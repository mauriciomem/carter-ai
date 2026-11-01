"""Tests for carter.state git operations — the recovery primitive.

``commit_state`` is what makes "I deleted a plan/session" recoverable: the nested
.carter/.git must carry ongoing history beyond the single init commit.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from carter.config import generate_default_config
from carter.state import commit_state, init_workspace


@pytest.fixture
def config() -> dict:
    cfg = generate_default_config(workspace_name="state-test", mode="umbrella")
    cfg["agent_suffix"] = ""
    return cfg


def _git(carter_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=carter_dir, capture_output=True, text=True, check=False
    )


class TestCommitState:
    def test_init_makes_exactly_one_commit(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        log = _git(carter_dir, "log", "--oneline")
        assert "init carter state" in log.stdout
        assert len(log.stdout.strip().splitlines()) == 1

    def test_commits_new_changes(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        (carter_dir / "state" / "sessions" / "checkpoint.md").write_text(
            "---\nupdated: 2026-06-09\n---\n", encoding="utf-8"
        )
        assert commit_state(carter_dir, "test: add checkpoint") is True
        log = _git(carter_dir, "log", "--oneline")
        assert "add checkpoint" in log.stdout
        assert len(log.stdout.strip().splitlines()) == 2

    def test_returns_false_when_nothing_to_commit(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        # init already committed everything; nothing new staged
        assert commit_state(carter_dir, "test: noop") is False

    def test_returns_false_without_git_repo(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=False)
        assert not (carter_dir / ".git").exists()
        assert commit_state(carter_dir, "test: no repo") is False

    def test_deleted_plan_is_recoverable(self, tmp_path, config):
        """The headline recovery contract: a deleted plan dir is restorable."""
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        plan = carter_dir / "state" / "plans" / "active" / "001-x"
        plan.mkdir(parents=True)
        (plan / "README.md").write_text("---\nid: 001-x\n---\n", encoding="utf-8")
        commit_state(carter_dir, "test: add plan 001-x")

        shutil.rmtree(plan)
        assert not plan.exists()

        _git(carter_dir, "checkout", "HEAD", "--", "state/plans/active/001-x/README.md")
        assert (plan / "README.md").exists()

    def test_failed_git_add_raises_not_masked(self, tmp_path):
        """A broken repo (.git is a file, not a dir) makes `git add` fail; that
        must surface as StateError, not a silent 'nothing to commit'."""
        from carter.state import StateError

        carter_dir = tmp_path / ".carter"
        carter_dir.mkdir()
        (carter_dir / ".git").write_text("not a repo", encoding="utf-8")  # exists() True
        with pytest.raises(StateError):
            commit_state(carter_dir, "test: broken repo")

    def test_default_message_used_when_omitted(self, tmp_path):
        """commit_state succeeds with a generated message via `carter save` (no -m)."""
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        runner.invoke(main, ["init", str(tmp_path)])
        (tmp_path / ".carter" / "state" / "sessions" / "checkpoint.md").write_text(
            "---\nupdated: 2026-06-10\n---\n", encoding="utf-8"
        )
        result = runner.invoke(main, ["save", str(tmp_path)])  # no -m
        assert result.exit_code == 0, result.output
        assert "Saved" in result.output


class TestSaveCommand:
    def _runner(self):
        from click.testing import CliRunner

        from carter.cli import main

        return CliRunner(), main

    def test_save_commits_changes(self, tmp_path):
        runner, main = self._runner()
        runner.invoke(main, ["init", str(tmp_path)])
        cp = tmp_path / ".carter" / "state" / "sessions" / "checkpoint.md"
        cp.write_text("---\nupdated: 2026-06-09\n---\n", encoding="utf-8")
        result = runner.invoke(main, ["save", str(tmp_path), "-m", "test: cp"])
        assert result.exit_code == 0, result.output
        assert "Saved" in result.output

    def test_save_nothing_to_commit(self, tmp_path):
        runner, main = self._runner()
        runner.invoke(main, ["init", str(tmp_path)])
        result = runner.invoke(main, ["save", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Nothing to save" in result.output

    def test_save_not_a_workspace(self, tmp_path):
        runner, main = self._runner()
        result = runner.invoke(main, ["save", str(tmp_path)])
        assert result.exit_code != 0


class TestStateExtras:
    """Coverage for init idempotency, allow_empty, and end-to-end recovery."""

    def test_git_init_idempotent(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        head1 = _git(carter_dir, "rev-parse", "HEAD").stdout.strip()
        # Re-running init must not re-init or add a commit (early-return on .git)
        init_workspace(tmp_path, config, git_state=True)
        head2 = _git(carter_dir, "rev-parse", "HEAD").stdout.strip()
        assert head1 == head2

    def test_commit_state_allow_empty_makes_commit(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        before = len(_git(carter_dir, "log", "--oneline").stdout.strip().splitlines())
        assert commit_state(carter_dir, "test: empty snapshot", allow_empty=True) is True
        after = len(_git(carter_dir, "log", "--oneline").stdout.strip().splitlines())
        assert after == before + 1

    def test_recovery_end_to_end_via_save_cli(self, tmp_path):
        """Delete a plan, recover it from the snapshot `carter save` committed."""
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        runner.invoke(main, ["init", str(tmp_path)])
        carter_dir = tmp_path / ".carter"
        plan = carter_dir / "state" / "plans" / "active" / "001-x"
        plan.mkdir(parents=True)
        (plan / "README.md").write_text("---\nid: 001-x\n---\n", encoding="utf-8")

        result = runner.invoke(main, ["save", str(tmp_path), "-m", "test: snapshot plan"])
        assert result.exit_code == 0, result.output

        shutil.rmtree(plan)
        assert not plan.exists()
        _git(carter_dir, "checkout", "HEAD", "--", "state/plans/active/001-x/README.md")
        assert (plan / "README.md").exists()


class TestCommitAttribution:
    """Decision A/B: the user is the author; Carter is only a ``Co-authored-by:``."""

    @staticmethod
    def _isolate(monkeypatch, tmp_path: Path, *, identity: bool) -> Path:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        gitconfig = home / ".gitconfig"
        gitconfig.write_text(
            "[user]\n\tname = Jane Dev\n\temail = jane@example.com\n" if identity else ""
        )
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        for var in (
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
            "EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)
        return home

    def test_user_is_author_and_t0_credits_carter_without_an_email(
        self, tmp_path, config, monkeypatch
    ):
        self._isolate(monkeypatch, tmp_path, identity=True)
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "note.md").write_text("x\n")
        assert commit_state(carter_dir, "chore: snapshot") is True

        log = _git(carter_dir, "log", "-1", "--format=%an <%ae>%n%B")
        assert log.stdout.startswith("Jane Dev <jane@example.com>")
        assert "Assisted-by: Carter" in log.stdout  # T0: no identity configured
        assert "Co-authored-by" not in log.stdout

    def test_co_author_comes_from_carter_config(self, tmp_path, config, monkeypatch):
        home = self._isolate(monkeypatch, tmp_path, identity=True)
        (home / ".carter").mkdir()
        (home / ".carter" / "config.toml").write_text(
            'schema = 2\n[identity]\nlogin = "acme-bot"\nid = 99\n'
            'email = "99+acme-bot@users.noreply.github.com"\n'
        )
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        trailers = _git(carter_dir, "log", "-1", "--format=%(trailers:key=Co-authored-by)")
        assert "Co-authored-by: acme-bot <99+acme-bot@users.noreply.github.com>" in trailers.stdout

    def test_falls_back_to_a_neutral_author_without_git_identity(
        self, tmp_path, config, monkeypatch
    ):
        self._isolate(monkeypatch, tmp_path, identity=False)
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        log = _git(carter_dir, "log", "-1", "--format=%ae")
        assert log.stdout.strip() == "state@carter.invalid"


# ─── Commit shape: human/human, unsigned, immune to the environment (plan 002 step 11) ───

IDENT = "Jane Dev|Jane Dev|N"  # %an|%cn|%G?
LOG_SHAPE = "--format=%an|%cn|%G?"
LLM_EMAIL = "12345+llm-bot@users.noreply.github.com"


def _shape(carter_dir: Path) -> str:
    return _git(carter_dir, "log", "-1", LOG_SHAPE).stdout.strip()


def _human_git(monkeypatch, tmp_path: Path, extra: str = "") -> Path:
    """Hermetic HOME whose global git config is a real human identity (plus ``extra``)."""
    home = Path(os.environ["HOME"])
    gitconfig = home / "gitconfig"
    gitconfig.write_text(f"[user]\n\tname = Jane Dev\n\temail = jane@example.com\n{extra}")
    return home


def _write_carter_config(home: Path, text: str) -> None:
    (home / ".carter").mkdir(exist_ok=True)
    (home / ".carter" / "config.toml").write_text(text)


class TestCommitShapeUnderPollution:
    def test_polluted_env_cannot_change_author_committer_or_signing(
        self, tmp_path, config, monkeypatch, pollute_git_env
    ):
        _human_git(monkeypatch, tmp_path)
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "a.md").write_text("x\n")
        pollute_git_env()
        # Injected config: ask for SSH signing with a bogus key. Unscrubbed, git would try
        # to sign (and fail, or sign) instead of producing a plain commit.
        monkeypatch.setenv("GIT_CONFIG_COUNT", "3")
        for i, (k, v) in enumerate(
            [("commit.gpgsign", "true"), ("user.signingkey", "/nope.pub"), ("gpg.format", "ssh")]
        ):
            monkeypatch.setenv(f"GIT_CONFIG_KEY_{i}", k)
            monkeypatch.setenv(f"GIT_CONFIG_VALUE_{i}", v)
        monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'commit.gpgsign=true'")

        assert commit_state(carter_dir, "chore: polluted snapshot") is True

        assert _shape(carter_dir) == IDENT

    def test_init_commit_is_also_clean_under_pollution(
        self, tmp_path, config, monkeypatch, pollute_git_env
    ):
        _human_git(monkeypatch, tmp_path)
        pollute_git_env()
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        assert _shape(carter_dir) == IDENT

    def test_the_humans_signing_config_does_not_make_state_commits_sign(
        self, tmp_path, config, monkeypatch
    ):
        # commit.gpgsign=true in the human's own gitconfig: -c commit.gpgsign=false wins.
        _human_git(
            monkeypatch,
            tmp_path,
            "[commit]\n\tgpgsign = true\n[user]\n\tsigningkey = /does/not/exist.pub\n"
            "[gpg]\n\tformat = ssh\n",
        )
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "a.md").write_text("x\n")
        assert commit_state(carter_dir, "chore: snapshot") is True
        assert _shape(carter_dir) == IDENT

    def test_role_author_in_env_and_config_does_not_change_the_shape(
        self, tmp_path, config, monkeypatch
    ):
        home = _human_git(monkeypatch, tmp_path)
        _write_carter_config(home, 'schema = 2\n[identity]\nrole = "author"\n')
        monkeypatch.setenv("CARTER_IDENTITY_ROLE", "author")
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "a.md").write_text("x\n")

        assert commit_state(carter_dir, "chore: snapshot") is True

        assert _shape(carter_dir) == IDENT  # role is ignored for state commits

    def test_neutral_author_without_any_git_identity_is_unsigned_and_not_a_github_account(
        self, tmp_path, config, monkeypatch, pollute_git_env
    ):
        os.environ["GIT_CONFIG_GLOBAL"] = str(Path(os.environ["HOME"]) / "empty")
        Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text("")
        pollute_git_env()  # a polluter must not become the author either
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "a.md").write_text("x\n")
        assert commit_state(carter_dir, "chore: snapshot") is True
        out = _git(carter_dir, "log", "-1", "--format=%an|%ae|%cn|%ce|%G?").stdout.strip()
        assert out == "Carter|state@carter.invalid|Carter|state@carter.invalid|N"
        assert "noreply" not in out and "Polluter" not in out


class TestTierAwareTrailer:
    def _commit(self, tmp_path, config, monkeypatch, carter_toml: str | None) -> str:
        home = _human_git(monkeypatch, tmp_path)
        if carter_toml is not None:
            _write_carter_config(home, carter_toml)
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "a.md").write_text("x\n")
        assert commit_state(carter_dir, "chore: snapshot") is True
        return _git(carter_dir, "log", "-1", "--format=%B").stdout

    def test_t0_assisted_by_carter_without_email_or_model(self, tmp_path, config, monkeypatch):
        body = self._commit(tmp_path, config, monkeypatch, None)
        assert "Assisted-by: Carter\n" in body + "\n"
        assert "Assisted-by: Carter:" not in body and "<" not in body.split("Assisted-by")[1]
        assert "Co-authored-by" not in body

    def test_t1_co_authored_by_the_llm_account(self, tmp_path, config, monkeypatch):
        toml = f'schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\nemail = "{LLM_EMAIL}"\n'
        body = self._commit(tmp_path, config, monkeypatch, toml)
        assert f"Co-authored-by: llm-bot <{LLM_EMAIL}>" in body
        assert "Assisted-by" not in body

    def test_t2_still_uses_the_t1_style_trailer_and_does_not_sign(
        self, tmp_path, config, monkeypatch
    ):
        toml = (
            f'schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\nemail = "{LLM_EMAIL}"\n'
            '[identity.signing]\npublic_key = "ssh-ed25519 AAAA"\nfingerprint = "SHA256:abc"\n'
        )
        home = _human_git(monkeypatch, tmp_path)
        _write_carter_config(home, toml)
        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)
        (carter_dir / "knowledge" / "a.md").write_text("x\n")
        assert commit_state(carter_dir, "chore: snapshot") is True
        out = _git(carter_dir, "log", "-1", "--format=%an|%cn|%G?%n%B").stdout
        assert out.startswith(IDENT)
        assert f"Co-authored-by: llm-bot <{LLM_EMAIL}>" in out

    @pytest.mark.parametrize(
        "broken",
        [
            "schema = 2\n[identity\n",  # TOML error
            'schema = 2\n[identity]\nrole = "root"\n',  # invalid value
            'schema = 2\n[identity]\nlogin = "x"\nid = 1\n[identity.signing]\nfingerprint = "f"\n',
            "schema = 3\n",
        ],
        ids=["syntax", "enum", "incomplete-signing", "future-schema"],
    )
    def test_broken_config_gives_assisted_by_and_the_state_commit_still_succeeds(
        self, tmp_path, config, monkeypatch, broken
    ):
        body = self._commit(tmp_path, config, monkeypatch, broken)
        assert "Assisted-by: Carter" in body
        assert "Co-authored-by" not in body

    def test_role_refusal_also_falls_back_to_assisted_by(self, tmp_path, config, monkeypatch):
        body = self._commit(
            tmp_path, config, monkeypatch, 'schema = 2\n[identity]\nrole = "author"\n'
        )
        assert "Assisted-by: Carter" in body

    def test_no_carter_bot_identity_anywhere_in_the_commit(self, tmp_path, config, monkeypatch):
        body = self._commit(tmp_path, config, monkeypatch, None)
        assert "carter-bot" not in body


def _verb(cmd: list[str]) -> str:
    """The git subcommand of ``git [-c k=v]... <verb> ...``."""
    rest = cmd[1:]
    while rest[0] == "-c":
        rest = rest[2:]
    return rest[0]


class TestSingleChokePoint:
    def test_run_git_is_the_only_subprocess_entry_in_state(self):
        import carter.state as state

        tree = ast.parse(Path(state.__file__).read_text(encoding="utf-8"))
        callers = []
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "subprocess"
                    and node.attr in {"run", "Popen", "call", "check_call", "check_output"}
                ):
                    callers.append(fn.name)
        assert callers == ["_run_git"]

    def test_every_git_call_is_scrubbed_and_never_signs(
        self, tmp_path, config, monkeypatch, pollute_git_env
    ):
        import carter.state as state

        _human_git(monkeypatch, tmp_path)
        pollute_git_env()
        monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'x.y=z'")
        monkeypatch.setenv("GIT_CONFIG_KEY_5", "k")
        calls: list[tuple[list[str], dict[str, str]]] = []
        real = subprocess.run

        def spy(cmd, *a, **kw):
            calls.append((list(cmd), dict(kw.get("env") or os.environ)))
            return real(cmd, *a, **kw)

        monkeypatch.setattr(state.subprocess, "run", spy)

        carter_dir = init_workspace(tmp_path / "ws", config, git_state=True)  # init + commit
        (carter_dir / "knowledge" / "a.md").write_text("x\n")
        commit_state(carter_dir, "chore: snapshot")  # add, diff, config x2, commit

        assert {"init", "add", "diff", "config", "commit"} <= {_verb(c) for c, _ in calls}
        bad_prefix = ("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
        for cmd, env in calls:
            assert cmd[:3] == ["git", "-c", "commit.gpgsign=false"], cmd
            assert not [k for k in env if k.startswith(bad_prefix)], cmd
            for name in (
                "GIT_CONFIG_COUNT",
                "GIT_CONFIG_PARAMETERS",
                "CARTER_IDENTITY",
                "CARTER_IDENTITY_ROLE",
                "CARTER_IDENTITY_MODE",
                "EMAIL",
            ):
                assert name not in env, (name, cmd)

    def test_the_process_environment_is_left_alone(
        self, tmp_path, config, monkeypatch, pollute_git_env
    ):
        _human_git(monkeypatch, tmp_path)
        pollute_git_env()
        init_workspace(tmp_path / "ws", config, git_state=True)
        assert os.environ["GIT_AUTHOR_NAME"] == "Polluter"  # scrubbed per call, not globally
