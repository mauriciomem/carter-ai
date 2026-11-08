"""M2 rehearsal in a real OpenCode (plan 005 steps 8-12, before the step-25 contract suite).

The real pieces, end to end: the 2b plugin core in Bun, the **real** ``identity env`` entry (the
interpreter in ``isolation.json`` is a wrapper that runs the repo's Python for the entry and allows
every command for the gate), the generated shim, the dedicated agent started and stopped by
``carter.identity.agent``, a throwaway key, and git. Opt-in (``CARTER_E2E=1``); nothing touches the
real ``~/.config/opencode``, ``~/.carter`` or the user's agent.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from carter.identity import agent, agent_paths, isolation, shim
from carter.identity.payload import fingerprint_of
from e2e.harness import Rig
from e2e.test_plugin_smoke import PLUGIN_SRC, iso_bytes, status

pytestmark = pytest.mark.e2e

SSH = Path("/usr/bin")
LOGIN, UID = "llm-bot", 4242
WRAPPER = """#!/bin/sh
case "$*" in
  *carter.identity.env*) exec %(python)s "$@" ;;
esac
cat > /dev/null
echo '{"decision":"allow","rule":null,"message":null}'
"""


@dataclass
class Full:
    rig: Rig
    key: Path
    blob: str
    setup: agent.Setup

    def shell(self, command: str) -> str:
        sid = self.rig.new_session()
        seen = len(self.rig.results())
        self.rig.prompt(sid, f"RUN {command}")
        return str(self.rig.wait_results(seen + 1)[-1]["result"])

    def commit(self, message: str) -> str:
        script = self.rig.ws / f"c{len(list(self.rig.ws.glob('c*.sh')))}.sh"
        script.write_text(
            f"#!/bin/sh\ncd {self.rig.ws}\necho {message!r} >> f.txt\ngit add f.txt\n"
            f"git commit -q -m {message!r}\necho rc=$?\n"
        )
        return self.shell(f"sh {script}")

    def head(self) -> str:
        allowed = self.rig.home / ".carter" / "hooks" / "allowed_signers"
        env = {
            "HOME": str(self.rig.home),
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "gpg.ssh.allowedSignersFile",
            "GIT_CONFIG_VALUE_0": str(allowed),
            "GIT_CONFIG_KEY_1": "gpg.ssh.program",
            "GIT_CONFIG_VALUE_1": str(self.rig.home / ".carter" / "bin" / "carter-ssh-sign"),
        }
        return subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>|%cn <%ce>|%G?|%GF"],
            cwd=self.rig.ws,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def unlock(self) -> None:
        got = agent.unlock(
            self.setup, lambda argv, env: subprocess.run(argv, env=env, check=False).returncode
        )
        assert got.status in ("unlocked", "already-unlocked"), got


@pytest.fixture
def full(rig_factory, opencode_bin) -> Iterator[Full]:  # type: ignore[no-untyped-def]
    keydir = Path(
        tempfile.mkdtemp(
            prefix="k", dir="/tmp/opencode/2b" if Path("/tmp/opencode/2b").exists() else None
        )
    )
    key = keydir / "id"
    done = subprocess.run(
        [str(SSH / "ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-C", "e2e", "-f", str(key)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    assert done.returncode == 0, done.stderr
    kind, data = Path(f"{key}.pub").read_text().split()[:2]
    blob = f"{kind} {data}"
    fingerprint = fingerprint_of(blob)

    def config(home: Path) -> str:
        return (
            "schema = 2\n[identity]\n"
            f'login = "{LOGIN}"\nid = {UID}\nname = "LLM Bot"\n'
            f'email = "{UID}+{LOGIN}@users.noreply.github.com"\n'
            f'[identity.signing]\npublic_key = "{blob} e2e"\nfingerprint = "{fingerprint}"\n'
            f'private_key_path = "{key}"\n'
        )

    def shim_bytes(home: Path) -> bytes:
        return shim.render(
            shim.ShimParams(
                key=blob,
                sock=str(agent_paths.socket_path(home, {})),
                false_path=isolation.resolve_false(),
                keygen=str(SSH / "ssh-keygen"),
                run_dir=str(home / ".carter" / "run"),
            )
        )

    def guard_state(home: Path) -> str:
        path = home / ".carter" / "bin" / "carter-ssh-sign"
        digest = hashlib.sha256(shim_bytes(home)).hexdigest()
        return json.dumps({"files": [{"path": str(path), "sha256": f"sha256:{digest}"}]})

    def index_ts(home: Path) -> str:
        sha = isolation.sha256_hex(iso_bytes(home))
        text = (PLUGIN_SRC / "index.ts").read_text()
        return text.replace("__CARTER_ISOLATION_SHA256__", sha).replace(
            "__CARTER_VERSION__", "0.0-e2e"
        )

    rig = rig_factory(
        opencode=opencode_bin,
        carter_agent=True,
        extra_files={
            ".config/opencode/plugins/carter/index.ts": index_ts,
            ".config/opencode/plugins/carter/core.ts": (PLUGIN_SRC / "core.ts").read_text(),
            ".config/opencode/plugins/carter/broker.ts": (PLUGIN_SRC / "broker.ts").read_text(),
            ".carter/isolation.json": lambda home: iso_bytes(home).decode(),
            ".carter/config.toml": config,
            ".carter/guard-state.json": guard_state,
            ".carter/hooks/allowed_signers": lambda home: f'{LOGIN}@e2e namespaces="git" {blob}\n',
            "fakepy": lambda home: WRAPPER % {"python": sys.executable},
        },
        executable=["fakepy"],
        server_env_extra={"SSH_AUTH_SOCK": "/tmp/fake-agent.sock"},
    )
    home = rig.home
    (home / ".carter" / "run").mkdir(parents=True, exist_ok=True, mode=0o700)
    shim.write(home / ".carter" / "bin" / "carter-ssh-sign", shim_bytes(home))
    (home / ".carter" / "hooks" / "allowed_signers").write_text(
        f'{UID}+{LOGIN}@users.noreply.github.com namespaces="git" {blob}\n'
    )
    setup = agent.Setup(
        home=home, ssh_bin_dir=str(SSH), ttl="1h", blob=blob, fingerprint=fingerprint,
        private_key=str(key), managed_externally=False, sock=agent_paths.socket_path(home, {}),
    )  # fmt: skip
    state = Full(rig, key, blob, setup)
    yield state
    agent.lock(setup, stop_all=True)
    for leftover in keydir.iterdir():
        leftover.unlink()
    keydir.rmdir()


def test_a_real_agent_commit_is_k1_and_every_failure_stays_closed(full: Full) -> None:
    rig = full.rig
    full.unlock()
    out = full.commit("signed by the llm")
    assert "rc=0" in out, out
    who = f"E2E Human <e2e-human@example.invalid>|LLM Bot <{UID}+{LOGIN}@users.noreply.github.com>"
    assert full.head() == f"{who}|G|{fingerprint_of(full.blob)}"
    assert not {"sign-unavailable", "config-error"} & set(status(rig)[0]["flags"])

    # the key is locked: the raw git error, nothing committed, changes still staged
    agent.lock(full.setup)
    locked = full.commit("while locked")
    # `lock` stopped the now-empty agent, so it is the "no agent" string (E-SIGN-NOAGENT; the
    # message is the same as for a locked key)
    assert "rc=128" in locked and "Couldn't get agent socket?" in locked, locked
    full.unlock()

    # a missing shim: `identity env` says shim-missing, the plugin blocks (not degrades)
    shim_file = rig.home / ".carter" / "bin" / "carter-ssh-sign"
    kept = shim_file.read_bytes()
    shim_file.unlink()
    (rig.home / ".carter" / "config.toml").touch()  # a new mtime: the plugin asks again
    blocked = full.commit("shim gone")
    assert "rc=128" in blocked, blocked
    assert "sign-unavailable" in status(rig)[0]["flags"]
    shim.write(shim_file, kept)
    (rig.home / ".carter" / "config.toml").touch()
    assert "rc=0" in full.commit("shim back")
    assert full.head().split("|")[2] == "G"


def test_a_workspace_cap_gives_an_unsigned_human_commit_and_no_block(full: Full) -> None:
    rig = full.rig
    full.unlock()
    config = rig.home / ".carter" / "config.toml"
    config.write_text(config.read_text() + f'[workspaces."{rig.ws}"]\nmax_tier = "t1"\n')
    out = full.commit("capped")
    assert "rc=0" in out, out
    shown = full.head().split("|")
    assert shown[2] == "N" and "LLM Bot" not in shown[1]  # unsigned, committer is the human
    assert "sign-unavailable" not in status(rig)[0]["flags"]
