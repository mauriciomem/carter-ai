"""Shared test fixtures for Carter installer tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Path to the Carter repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Temporary base directory for testing (overrides ~/.copilot etc.)."""
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
    ) -> Path:
        """``agents_output``/``agents_exit`` drive ``opencode debug agents``."""
        bindir = tmp_path / "fakebin"
        bindir.mkdir(exist_ok=True)
        script = bindir / "opencode"
        if version_output is None:
            script.unlink(missing_ok=True)
        else:
            agents_file = bindir / "agents.out"
            agents_file.write_text(agents_output)
            script.write_text(
                "#!/bin/sh\n"
                f'if [ "$1" = debug ]; then /bin/cat "{agents_file}"; exit {agents_exit}; fi\n'
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
