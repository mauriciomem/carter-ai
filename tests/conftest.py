"""Shared test fixtures for Carter installer tests."""

from __future__ import annotations

import os
import pwd
from collections.abc import Callable
from pathlib import Path

import pytest

# Resolved once at import, before any fixture can redirect HOME. The hermetic fixture
# compares against it, so it must not be recomputed lazily.
_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()

# Ambient variables that change who git (or Carter) thinks the author is.
_IDENTITY_ENV_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "EMAIL",
    "CARTER_IDENTITY",
    "CARTER_IDENTITY_ROLE",
    "CARTER_IDENTITY_MODE",
)


def _is_under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root)


@pytest.fixture(scope="session")
def real_home() -> Path:
    """The developer's real home directory (never write here)."""
    return _REAL_HOME


@pytest.fixture(autouse=True)
def _hermetic_env(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate every test from the developer's home, git config and identity env.

    Redirects ``HOME`` (what ``Path.home()``, hence ``~/.carter`` and
    ``~/.config/opencode``, resolve from), ``XDG_CONFIG_HOME`` and git's global/system
    config, and clears variables that override the git identity. The fixture home is
    separate from ``tmp_path`` so tests that list ``tmp_path`` do not see it.

    It asserts the isolation before the test body runs (and so before any git writer
    can), and fails the test if any location still points at the real home.
    """
    home = tmp_path_factory.mktemp("home").resolve()
    xdg = home / ".config"
    xdg.mkdir()
    gitconfig = home / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Fixture Human\n\temail = fixture-human@example.invalid\n"
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # GIT_CONFIG_KEY_<n> / GIT_CONFIG_VALUE_<n> inject config pairs; clear every index.
    injected = [v for v in os.environ if v.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))]
    for var in (*_IDENTITY_ENV_VARS, *injected):
        monkeypatch.delenv(var, raising=False)

    # Fail closed: a regression here would let a test write the real ~/.gitconfig.
    assert Path.home().resolve() == home, "Path.home() ignores HOME; tests are not hermetic"
    assert home != _REAL_HOME, "fixture home is the real home"
    assert _is_under(Path(os.environ["GIT_CONFIG_GLOBAL"]), home)
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    return home


@pytest.fixture
def pollute_git_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Return a function that sets every env var able to hijack the commit identity.

    Used to prove ``state.py`` commits stay human/human and unsigned (plan 002, step 11).
    The function takes an optional ``monkeypatch`` (defaults to the test's own) so it can
    also be driven from another fixture; the changes are undone with that monkeypatch.
    """

    def pollute(mp: pytest.MonkeyPatch | None = None) -> None:
        mp = mp or monkeypatch
        mp.setenv("GIT_AUTHOR_NAME", "Polluter")
        mp.setenv("GIT_AUTHOR_EMAIL", "polluter-author@example.invalid")
        mp.setenv("GIT_COMMITTER_NAME", "Polluter")
        mp.setenv("GIT_COMMITTER_EMAIL", "polluter-committer@example.invalid")
        mp.setenv("GIT_CONFIG_COUNT", "1")
        mp.setenv("GIT_CONFIG_KEY_0", "user.name")
        mp.setenv("GIT_CONFIG_VALUE_0", "Polluter Config")
        mp.setenv("CARTER_IDENTITY", "polluter")
        mp.setenv("CARTER_IDENTITY_ROLE", "author")
        mp.setenv("CARTER_IDENTITY_MODE", "review")

    return pollute


@pytest.fixture
def repo_root() -> Path:
    """Path to the Carter repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Temporary base directory for testing (overrides ~/.config, ~/.carter etc.)."""
    return tmp_path


@pytest.fixture
def fake_opencode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put a fake ``opencode`` on an isolated PATH.

    Call it with the ``--version`` output to emit, or ``None`` for "not installed".
    PATH holds only the fake bin dir, so a real ``opencode`` can never leak in.
    """

    def make(
        version_output: str | None = "opencode v2.1.4",
        agents_output: str = "[]",
        agents_exit: int = 0,
        agents_sequence: list[str] | None = None,
    ) -> Path:
        """``agents_output``/``agents_exit`` drive ``opencode debug agents``.

        ``agents_sequence`` serves one output per call (repeating the last), to
        mimic OpenCode's service returning stale data before fresh data.
        """
        bindir = tmp_path / "fakebin"
        bindir.mkdir(exist_ok=True)
        script = bindir / "opencode"
        if version_output is None:
            script.unlink(missing_ok=True)
        else:
            outputs = agents_sequence or [agents_output]
            for i, out in enumerate(outputs, 1):
                (bindir / f"agents.{i}.out").write_text(out)
            counter = bindir / "agents.calls"
            counter.write_text("0")
            script.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = debug ]; then\n'
                f'  n=$(( $(/bin/cat "{counter}") + 1 )); echo "$n" > "{counter}"\n'
                f'  [ "$n" -gt {len(outputs)} ] && n={len(outputs)}\n'
                f'  /bin/cat "{bindir}/agents.$n.out"; exit {agents_exit}\n'
                "fi\n"
                f"printf '%s\\n' '{version_output}'\n"
            )
            script.chmod(0o755)
        monkeypatch.setenv("PATH", str(bindir))
        return bindir

    return make


@pytest.fixture(autouse=True)
def _no_real_opencode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``carter check`` from running a developer's real ``opencode``.

    Tests that want the harness step opt in via the ``fake_opencode`` fixture.
    """
    if "fake_opencode" in request.fixturenames:
        return
    import carter.harness

    monkeypatch.setattr(carter.harness, "_which", lambda _cmd: None)
