# ruff: noqa: E501
"""``carter check --host``: the identity items.

The identity is made with the real ``identity add`` against the loopback fake GitHub. The
command stays read-only and names-only; the account's key lists are read without credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from carter import hostcheck_id, identity_add
from carter.checkitems import Item
from carter.guard import mirror_io
from carter.guard.state import load, save
from carter.identity.agent_probe import Probe
from carter.identity.config import load_identity
from carter.identity.schema import Workspace
from carter.identity.writer import write_config
from carter.install.paths import guard_state_path
from gh_api import FakeGitHub, Reply
from rows import check_host
from ssh_rig import KeyPair, real_ssh

LOGIN, UID = "octocat", 583231
SENTINEL = "SECRET-SENTINEL-DO-NOT-PRINT"


@pytest.fixture
def home() -> Path:
    return Path(os.environ["HOME"])


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    server = FakeGitHub().start()
    monkeypatch.setenv("GITHUB_API_URL", server.url)
    server.public_world()
    yield server
    server.stop()


@pytest.fixture
def key(throwaway_key: Callable[..., KeyPair]) -> KeyPair:
    return throwaway_key("ed25519")


def register(fake: FakeGitHub, blob: str, auth: tuple[str, ...] = ()) -> None:
    items = [{"id": 1, "key": blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
    fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
    fake.on("GET", f"/{LOGIN}.keys", Reply(200, "\n".join(auth), content_type="text/plain"))


def make(fake: FakeGitHub, key: KeyPair, sock: str = "/run/pm/agent.sock") -> None:
    register(fake, key.blob)
    identity_add.apply_add(
        identity_add.plan_add(identity_add.AddRequest(LOGIN, str(key.pub_path), None, sock, None))
    )


def run(
    cwd: Path, *, fetch: hostcheck_id.Fetch | None = None, git: tuple[int, int] | None = (2, 56)
) -> list[Item]:
    cfg = load_identity()
    state = load(guard_state_path(None))
    from carter.identity.env import workspace_for

    return hostcheck_id.identity_items(
        cfg, state, cwd=cwd, git=git, fetch=fetch, workspace=workspace_for(cfg, str(cwd))
    )


def find(items: list[Item], area: str, needle: str = "") -> Item | None:
    return next((i for i in items if i.area == area and needle in i.text), None)


def levels(items: list[Item], area: str) -> list[str]:
    return [i.level for i in items if i.area == area]


class TestMirror:
    def test_in_sync_is_ok(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        assert levels(run(tmp_path), "hook tier") == ["ok"]

    def test_a_missing_file_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        (home / ".carter" / "gitconfig").unlink()
        item = find(run(tmp_path), "hook tier", "missing")
        assert item and item.level == "red" and item.fix == "Run `carter update`."

    def test_a_wrong_email_or_fingerprint_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        cfg_file = home / ".carter" / "gitconfig"
        # the user's edit is not Carter's file any more, but the value the guard reads is what matters
        cfg_file.write_text(cfg_file.read_text().replace(key.fingerprint, "SHA256:other"))
        assert find(run(tmp_path), "hook tier", "carter.llmFingerprint differs")

    def test_a_cap_added_without_update_is_red_because_the_guard_still_reads_t2(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        ws = tmp_path / "ws"
        ws.mkdir()
        write_config(
            replace(load_identity(), workspaces={str(ws.resolve()): Workspace(max_tier="t1")}),
            home / ".carter" / "config.toml",
        )
        item = find(run(ws), "hook tier", "config.toml allows t1")
        assert item and item.level == "red" and "agent commits fail" in item.text

    def test_a_cap_removed_without_update_is_red_too_and_t1_vs_t0_is_only_a_warning(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        ws = tmp_path / "ws"
        ws.mkdir()
        import subprocess

        subprocess.run(
            ["git", "init", "-q", str(ws)], check=True, capture_output=True
        )  # includeIf needs a repo
        capped = replace(load_identity(), workspaces={str(ws.resolve()): Workspace(max_tier="t1")})
        state = load(guard_state_path(None))
        mirror_io.sync(None, state, capped)
        save(state, guard_state_path(None))
        write_config(
            replace(capped, workspaces={}), home / ".carter" / "config.toml"
        )  # cap removed in config.toml only
        assert find(run(ws), "hook tier", "config.toml allows t2").level == "red"  # type: ignore[union-attr]
        # t0 cap vs t1 mirror: no T2 involved, the trailer differs only
        t0 = replace(capped, workspaces={str(ws.resolve()): Workspace(max_tier="t0")})
        write_config(t0, home / ".carter" / "config.toml")
        item = find(run(ws), "hook tier", "config.toml allows t0")
        assert item and item.level == "warn"


class TestFragmentsAndWorktrees:
    def capped(self, home: Path, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        cfg = replace(load_identity(), workspaces={str(ws.resolve()): Workspace(max_tier="t1")})
        write_config(cfg, home / ".carter" / "config.toml")
        state = load(guard_state_path(None))
        mirror_io.sync(None, state, cfg)
        save(state, guard_state_path(None))
        return ws

    def test_a_good_fragment_is_ok(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        ws = self.capped(home, tmp_path)
        assert levels(run(ws), "workspace cap") == ["ok"]

    def test_a_malformed_fragment_is_red_and_says_git_fails_there(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        self.capped(home, tmp_path)
        (frag,) = (home / ".carter" / "gitconfig.d").iterdir()
        frag.write_text("[carter\n\ttier = broken\n")
        item = find(run(tmp_path), "workspace cap", "malformed")
        assert (
            item
            and item.level == "red"
            and "git fails in that workspace" in item.text
            and str(frag) in item.fix
        )

    def test_a_missing_fragment_is_red_and_an_edited_one_is_a_warning(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        self.capped(home, tmp_path)
        (frag,) = (home / ".carter" / "gitconfig.d").iterdir()
        frag.write_text(frag.read_text() + "# mine\n")
        assert levels(run(tmp_path), "workspace cap") == ["warn"]
        frag.unlink()
        assert levels(run(tmp_path), "workspace cap") == ["red"]

    def test_worktree_gaps_are_warnings_naming_the_path(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        import subprocess

        make(fake, key)
        ws = self.capped(home, tmp_path)
        outside = tmp_path / "outside"
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "a",
            "GIT_AUTHOR_EMAIL": "a@e",
            "GIT_COMMITTER_NAME": "a",
            "GIT_COMMITTER_EMAIL": "a@e",
        }
        for argv, cwd in (
            (["init", "-q", str(outside)], tmp_path),
            (["commit", "-q", "--allow-empty", "-m", "i"], outside),
            (["worktree", "add", "-q", str(ws / "wt"), "-b", "w"], outside),
        ):
            subprocess.run(["git", *argv], cwd=cwd, env=env, check=True, capture_output=True)
        items = [i for i in run(ws) if i.area == "worktree"]
        assert (
            len(items) == 1
            and items[0].level == "warn"
            and str((ws / "wt").resolve()) in items[0].text
            and "does NOT apply" in items[0].text
        )


class TestShimAndAgent:
    def test_shim_ok_and_socket_agreement(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        items = run(tmp_path)
        assert find(items, "signing helper", "is Carter's and unchanged").level == "ok"  # type: ignore[union-attr]
        assert not find(items, "signing helper", "another agent socket")

    def test_an_edited_shim_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        shim = home / ".carter" / "bin" / "carter-ssh-sign"
        shim.write_text(shim.read_text() + "# edited\n")
        item = find(run(tmp_path), "signing helper", "agent commits fail")
        assert item and item.level == "red"

    def test_a_shim_naming_another_socket_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        cfg = load_identity()
        write_config(
            replace(cfg, signing=replace(cfg.signing, agent_socket="/tmp/moved.sock")),
            home / ".carter" / "config.toml",
        )
        assert find(run(tmp_path), "signing helper", "another agent socket").level == "red"  # type: ignore[union-attr]

    def test_a_missing_allowed_signers_is_a_warning(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        (home / ".carter" / "hooks" / "allowed_signers").unlink()
        assert find(run(tmp_path), "allowed_signers").level == "warn"  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        ("state", "level", "needle"),
        [
            ("ok", "ok", "loaded"),
            ("empty", "info", "will fail until you unlock"),
            ("none", "info", "will fail until you unlock"),
            ("wrong-key", "warn", "other keys"),
            ("stale", "warn", "does not answer"),
            ("bad", "red", "not our agent socket"),
        ],
    )
    def test_every_agent_state_has_its_level(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        state: str,
        level: str,
        needle: str,
    ) -> None:
        make(fake, key)
        monkeypatch.setattr(hostcheck_id, "probe_setup", lambda *_a: Probe(state))
        item = find(run(tmp_path), "signing agent")
        assert item and item.level == level and needle in item.text

    @real_ssh
    def test_the_real_probe_sees_the_loaded_key(
        self, home: Path, fake: FakeGitHub, key: KeyPair, real_ssh_agent, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        make(fake, key, str(real_ssh_agent.sock))
        assert find(run(tmp_path), "signing agent").level == "info"  # type: ignore[union-attr]
        assert real_ssh_agent.add(key) == 0
        assert find(run(tmp_path), "signing agent").level == "ok"  # type: ignore[union-attr]


class TestHygiene:
    def test_a_key_registered_for_login_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        register(fake, key.blob, auth=(key.blob,))
        item = find(run(tmp_path, fetch=hostcheck_id.live_fetch), "key on GitHub", "AUTHENTICATION")
        assert item and item.level == "red"

    def test_a_clean_account_is_ok_and_requests_carry_no_credentials(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        make(fake, key)
        monkeypatch.setenv("GH_TOKEN", SENTINEL)
        fake.requests.clear()
        items = run(tmp_path, fetch=hostcheck_id.live_fetch)
        assert levels(items, "key on GitHub") == ["ok"]
        assert (
            fake.requests
            and fake.authorized_requests() == []
            and SENTINEL not in json.dumps([r.headers for r in fake.requests])
        )

    def test_a_key_missing_from_the_signing_list_is_a_warning(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        tmp_path: Path,
        throwaway_key: Callable[..., KeyPair],
    ) -> None:
        make(fake, key)
        register(fake, throwaway_key("ed25519").blob)
        item = find(
            run(tmp_path, fetch=hostcheck_id.live_fetch), "key on GitHub", "not an SSH signing key"
        )
        assert item and item.level == "warn"

    def test_offline_is_info_not_a_failure(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        fake.on("GET", f"/{LOGIN}.keys", Reply(502, "{}"))
        fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(502, "{}"))
        got = levels(run(tmp_path, fetch=hostcheck_id.live_fetch), "key on GitHub")
        assert got == ["info", "info"]
        assert levels(run(tmp_path, fetch=None), "key on GitHub") == ["info"]


class TestGuardsAndGroups:
    def test_t2_without_any_guard_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        item = find(run(tmp_path), "guards", "commit hooks")
        assert item and item.level == "red"

    def test_a_declined_hooks_group_is_named_with_the_command_that_asks_again(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        state = load(guard_state_path(None))
        state.consent("hooks", "declined", "2026-11-08", 2)
        save(state, guard_state_path(None))
        item = find(run(tmp_path), "guards", "commit hooks")
        assert item and item.level == "red"
        assert "declined" in item.text and "2026-11-08" in item.text
        assert "carter guard install --only hooks" in item.fix

    def test_on_an_old_git_the_group_to_ask_again_is_repo_hooks(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        state = load(guard_state_path(None))
        state.consent("repo_hooks", "declined", "2026-11-08", 2)
        save(state, guard_state_path(None))
        item = find(run(tmp_path, git=(2, 45)), "guards", "commit hooks")
        assert item and "carter guard install --only repo_hooks" in item.fix

    def test_when_nothing_was_declined_the_plain_command_is_the_fix(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        item = find(run(tmp_path), "guards", "commit hooks")
        assert item and "declined" not in item.text
        assert item.fix == "Run `carter guard install` in your terminal."

    def test_with_hooks_the_note_is_info_and_old_git_is_red(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        state = load(guard_state_path(None))
        state.consent("hooks", "accepted", "2026-11-04", 2)
        save(state, guard_state_path(None))
        items = run(tmp_path, git=(2, 39))
        assert find(items, "guards", "cannot be signed").level == "info"  # type: ignore[union-attr]
        assert find(items, "git", "E-GIT-OLD").level == "red"  # type: ignore[union-attr]

    def test_the_alias_consent_is_listed(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        items = run(tmp_path)
        assert find(items, "consent", "alias").level == "info"  # type: ignore[union-attr]

    def test_no_identity_no_items(self, home: Path, tmp_path: Path) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        assert (
            hostcheck_id.identity_items(
                load_identity(),
                load(guard_state_path(None))
                if guard_state_path(None).exists()
                else __import__("carter.guard.state", fromlist=["GuardState"]).GuardState(),
                cwd=tmp_path,
            )
            == []
        )

    def test_t1_gets_the_mirror_but_no_key_items(
        self, home: Path, fake: FakeGitHub, tmp_path: Path
    ) -> None:
        identity_add.apply_add(identity_add.plan_add(identity_add.AddRequest(LOGIN)))
        areas = {i.area for i in run(tmp_path)}
        assert "hook tier" in areas and not areas & {
            "signing helper",
            "signing agent",
            "key on GitHub",
            "guards",
        }


class TestTheCommand:
    def host(self, cwd: Path) -> tuple[int, str]:

        done = check_host(str(cwd))
        return done.exit_code, done.output

    def test_it_is_read_only_prints_names_only_and_exits_1_on_red(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        make(fake, key)
        monkeypatch.setenv("GH_TOKEN", SENTINEL)
        before = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(home.rglob("*"))
            if p.is_file()
        }
        code, out = self.host(tmp_path)
        after = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(home.rglob("*"))
            if p.is_file()
        }
        assert before == after
        assert (
            code == 1
            and "RED   guards: the LLM signing key (T2) is set up but the commit hooks are not installed"
            in out
        )
        assert SENTINEL not in out and key.blob not in out and str(key.pub_path) not in out
        assert "OK    key on GitHub: the key is absent from the account's login keys" in out
        assert fake.authorized_requests() == []
