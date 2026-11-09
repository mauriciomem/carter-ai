# ruff: noqa: E501
"""``carter identity remove`` ADR removable, and only if unchanged).

The identity is made with the real ``identity add`` code against the loopback fake GitHub. The
dedicated agent case uses a throwaway ssh-agent as the "password manager" socket.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import identity_add, identity_remove, terminal
from carter.cli import main
from carter.guard import mirror_io
from carter.guard.state import load
from carter.identity.config import load_identity
from carter.identity.errors import E_HUMAN_TERMINAL
from carter.identity.schema import Workspace
from carter.identity.writer import write_config
from carter.install.paths import guard_state_path
from gh_api import FakeGitHub, Reply
from guard.helpers import replace_others
from ssh_rig import KeyPair

LOGIN, UID = "octocat", 583231
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"


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
def human(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(terminal, "_isatty", lambda _s: True)


def tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def t2(fake: FakeGitHub, key: KeyPair, sock: str = "/run/pm/agent.sock") -> None:
    items = [{"id": 1, "key": key.blob, "title": "t", "created_at": "2026-01-01T00:00:00Z"}]
    fake.on("GET", f"/users/{LOGIN}/ssh_signing_keys", Reply(200, json.dumps(items)))
    fake.on("GET", f"/{LOGIN}.keys", Reply(200, "", content_type="text/plain"))
    req = identity_add.AddRequest(LOGIN, str(key.pub_path), None, sock, None)
    identity_add.apply_add(identity_add.plan_add(req))


def remove(*args: str, env: dict[str, str] | None = None, input: str | None = None):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(
        main, ["identity", "remove", *args], env=env, input=input, catch_exceptions=False
    )


@pytest.fixture
def key(throwaway_key: Callable[..., KeyPair]) -> KeyPair:
    return throwaway_key("ed25519")


class TestRemoval:
    def test_everything_identity_goes_and_the_pre_install_tree_comes_back(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        before = tree(home)
        t2(fake, key)
        assert (home / ".carter" / "bin" / "carter-ssh-sign").exists()
        report = identity_remove.remove_identity()
        after = {k: v for k, v in tree(home).items() if not k.startswith(".carter/backups/")}
        assert after == before, sorted(set(after) ^ set(before))
        assert not report.kept
        assert list(
            (home / ".carter" / "backups").rglob("config.toml")
        )  # the one documented exception
        assert not (home / ".carter" / "bin").exists() or not any(
            (home / ".carter" / "bin").iterdir()
        )

    def test_the_config_keeps_pins_and_the_footer_and_loses_the_identity(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        t2(fake, key)
        cfg = load_identity(home / ".carter" / "config.toml")
        write_config(
            replace(cfg, workspaces={str(tmp_path): Workspace(max_tier="t1")}),
            home / ".carter" / "config.toml",
        )
        identity_remove.remove_identity()
        left = load_identity(home / ".carter" / "config.toml")
        assert (
            left.identity.login == ""
            and left.signing.public_key == ""
            and left.signing.fingerprint == ""
        )
        assert left.workspaces[str(tmp_path)].max_tier == "t1"
        assert list((home / ".carter" / "backups").rglob("config.toml"))

    def test_edited_files_are_kept_and_reported(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        shim = home / ".carter" / "bin" / "carter-ssh-sign"
        shim.write_text(shim.read_text() + "# mine\n")
        allowed = home / ".carter" / "hooks" / "allowed_signers"
        allowed.write_text(allowed.read_text() + "# mine\n")
        main_file = home / ".carter" / "gitconfig"
        main_file.write_text(main_file.read_text() + "# mine\n")
        report = identity_remove.remove_identity()
        assert shim.exists() and allowed.exists() and main_file.exists()
        text = "\n".join(report.kept)
        assert str(shim) in text and str(allowed) in text and f"{main_file} (edited" in text
        assert "# mine" in shim.read_text()

    def test_an_edited_fragment_is_kept_and_a_clean_one_removed(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        t2(fake, key)
        cfg = load_identity(home / ".carter" / "config.toml")
        cfg2 = replace(cfg, workspaces={str(ws): Workspace(max_tier="t1")})
        write_config(cfg2, home / ".carter" / "config.toml")
        state = load(guard_state_path(None))
        mirror_io.sync(None, state, cfg2)
        from carter.guard.state import save

        save(state, guard_state_path(None))
        (frag,) = list((home / ".carter" / "gitconfig.d").iterdir())
        frag.write_text(frag.read_text() + "# mine\n")
        report = identity_remove.remove_identity()
        assert frag.exists() and any(str(frag) in k for k in report.kept)

    def test_hooks_and_the_alias_in_the_same_file_stay(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        state = load(guard_state_path(None))
        replace_others(
            None,
            state,
            [("hook.carter-guard-pre-push.event", "pre-push"), ("alias.ai-commit", "!true")],
        )
        from carter.guard.state import save

        save(state, guard_state_path(None))
        identity_remove.remove_identity()
        keys = [k for k, _ in mirror_io.read_entries(home / ".carter" / "gitconfig")]
        assert keys == ["hook.carter-guard-pre-push.event", "alias.ai-commit"]
        assert guard_state_path(None).exists()  # the file's record is still needed

    def test_a_dry_run_changes_nothing(self, home: Path, fake: FakeGitHub, key: KeyPair) -> None:
        t2(fake, key)
        before = tree(home)
        report = identity_remove.remove_identity(dry_run=True)
        assert tree(home) == before and report.verb == "Would remove" and report.removed

    def test_running_it_twice_or_with_nothing_installed_is_fine(self, home: Path) -> None:
        before = tree(home)
        first = identity_remove.remove_identity()
        assert not first.removed and not first.kept
        assert tree(home) == before

    def test_a_corrupt_config_is_left_alone_and_the_files_still_go(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        (home / ".carter" / "config.toml").write_text("schema = 2\nbroken [[[")
        report = identity_remove.remove_identity()
        assert (home / ".carter" / "config.toml").read_text().startswith("schema = 2\nbroken")
        assert any("not valid" in k for k in report.kept)
        assert not (home / ".carter" / "bin" / "carter-ssh-sign").exists()

    def test_a_corrupt_guard_state_proves_nothing_so_nothing_is_deleted(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        guard_state_path(None).write_text("{broken")
        report = identity_remove.remove_identity()
        assert (home / ".carter" / "bin" / "carter-ssh-sign").exists()
        assert any("corrupt" in k for k in report.kept)


class TestCommand:
    def test_it_asks_nothing_and_says_it_in_one_line(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        done = remove()  # no input, no terminal: we have backups
        assert done.exit_code == 0, done.output
        assert len(done.output.splitlines()) == 1 and "removed the LLM identity" in done.output
        assert "your key file stay" in done.output
        assert not (home / ".carter" / "bin" / "carter-ssh-sign").exists()

    def test_verbose_lists_what_went(self, home: Path, fake: FakeGitHub, key: KeyPair) -> None:
        t2(fake, key)
        done = remove("-v")
        assert done.exit_code == 0 and "carter-ssh-sign" in done.output

    def test_yes_needs_no_terminal_but_an_agent_shell_is_always_refused(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        agent = remove("--yes", env={"AGENT": "1"})
        assert agent.exit_code == 1 and E_HUMAN_TERMINAL in agent.output
        assert (home / ".carter" / "bin" / "carter-ssh-sign").exists()
        assert remove("--yes").exit_code == 0

    def test_dry_run_works_anywhere_and_writes_nothing(
        self, home: Path, fake: FakeGitHub, key: KeyPair
    ) -> None:
        t2(fake, key)
        before = tree(home)
        done = remove("--dry-run", env={"AGENT": "1"})
        assert done.exit_code == 0 and "would remove the LLM identity" in done.output
        assert tree(home) == before

    def test_nothing_installed_says_so(self, home: Path) -> None:
        done = remove("--yes")
        assert done.exit_code == 0 and "no LLM identity here" in done.output
