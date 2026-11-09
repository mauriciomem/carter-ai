"""``check --host`` for a key without a passphrase (): no agent to probe, no unlock."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from carter import hostcheck_id
from carter.identity import shim
from carter.identity.schema import Identity, IdentityConfig, Signing

BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"


def cfg(**signing: str) -> IdentityConfig:
    return IdentityConfig(
        identity=Identity(login="bot", id=1, email="1+bot@users.noreply.github.com"),
        signing=Signing(
            public_key=BLOB,
            fingerprint="SHA256:abc",
            private_key_path="/home/u/.ssh/llm",
            **signing,
        ),
        state="current",
    )


@pytest.fixture
def quiet_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(hostcheck_id, "shim_state", lambda _home: SimpleNamespace(ok=True))
    monkeypatch.setattr(hostcheck_id, "shim_socket", lambda _home: None)
    allowed = shim.allowed_signers_path(tmp_path)
    allowed.parent.mkdir(parents=True)
    allowed.write_text("x\n")
    return tmp_path


def test_a_file_mode_key_is_ok_and_the_agent_is_never_probed(
    monkeypatch: pytest.MonkeyPatch, quiet_host: Path
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the agent was probed")

    monkeypatch.setattr(hostcheck_id, "probe_setup", boom)
    items = hostcheck_id.key_items(cfg(mode="file"), quiet_host)
    agent = [i for i in items if i.area == "agent"]
    assert [i.level for i in agent] == ["ok"] and "key file" in agent[0].text
    assert not [i for i in items if i.level in ("warn", "red")]
    assert "unlock" not in " ".join(i.text + i.fix for i in items)


def test_an_agent_mode_key_is_still_probed(
    monkeypatch: pytest.MonkeyPatch, quiet_host: Path
) -> None:
    seen: list[str] = []

    def fake_probe(setup: object, config: object) -> SimpleNamespace:
        seen.append("probed")
        return SimpleNamespace(state="none")

    monkeypatch.setattr(hostcheck_id, "probe_setup", fake_probe)
    items = hostcheck_id.key_items(cfg(), quiet_host)
    assert seen == ["probed"]
    assert any("unlock" in i.text or "unlock" in i.fix for i in items)
