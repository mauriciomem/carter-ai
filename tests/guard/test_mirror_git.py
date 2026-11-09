"""The mirror written for real and read back the way the guard reads it.

Real git in the hermetic home. The guard's read form is
``git config --file <carter>/gitconfig --includes --get carter.<key>`` (a line a shell appended
to ``~/.gitconfig`` must not be able to outvote it). ``includeIf gitdir:`` is evaluated under that
form for a repo, a subdirectory and a linked worktree; the cap follows the **main repo's** git dir.
"""

# ruff: noqa: E501
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import mirror_io, update_mirror
from carter.guard.state import GuardState, load
from carter.identity import mirror
from carter.identity.schema import Identity, IdentityConfig, Signing, Workspace
from carter.identity.writer import write_config
from carter.install.paths import carter_gitconfig_path, guard_state_path
from guard.helpers import replace_others

LOGIN, UID = "llm-bot", 4242
EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"


def git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid", **(env or {})}  # fmt: skip
    return subprocess.run(["git", *args], cwd=cwd, env=full, capture_output=True, text=True)


def cfg(ws: dict[str, Workspace] | None = None) -> IdentityConfig:
    return IdentityConfig(
        identity=Identity(login=LOGIN, id=UID, email=EMAIL),
        signing=Signing(public_key=BLOB, fingerprint="SHA256:abc"),
        workspaces=ws or {},
        state="current",
    )


def guard_reads(base: Path, cwd: Path, key: str = "tier", *pre: str) -> str:
    done = git(
        cwd,
        *pre,
        "config",
        "--file",
        str(carter_gitconfig_path(base)),
        "--includes",
        "--get",
        f"carter.{key}",
    )
    return done.stdout.strip()


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path / "base"


def repo(path: Path) -> Path:
    path.mkdir(parents=True)
    assert git(path, "init", "-q").returncode == 0
    git(path, "commit", "-q", "--allow-empty", "-m", "i")
    return path


class TestGuardReadForm:
    def test_capped_inside_the_workspace_base_value_outside_absent_is_t0(
        self, tmp_path: Path, base: Path
    ) -> None:
        ws = tmp_path / "ws"
        inside, outside = repo(ws / "r1"), repo(tmp_path / "other" / "r2")
        (inside / "src" / "deep").mkdir(parents=True)
        state = GuardState()
        mirror_io.sync(base, state, cfg({str(ws): Workspace(max_tier="t1")}))
        assert guard_reads(base, inside) == guard_reads(base, inside / "src" / "deep") == "t1"
        assert guard_reads(base, outside) == "t2"
        assert guard_reads(base, outside, "llmEmail") == EMAIL
        assert guard_reads(base, outside, "llmFingerprint") == "SHA256:abc"
        mirror_io.sync(base, state, IdentityConfig(state="absent"))
        assert guard_reads(base, inside) == ""  # file gone: absent = t0 by the script's default

    def test_command_line_environment_and_local_values_have_no_effect(
        self, tmp_path: Path, base: Path
    ) -> None:
        r = repo(tmp_path / "ws" / "r")
        mirror_io.sync(base, GuardState(), cfg())
        assert guard_reads(base, r, "tier", "-c", "carter.tier=t0") == "t2"
        env = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "carter.tier",
            "GIT_CONFIG_VALUE_0": "t0",
        }
        done = git(
            r,
            "config",
            "--file",
            str(carter_gitconfig_path(base)),
            "--includes",
            "--get",
            "carter.tier",
            env=env,
        )
        assert done.stdout.strip() == "t2"
        git(r, "config", "--local", "carter.tier", "t0")
        assert guard_reads(base, r) == "t2"

    def test_a_line_appended_to_the_global_config_cannot_outvote_the_file(
        self, tmp_path: Path, base: Path
    ) -> None:
        """~/.gitconfig is shell-writable; the guard must not read through it."""
        r = repo(tmp_path / "r")
        mirror_io.sync(base, GuardState(), cfg())
        glob = Path(os.environ["GIT_CONFIG_GLOBAL"])
        glob.write_text(
            glob.read_text()
            + f"[include]\n\tpath = {carter_gitconfig_path(base)}\n[carter]\n\ttier = t0\n"
        )
        assert (
            git(r, "config", "--global", "--includes", "--get", "carter.tier").stdout.strip()
            == "t0"
        )
        assert guard_reads(base, r) == "t2"

    def test_a_symlinked_workspace_path_is_normalised(self, tmp_path: Path, base: Path) -> None:
        real = tmp_path / "real"
        link = tmp_path / "link"
        r = repo(real / "r")
        link.symlink_to(real)
        mirror_io.sync(base, GuardState(), cfg({str(link): Workspace(max_tier="t1")}))
        assert guard_reads(base, r) == "t1"
        assert guard_reads(base, link / "r") == "t1"


class TestWorktrees:
    """The main repo's git dir decides, not the worktree path."""

    def test_the_cap_follows_the_main_repo(self, tmp_path: Path, base: Path) -> None:
        ws, out = tmp_path / "ws", tmp_path / "out"
        main_in, main_out = repo(ws / "main-in"), repo(out / "main-out")
        git(main_in, "worktree", "add", "-q", str(ws / "wt-in-of-in"), "-b", "w1")
        git(main_in, "worktree", "add", "-q", str(out / "wt-out-of-in"), "-b", "w2")
        git(main_out, "worktree", "add", "-q", str(ws / "wt-in-of-out"), "-b", "w3")
        git(main_out, "worktree", "add", "-q", str(out / "wt-out-of-out"), "-b", "w4")
        mirror_io.sync(base, GuardState(), cfg({str(ws): Workspace(max_tier="t1")}))
        assert guard_reads(base, ws / "wt-in-of-in") == "t1"
        assert (
            guard_reads(base, out / "wt-out-of-in") == "t1"
        )  # outside the workspace, still capped
        assert guard_reads(base, ws / "wt-in-of-out") == "t2"  # inside the workspace, NOT capped
        assert guard_reads(base, out / "wt-out-of-out") == "t2"

    def test_worktree_cap_gaps_lists_both_cases_without_running_git(self, tmp_path: Path) -> None:
        ws, out = tmp_path / "ws", tmp_path / "out"
        main_in, main_out = repo(ws / "main-in"), repo(out / "main-out")
        git(main_in, "worktree", "add", "-q", str(out / "wt-out-of-in"), "-b", "w2")
        git(main_out, "worktree", "add", "-q", str(ws / "wt-in-of-out"), "-b", "w3")
        git(main_in, "worktree", "add", "-q", str(ws / "wt-in-of-in"), "-b", "w1")
        gaps = mirror.worktree_cap_gaps(str(ws))
        assert gaps.fail_open == [str((ws / "wt-in-of-out").resolve())]
        assert gaps.capped_outside == [str((out / "wt-out-of-in").resolve())]


class TestMirrorIo:
    def test_hook_and_alias_entries_are_carried_over_and_the_mirror_replaced(
        self, base: Path
    ) -> None:
        state = GuardState()
        file = carter_gitconfig_path(base)
        others = [("hook.carter-guard-pre-push.event", "pre-push"), ("alias.ai-commit", '!cd "${GIT_PREFIX:-.}" && carter commit')]  # fmt: skip
        mirror_io.write_entries(base, state, [], others, {})
        mirror_io.sync(base, state, cfg())
        keys = [k for k, _ in mirror_io.read_entries(file)]
        assert keys[:3] == list(mirror.CARTER_KEYS) and keys[3:] == [k for k, _ in others]
        mirror_io.sync(base, state, IdentityConfig(state="absent"))
        assert mirror_io.read_entries(file) == others  # the mirror left, the rest stayed
        assert (
            dict(mirror_io.read_entries(file))["alias.ai-commit"] == others[1][1]
        )  # git quoted it

    def test_guard_replacement_keeps_the_mirror_and_fragments(
        self, tmp_path: Path, base: Path
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        state = GuardState()
        mirror_io.sync(base, state, cfg({str(ws): Workspace(max_tier="t1")}))
        replace_others(base, state, [("hook.carter-guard-pre-push.event", "pre-push")])
        keys = [k for k, _ in mirror_io.read_entries(carter_gitconfig_path(base))]
        assert (
            keys[0] == "carter.tier"
            and keys[-1].startswith("hook.")
            and any(k.startswith("includeIf.") for k in keys)
        )
        replace_others(base, state, [])
        assert [k for k, _ in mirror_io.read_entries(carter_gitconfig_path(base))][
            0
        ] == "carter.tier"
        assert len(list((carter_gitconfig_path(base).parent / "gitconfig.d").iterdir())) == 1

    def test_hashes_are_recorded_and_an_edited_file_or_fragment_is_kept(
        self, tmp_path: Path, base: Path
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        state = GuardState()
        c = cfg({str(ws): Workspace(max_tier="t1")})
        first = mirror_io.sync(base, state, c)
        assert first.status == "created" and len(first.fragments_written) == 1
        main = carter_gitconfig_path(base)
        frag = Path(first.fragments_written[0])
        assert state.owned_unchanged(main) and state.owned_unchanged(frag)
        assert mirror_io.sync(base, state, c).status == "unchanged"
        frag.write_text("[carter]\n\ttier = t0\n")  # the user edited the fragment
        second = mirror_io.sync(base, state, c)
        assert str(frag) in second.kept and frag.read_text() == "[carter]\n\ttier = t0\n"
        main.write_text(main.read_text() + "# mine\n")
        third = mirror_io.sync(base, state, cfg({str(ws): Workspace(max_tier="t0")}))
        assert third.status == "edited-kept" and "# mine" in main.read_text()

    def test_a_removed_cap_removes_its_fragment_only_if_unchanged(
        self, tmp_path: Path, base: Path
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        state = GuardState()
        mirror_io.sync(base, state, cfg({str(ws): Workspace(max_tier="t1")}))
        out = mirror_io.sync(base, state, cfg())
        assert len(out.fragments_removed) == 1
        assert not (carter_gitconfig_path(base).parent / "gitconfig.d").exists()

    def test_the_rendered_file_parses_with_awkward_values(self, base: Path) -> None:
        # `;`, `#`, quotes and spaces in a value are rendered by git itself
        weird = IdentityConfig(
            identity=Identity(login=LOGIN, id=UID, email=EMAIL),
            signing=Signing(public_key=BLOB, fingerprint='SHA256:a;b #c "d" e'),
            state="current",
        )
        mirror_io.sync(base, GuardState(), weird)
        assert (
            dict(mirror_io.read_entries(carter_gitconfig_path(base)))["carter.llmFingerprint"]
            == 'SHA256:a;b #c "d" e'
        )


class TestUpdateCommand:
    """`carter update`: diff, confirmation, refusal, no write to the user's global config."""

    @pytest.fixture
    def world(self, tmp_path: Path) -> Path:
        home = Path(os.environ["HOME"])
        ws = tmp_path / "ws"
        ws.mkdir()
        assert CliRunner().invoke(main, ["init", str(ws), "--no-git-state"]).exit_code == 0
        (home / ".carter").mkdir(exist_ok=True)
        write_config(
            cfg({str(ws.resolve()): Workspace(max_tier="t1")}), home / ".carter" / "config.toml"
        )
        return ws

    def test_yes_writes_the_mirror_and_never_the_global_config(self, world: Path) -> None:
        glob = Path(os.environ["GIT_CONFIG_GLOBAL"])
        before = glob.read_bytes()
        done = CliRunner().invoke(main, ["update", "-v", str(world)])  # asks nothing ()
        assert done.exit_code == 0, done.output
        assert "+ carter.tier = t2" in done.output and "tier mirror written" in done.output
        assert glob.read_bytes() == before
        home = Path(os.environ["HOME"])
        assert mirror_io.read_entries(home / ".carter" / "gitconfig")[0] == ("carter.tier", "t2")
        recorded = load(guard_state_path(None))
        assert any(f["path"].endswith("/gitconfig") for f in recorded.files)
        assert len(list((home / ".carter" / "gitconfig.d").iterdir())) == 1

    def test_dry_run_writes_nothing_and_an_agent_shell_never_writes(self, world: Path) -> None:
        home = Path(os.environ["HOME"])
        dry = CliRunner().invoke(main, ["update", str(world), "--dry-run"])
        assert "dry run" in dry.output and not (home / ".carter" / "gitconfig").exists()
        agent = CliRunner().invoke(main, ["update", str(world)], env={"AGENT": "1"})
        assert "agent shells never change it" in agent.output
        assert not (home / ".carter" / "gitconfig").exists()

    def test_a_second_update_changes_nothing_and_prints_no_diff(self, world: Path) -> None:
        CliRunner().invoke(main, ["update", str(world), "--yes"])
        again = CliRunner().invoke(main, ["update", "-v", str(world), "--yes"])
        assert "carter.tier" not in again.output

    def test_a_cap_below_the_pinned_require_tier_is_refused(self, world: Path) -> None:
        home = Path(os.environ["HOME"])
        c = cfg({str(world.resolve()): Workspace(max_tier="t1", require_tier="t2")})
        write_config(c, home / ".carter" / "config.toml")
        assert "E-TIER-REQUIRED" in update_mirror.plan(None, c).refusal
        try:
            update_mirror.apply(None, c)
        except mirror.MirrorError as exc:
            assert "E-TIER-REQUIRED" in str(exc)
        assert not (home / ".carter" / "gitconfig").exists()  # nothing was written
        # through `carter update`: carter.yaml asks for t2, config.toml caps at t1
        yml = world / ".carter" / "carter.yaml"
        import yaml

        data = yaml.safe_load(yml.read_text())
        data["identity"] = {"require_tier": "t2"}
        yml.write_text(yaml.dump(data))
        done = CliRunner().invoke(main, ["update", str(world), "--yes"])
        assert done.exit_code != 0 and "below require_tier" in done.output
        assert not (home / ".carter" / "gitconfig").exists()

    def test_it_prints_the_include_line_only_when_hooks_or_alias_need_it(self, world: Path) -> None:
        home = Path(os.environ["HOME"])
        CliRunner().invoke(main, ["update", str(world), "--yes"])
        assert update_mirror.include_hint(None) is None  # only the mirror: the guard reads the file
        state = load(guard_state_path(None))
        replace_others(None, state, [("alias.ai-commit", "!true")])
        assert (
            update_mirror.include_hint(None)
            == f"git config --global --add include.path {home}/.carter/gitconfig"
        )
