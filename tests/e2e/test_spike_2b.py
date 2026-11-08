"""Spike C (plan 005, step 4): the real OpenCode, the signing env and the PTY/`!` environments.

Opt-in (``CARTER_E2E=1``). Throwaway ed25519 key, dedicated ``ssh-agent`` and shim under the
rig's own HOME; the agent is killed at teardown. The 2a plugin is the real one (with the fake
python interpreter of ``test_plugin_smoke``); ``probes/signing_probe.ts`` stands in for the 2b
signing block and is loaded after it. Observed on OpenCode 2.1.4 (see plan 005 notes, Spike C).
Step 25 extends these into the 2b contract suite.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from carter.identity import isolation
from e2e.harness import Rig
from e2e.test_plugin_smoke import FAKE_PYTHON, PLUGIN_SRC, iso_bytes, status

pytestmark = pytest.mark.e2e

SSH = Path("/usr/bin")
PROBE = (Path(__file__).parent / "probes" / "signing_probe.ts").read_text()
SIGNATURE_LOG = "%an|%ae|%cn|%ce|%G?|%GF"
CTX_SCRIPT = """#!/bin/sh
t() { if [ -t "$1" ]; then printf 1; else printf 0; fi; }
dt=0; (: </dev/tty) 2>/dev/null && dt=1
printf 'tty=%s%s%s devtty=%s term=%s oc_terminal=%s names=' \\
  "$(t 0)" "$(t 1)" "$(t 2)" "$dt" "$TERM" "$OPENCODE_TERMINAL"
env | cut -d= -f1 \\
  | grep -E '^(AGENT|AI_AGENT|OPENCODE.*|SSH_AUTH_SOCK|GITHUB_TOKEN|GH_TOKEN|CARTER.*)$' \\
  | sort | tr '\\n' ' '
echo
"""


@dataclass
class Signing:
    rig: Rig
    key: Path
    sock: Path
    shim: Path
    allowed: Path
    blob: str
    agent_pid: int

    def env(self) -> dict[str, str]:
        return {
            "HOME": str(self.rig.home / "tmp"),
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "SSH_AUTH_SOCK": str(self.sock),
        }

    def add_key(self) -> None:
        done = subprocess.run(
            [str(SSH / "ssh-add"), str(self.key)],
            env={**self.env(), "SSH_ASKPASS_REQUIRE": "never"},
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert done.returncode == 0, done.stderr

    def remove_keys(self) -> None:
        subprocess.run(
            [str(SSH / "ssh-add"), "-D"],
            env=self.env(),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            check=True,
        )

    def write_probe(self, *, sign: bool = True, version: str = "v1") -> None:
        pairs = [
            ("commit.gpgsign", "true"),
            ("gpg.format", "ssh"),
            ("user.signingkey", f"key::{self.blob}"),
            ("gpg.ssh.program", str(self.shim)),
            ("gpg.ssh.allowedSignersFile", str(self.allowed)),
        ]
        (self.rig.logs / "probe.json").write_text(
            json.dumps(
                {
                    "sign": sign,
                    "pairs": pairs,
                    "name": "LLM Agent",
                    "email": "llm@example.invalid",
                    "version": version,
                }
            )
        )


def _make_rig(rig_factory, opencode_bin) -> Rig:  # type: ignore[no-untyped-def]
    def index_ts(home: Path) -> str:
        sha = isolation.sha256_hex(iso_bytes(home))
        text = (PLUGIN_SRC / "index.ts").read_text()
        return text.replace("__CARTER_ISOLATION_SHA256__", sha).replace(
            "__CARTER_VERSION__", "0.0-e2e"
        )

    return rig_factory(
        opencode=opencode_bin,
        carter_agent=True,
        plugins={"zprobe": PROBE},
        extra_files={
            ".config/opencode/plugins/carter/index.ts": index_ts,
            ".config/opencode/plugins/carter/core.ts": (PLUGIN_SRC / "core.ts").read_text(),
            ".config/opencode/plugins/carter/broker.ts": (PLUGIN_SRC / "broker.ts").read_text(),
            ".carter/isolation.json": lambda home: iso_bytes(home).decode(),
            "fakepy": lambda home: FAKE_PYTHON % {"home": home},
        },
        executable=["fakepy"],
        server_env_extra={"SSH_AUTH_SOCK": "/tmp/fake-agent.sock", "GITHUB_TOKEN": "not-a-token"},
    )


@pytest.fixture
def signing(rig_factory, opencode_bin) -> Iterator[Signing]:  # type: ignore[no-untyped-def]
    rig = _make_rig(rig_factory, opencode_bin)
    carter = rig.home / ".carter"
    (carter / "run").mkdir(parents=True, mode=0o700, exist_ok=True)
    (carter / "bin").mkdir(exist_ok=True)
    key = carter / "llm_key"
    done = subprocess.run(
        [str(SSH / "ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-C", "e2e", "-f", str(key)],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    assert done.returncode == 0, done.stderr
    kind, data = Path(f"{key}.pub").read_text().split()[:2]
    sock = carter / "run" / "agent.sock"
    assert len(str(sock)) < 104
    started = subprocess.run(
        [str(SSH / "ssh-agent"), "-a", str(sock), "-s"],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        check=True,
    )
    pid = int(started.stdout.split("SSH_AGENT_PID=")[1].split(";")[0])
    shim = carter / "bin" / "sign-shim"
    shim.write_text(
        "#!/bin/sh\n"
        f"exec env SSH_AUTH_SOCK='{sock}' SSH_ASKPASS=/usr/bin/false SSH_ASKPASS_REQUIRE=force "
        f"'{SSH / 'ssh-keygen'}' \"$@\"\n"
    )
    shim.chmod(0o755)
    allowed = carter / "allowed_signers"
    allowed.write_text(f'llm@example.invalid namespaces="git" {kind} {data}\n')
    state = Signing(rig, key, sock, shim, allowed, f"{kind} {data}", pid)
    state.add_key()
    state.write_probe()
    hooks = carter / "hooks"
    hooks.mkdir()
    (hooks / "commit-msg.sh").write_text(
        '#!/bin/sh\ngrep -q REJECTME "$1" && { echo "carter-guard: commit rejected: test" >&2;'
        " exit 1; }\nexit 0\n"
    )
    (hooks / "post-commit.sh").write_text(
        '#!/bin/sh\n[ -f "$(git rev-parse --git-dir)/WARNME" ] && '
        '{ echo "carter-guard: warning: test warning" >&2; exit 3; }\nexit 0\n'
    )
    for script in hooks.iterdir():
        script.chmod(0o755)
    with (rig.home / ".gitconfig").open("a") as handle:
        handle.write(
            f'[hook "t-cm"]\n\tevent = commit-msg\n\tcommand = "{hooks / "commit-msg.sh"}"\n'
            f'[hook "t-pc"]\n\tevent = post-commit\n\tcommand = "{hooks / "post-commit.sh"}"\n'
        )
    (rig.ws / "ctx.sh").write_text(CTX_SCRIPT)
    yield state
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def shell(rig: Rig, command: str) -> str:
    sid = rig.new_session()
    seen = len(rig.results())
    rig.prompt(sid, f"RUN {command}")
    return str(rig.wait_results(seen + 1)[-1]["result"])


def bang(rig: Rig, command: str) -> str:
    sid = rig.new_session()
    rig.bang(sid, command)
    deadline = time.time() + 15
    while time.time() < deadline:
        rows = [
            m for m in rig.api("GET", f"/api/session/{sid}/context")["data"] if m["type"] == "shell"
        ]
        if rows and rows[0].get("status") == "exited":
            return str(rows[0]["output"]["output"])
        time.sleep(0.2)
    raise AssertionError("no output from the ! shell")


def pty(rig: Rig, command: str) -> str:
    out = rig.logs / f"pty-{time.time_ns()}.txt"
    rig.api(
        "POST", "/api/pty", {"command": "/bin/sh", "args": ["-c", f"{command} > {out}; sleep 1"]}
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if out.exists() and out.read_text().strip():
            return out.read_text()
        time.sleep(0.2)
    raise AssertionError("the PTY wrote nothing")


def committed(rig: Rig, text: str) -> str:
    script = rig.ws / f"c{time.time_ns()}.sh"
    script.write_text(
        "#!/bin/sh\ncd " + str(rig.ws) + "\necho x >> f.txt\ngit add f.txt\n"
        f"git commit -q -m '{text}'\necho rc=$?\n"
    )
    return shell(rig, f"sh {script}")


def verify(signing: Signing, ref: str = "HEAD") -> str:
    env = {
        **signing.env(),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_0": "gpg.format",
        "GIT_CONFIG_VALUE_0": "ssh",
        "GIT_CONFIG_KEY_1": "gpg.ssh.program",
        "GIT_CONFIG_VALUE_1": str(signing.shim),
        "GIT_CONFIG_KEY_2": "gpg.ssh.allowedSignersFile",
        "GIT_CONFIG_VALUE_2": str(signing.allowed),
    }
    return subprocess.run(
        ["git", "log", "-1", f"--format={SIGNATURE_LOG}", ref],
        cwd=signing.rig.ws,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    ).stdout.strip()


# --- 1. the signing env through create.before --------------------------------------------------


def test_the_appended_signing_entries_win_and_the_commit_is_k1(signing: Signing) -> None:
    rig = signing.rig
    out = committed(rig, "first signed commit")
    assert "rc=0" in out, out
    fp = subprocess.run(
        [str(SSH / "ssh-keygen"), "-lf", f"{signing.key}.pub"], capture_output=True, text=True
    ).stdout.split()[1]
    # author = the human of ~/.gitconfig, committer = the LLM, signed by the LLM key
    assert (
        verify(signing)
        == f"E2E Human|e2e-human@example.invalid|LLM Agent|llm@example.invalid|G|{fp}"
    )
    probe = [json.loads(x) for x in (rig.logs / "probe.log").read_text().splitlines()]
    creates = [e for e in probe if e["ev"] == "create"]
    assert creates[-1]["agent"] is True and creates[-1]["count_before"] == 13  # the 2a block


def test_with_the_block_off_the_agent_commit_stays_unsigned(signing: Signing) -> None:
    signing.write_probe(sign=False)
    out = committed(signing.rig, "unsigned")
    # 2a isolation: commit.gpgsign=false and gpg.*.program=false are the effective values
    assert "rc=0" in out, out
    assert verify(signing).split("|")[4:] == ["N", ""]


# --- 2. what the model sees --------------------------------------------------------------------


def test_model_visible_texts_for_signing_and_hook_failures(signing: Signing) -> None:
    rig = signing.rig
    seen: dict[str, str] = {}
    signing.remove_keys()
    seen["locked"] = committed(rig, "locked")
    signing.add_key()
    seen["rejected"] = committed(rig, "REJECTME please")
    (rig.ws / ".git" / "WARNME").write_text("")
    seen["warned"] = committed(rig, "warn me")
    os.kill(signing.agent_pid, signal.SIGKILL)
    time.sleep(0.2)
    seen["stale"] = committed(rig, "stale agent")
    assert "Couldn't find key in agent?" in seen["locked"]
    assert "failed to write commit object" in seen["locked"]
    assert "carter-guard: commit rejected: test" in seen["rejected"]
    assert "carter-guard: warning: test warning" in seen["warned"]
    assert "Couldn't get agent socket?" in seen["stale"]


# --- 3/4. PTY and `!` environments, agent signals -----------------------------------------------


def test_environments_of_agent_subagent_bang_and_pty_shells(signing: Signing) -> None:
    rig = signing.rig
    seen = {"agent": shell(rig, f"sh {rig.ws / 'ctx.sh'}").strip()}
    sid = rig.new_session()
    rig.prompt(sid, f"TASK RUN sh {rig.ws / 'ctx.sh'}")
    seen["subagent"] = str(rig.wait_results(2)[0]["result"]).strip()
    seen["bang"] = bang(rig, f"sh {rig.ws / 'ctx.sh'}").strip()
    seen["pty"] = pty(rig, f"sh {rig.ws / 'ctx.sh'}").strip()
    print(json.dumps(seen, indent=1))
    names = {k: v.split("names=")[1].split() for k, v in seen.items()}
    flags = {k: v.split(" names=")[0] for k, v in seen.items()}
    agent_signals = {"AGENT", "AI_AGENT", "OPENCODE_SESSION_ID", "CARTER_AGENT_SHELL"}
    for kind in ("agent", "subagent"):  # AD1 inputs and the marker; no terminal at all
        assert agent_signals <= set(names[kind])
        assert flags[kind].startswith("tty=000 devtty=0")
    assert flags["bang"].startswith("tty=000 devtty=0")  # `!` has no terminal either
    assert not {"AGENT", "OPENCODE_SESSION_ID", "CARTER_AGENT_SHELL"} & set(names["bang"])
    assert "CARTER_HUMAN_SHELL" in names["bang"] or "SSH_AUTH_SOCK" in names["bang"]
    assert flags["pty"].startswith("tty=1") and "devtty=1" in flags["pty"]  # the only real TTY
    assert not agent_signals & set(names["pty"])
    # OPENCODE_TERMINAL is "1" in every OpenCode-spawned shell (agent, `!`, PTY): the unlock
    # refusal rule keys on it plus the missing TTY, it cannot tell the PTY from `!` by itself
    for kind in seen:
        assert "OPENCODE_TERMINAL" in names[kind], kind


# --- 5. timing ---------------------------------------------------------------------------------


def test_signed_commit_latency_in_an_agent_shell(signing: Signing) -> None:
    rig = signing.rig
    script = rig.ws / "timing.sh"
    script.write_text(
        f"#!/bin/sh\ncd {rig.ws}\nfor i in 1 2 3 4 5 6 7 8; do\n"
        "  echo $i >> t.txt; git add t.txt\n"
        '  s=$(date +%s%N); git commit -q -m "t$i"; e=$(date +%s%N)\n'
        "  echo $(( (e - s) / 1000000 ))\ndone\n"
    )
    ms = sorted(int(x) for x in shell(rig, f"sh {script}").split())
    print("signed commit ms:", ms)
    assert len(ms) == 8 and ms[-1] < 1500


# --- 6. hot reload ---------------------------------------------------------------------------


def test_replacing_the_plugin_files_while_the_server_runs(signing: Signing) -> None:
    rig = signing.rig
    committed(rig, "before reload")
    (before,) = status(rig)
    plug = rig.home / ".config/opencode/plugins"
    probe_ts = plug / "zprobe" / "index.ts"
    probe_ts.write_text(probe_ts.read_text() + "\n// v2\n")
    index_ts = plug / "carter" / "index.ts"
    index_ts.write_text(index_ts.read_text().replace("0.0-e2e", "0.0-e2e-v2"))
    deadline = time.time() + 15
    rows: list[dict] = []
    while time.time() < deadline:
        rows = status(rig)
        if rows and rows[0].get("plugin_version") == "0.0-e2e-v2":
            break
        time.sleep(0.3)
    log = rig.home / "fakepy.log"
    calls_before = log.read_text().count("gate args=")
    out = committed(rig, "after reload")
    calls_after = log.read_text().count("gate args=")
    probe = [json.loads(x) for x in (rig.logs / "probe.log").read_text().splitlines()]
    assert "rc=0" in out
    assert len(rows) == 1 and rows[0]["pid"] == before["pid"]  # one status file per pid
    assert rows[0]["instance"] != before["instance"]  # a new instance ...
    assert rows[0]["state"] == "unproven"  # ... that starts again unproven
    assert calls_after - calls_before == 1  # one gate call: no duplicate hooks
    assert [e["ev"] for e in probe if e["ev"] != "create"] == ["setup", "cleanup", "setup"]
    assert verify(signing).split("|")[2:4] == ["LLM Agent", "llm@example.invalid"]  # still signing
