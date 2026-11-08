"""D52: ``allow_project_opencode_edit`` becomes exact-path allows in the Carter agents' own
permissions (plan 003 step 11; RFC-0007 §4.5, App C.6.2; D71 moved them out of global policies)."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from carter.cli import main
from carter.guard import consent, optout, policies
from carter.guard.state import GuardState, save
from carter.identity import load_identity
from carter.install.mcp import config_target
from carter.install.paths import guard_state_path

REPO = Path(__file__).resolve().parents[2]


def glob(pattern: str, value: str) -> bool:
    rx = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.fullmatch(rx, value, flags=re.DOTALL) is not None


def write_toml(home: Path, workspaces: dict[str, bool]) -> None:
    lines = ["schema = 2", ""]
    for path, flag in workspaces.items():
        lines += [
            f'[workspaces."{path}"]',
            f"allow_project_opencode_edit = {str(flag).lower()}",
            "",
        ]
    carter = home / ".carter"
    carter.mkdir(parents=True, exist_ok=True)
    (carter / "config.toml").write_text("\n".join(lines))


def dbg(statements) -> str:
    items = [{"action": s.action, "resource": s.resource, "effect": s.effect} for s in statements]
    return json.dumps({"providers": {"anthropic": {}}, "policies": items})


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "work" / "proj"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def home(_hermetic_env: Path) -> Path:
    return _hermetic_env


class TestStatements:
    def test_three_exact_path_allows_per_workspace(self, home: Path, ws: Path) -> None:
        write_toml(home, {str(ws): True})
        found = optout.active_optouts(load_identity())
        assert found.workspaces == [str(ws.resolve())]
        sts = found.statements()
        real = str(ws.resolve())
        sid = hashlib.sha256(real.encode()).hexdigest()[:8]
        assert [(s.id, s.resource, s.effect, s.action) for s in sts] == [
            (f"optout-{sid}-json", f"edit:{real}/opencode.json", "allow", "tool.use"),
            (f"optout-{sid}-jsonc", f"edit:{real}/opencode.jsonc", "allow", "tool.use"),
            (f"optout-{sid}-dir", f"edit:{real}/.opencode/*", "allow", "tool.use"),
        ]
        assert {s.group for s in sts} == {"config-edit"}

    def test_a_symlinked_workspace_uses_its_real_path(
        self, home: Path, ws: Path, tmp_path: Path
    ) -> None:
        link = tmp_path / "link"
        link.symlink_to(ws)
        write_toml(home, {str(link): True})
        found = optout.active_optouts(load_identity())
        assert found.workspaces == [str(ws.resolve())]

    def test_false_flag_and_missing_dir_and_glob_paths_give_nothing(
        self, home: Path, tmp_path: Path
    ) -> None:
        odd = tmp_path / "we*ird"
        odd.mkdir()
        write_toml(
            home, {str(tmp_path / "off"): False, str(tmp_path / "gone"): True, str(odd): True}
        )
        found = optout.active_optouts(load_identity())
        assert found.workspaces == []
        assert len(found.refused) == 2
        assert any("not found" in r for r in found.refused) and any(
            "glob" in r for r in found.refused
        )

    def test_the_allows_come_after_every_deny_and_lift_only_that_workspace(
        self, home: Path, ws: Path
    ) -> None:
        write_toml(home, {str(ws): True})
        optouts = optout.active_optouts(load_identity()).statements()
        st = GuardState()
        st.consent("config-edit", "accepted", "2026-11-02")
        st.consent("g2", "accepted", "2026-11-02")
        got = consent.desired_statements(st, home=str(home), optouts=optouts)
        assert [s.id for s in got[-3:]] == [s.id for s in optouts]

        def verdict(path: str) -> str:
            v = "allow"
            for s in got:
                if s.resource.startswith("edit:") and glob(s.resource, f"edit:{path}"):
                    v = s.effect
            return v

        real = str(ws.resolve())
        assert verdict(f"{real}/opencode.json") == "allow"
        assert verdict(f"{real}/opencode.jsonc") == "allow"
        assert verdict(f"{real}/.opencode/agents/x.md") == "allow"
        # a worktree outside the workspace path gets nothing
        other = str(ws.parent / "proj-worktree")
        assert verdict(f"{other}/opencode.json") == "deny"
        assert verdict(f"{real}/.git/hooks/pre-commit") == "deny"
        assert verdict(f"{home}/.config/opencode/opencode.json") == "deny"

    def test_not_emitted_without_config_edit_consent(self, home: Path, ws: Path) -> None:
        write_toml(home, {str(ws): True})
        optouts = optout.active_optouts(load_identity()).statements()
        st = GuardState()
        st.consent("g2", "accepted", "2026-11-02")
        st.consent("config-edit", "declined", "2026-11-02")
        assert not [
            s
            for s in consent.desired_statements(st, home=str(home), optouts=optouts)
            if s.id.startswith("optout")
        ]


class TestRuntimeReadersNeverApply:
    def test_loading_config_and_importing_policy_modules_writes_nothing(
        self, home: Path, ws: Path
    ) -> None:
        write_toml(home, {str(ws): True})
        import importlib

        importlib.reload(policies)
        load_identity()
        from carter.ops.config import Config

        Config.load()
        assert not config_target(None).exists()
        assert not guard_state_path(None).exists()

    @pytest.mark.parametrize(
        "package",
        [
            "carter/ops",
            "carter/identity",
            "carter/state.py",
            "carter/plans.py",
            "carter/harness.py",
        ],
    )
    def test_runtime_modules_do_not_import_the_policy_writer(self, package: str) -> None:
        root = REPO / package
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        offenders = []
        for f in files:
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if any(n.startswith("carter.guard") for n in names):
                    offenders.append(str(f.relative_to(REPO)))
        assert offenders == []


class UpdateEnv:
    """A workspace + a consented guard state, ready for ``carter update``."""

    def __init__(self, home: Path, ws: Path, fake_opencode) -> None:
        self.home, self.ws, self.fake = home, ws, fake_opencode
        self.state = GuardState()
        for g in ("g2", "config-edit"):
            self.state.consent(g, "accepted", "2026-11-02")
        runner = CliRunner()
        assert (
            runner.invoke(main, ["init", str(ws), "--single"], catch_exceptions=False).exit_code
            == 0
        )

    def install_base(self) -> None:
        save(self.state, guard_state_path(None))

    def update(self, *args: str, human_tty: bool = False) -> tuple[int, str]:
        return _update(self.ws, args, human_tty)

    def rules(self) -> list[dict]:
        text = (self.ws / ".opencode" / "agents" / "carter-engineer-local.md").read_text()
        return yaml.safe_load(text.split("---", 2)[1])["permissions"]

    def opt_outs(self) -> list[str]:
        real = str(self.ws.resolve())
        return [
            r["resource"]
            for r in self.rules()
            if r["action"] == "edit" and r["effect"] == "allow" and r["resource"].startswith(real)
        ]


def _update(ws: Path, args: tuple[str, ...], human_tty: bool) -> tuple[int, str]:
    """``carter update`` asks nothing (D68 h), so the terminal makes no difference."""
    del human_tty
    res = CliRunner().invoke(main, ["update", "-v", str(ws), *args], catch_exceptions=False)
    return res.exit_code, res.output


@pytest.fixture
def env(home: Path, ws: Path, fake_opencode) -> UpdateEnv:
    return UpdateEnv(home, ws, fake_opencode)


class TestCarterUpdate:
    def test_a_workspace_without_opt_outs_gets_the_denies_and_no_allow(
        self, env: UpdateEnv
    ) -> None:
        env.install_base()
        code, out = env.update("--yes")
        assert code == 0
        assert {"action": "shell", "resource": "git push *", "effect": "deny"} in env.rules()
        assert env.opt_outs() == []

    def test_no_guard_state_means_update_never_adds_the_rules(self, env: UpdateEnv) -> None:
        write_toml(env.home, {str(env.ws): True})
        code, out = env.update("--yes")
        assert (
            code == 0 and not config_target(None).exists() and not guard_state_path(None).exists()
        )
        assert env.opt_outs() == []  # no consent on record: update never creates G2 rules

    def test_update_lists_nothing_and_applies_the_opt_out_to_the_workspace_agents(
        self, env: UpdateEnv
    ) -> None:
        env.install_base()
        write_toml(env.home, {str(env.ws): True})
        code, out = env.update("--yes")
        assert code == 0
        real = str(env.ws.resolve())
        assert env.opt_outs() == [
            f"{real}/opencode.json",
            f"{real}/opencode.jsonc",
            f"{real}/.opencode/*",
        ]
        deny_at = max(
            i for i, r in enumerate(env.rules()) if r["effect"] == "deny" and r["action"] == "edit"
        )
        allow_at = min(
            i for i, r in enumerate(env.rules()) if r["resource"] == f"{real}/opencode.json"
        )
        assert allow_at > deny_at  # last match wins: the allow lifts only that workspace

    def test_update_asks_nothing_and_applies_without_a_terminal_or_yes(
        self, env: UpdateEnv
    ) -> None:
        env.install_base()
        write_toml(env.home, {str(env.ws): True})
        code, out = env.update(human_tty=False)  # no --yes, no TTY, no question
        assert code == 0 and "[y/N]" not in out and "Not applied" not in out
        assert len(env.opt_outs()) == 3

    def test_an_agent_shell_never_refreshes_the_global_agents(
        self, env: UpdateEnv, monkeypatch
    ) -> None:
        env.install_base()
        write_toml(env.home, {str(env.ws): True})
        monkeypatch.setenv("AGENT", "x")
        code, out = env.update("--yes")
        assert code == 0 and "agent shells never change them" in out

    def test_dry_run_writes_nothing(self, env: UpdateEnv) -> None:
        env.install_base()
        write_toml(env.home, {str(env.ws): True})
        before = env.rules()
        code, out = env.update("--dry-run", "--yes")
        assert code == 0 and "would render" in out
        assert env.rules() == before and env.opt_outs() == []

    def test_removing_the_opt_out_removes_the_allows_on_the_next_update(
        self, env: UpdateEnv
    ) -> None:
        env.install_base()
        write_toml(env.home, {str(env.ws): True})
        env.update("--yes")
        assert len(env.opt_outs()) == 3
        write_toml(env.home, {str(env.ws): False})
        code, out = env.update("--yes")
        assert code == 0 and env.opt_outs() == []

    def test_a_corrupt_guard_state_does_not_block_update(self, env: UpdateEnv) -> None:
        guard_state_path(None).parent.mkdir(parents=True, exist_ok=True)
        guard_state_path(None).write_text("{broken")
        write_toml(env.home, {str(env.ws): True})
        code, out = env.update("--yes")
        assert code == 0 and guard_state_path(None).read_text() == "{broken"

    def test_a_declined_config_edit_group_gives_no_opt_out(self, env: UpdateEnv) -> None:
        env.state.consent("config-edit", "declined", "2026-11-02")
        env.install_base()
        write_toml(env.home, {str(env.ws): True})
        code, out = env.update("--yes")
        assert code == 0 and env.opt_outs() == []

    def test_a_refused_workspace_is_reported_by_check_host(
        self, env: UpdateEnv, tmp_path: Path
    ) -> None:
        from rows import check_host

        env.install_base()
        write_toml(env.home, {str(tmp_path / "gone"): True})
        out = check_host().output
        assert "D52 opt-out: not applied" in out and "not found" in out
