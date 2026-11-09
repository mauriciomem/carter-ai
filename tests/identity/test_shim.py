"""The signing shim.

Three layers: the generator (quoting, determinism, atomic mode-0755 write), the script's contract
against a *fake* ``ssh-keygen`` that records what it receives (under ``dash`` and
``bash --posix``), and a round trip with the real tools through git. macOS ``/bin/sh`` runs in CI.
"""

# ruff: noqa: E501  (dense parametrized tables)
from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from carter.identity import shim
from carter.identity.errors import E_GIT_OLD, E_SHIM_REFUSED, E_SSH_OLD, IdentityError, registry
from carter.identity.payload import ShimState, build_payload, shim_state, to_git_env
from carter.identity.resolve import resolve
from carter.identity.rules import load_rules
from carter.identity.schema import Identity, IdentityConfig, Signing
from ssh_rig import PASSPHRASE_PROMPT, KeyPair, Rig, pty_run, real_ssh

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
OTHER = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFDQnea8LgFZ8D5U5LltihuJT5SwVYKxvc17OZNaCgaU"
SHELLS = [
    pytest.param(
        [shutil.which("dash") or "dash"],
        id="dash",
        marks=pytest.mark.skipif(not shutil.which("dash"), reason="dash is not installed"),
    ),
    pytest.param(
        [shutil.which("bash") or "bash", "--posix"],
        id="bash-posix",
        marks=pytest.mark.skipif(not shutil.which("bash"), reason="bash is not installed"),
    ),
]

FAKE = """#!/bin/sh
PATH=/usr/bin:/bin  # the shim hides PATH from nobody: the fake just needs cat and sleep
{
  printf 'ARGC=%s\\n' "$#"
  for a in "$@"; do printf 'ARG=%s\\n' "$a"; done
  printf 'SOCK=%s\\nASKPASS=%s\\nREQUIRE=%s\\n' "${SSH_AUTH_SOCK-<unset>}" "${SSH_ASKPASS-<unset>}" \\
    "${SSH_ASKPASS_REQUIRE-<unset>}"
  prev=; for a in "$@"; do
    if [ "$prev" = -f ]; then printf 'FILEPATH=%s\\nFILE=%s\\n' "$a" "$(cat "$a")"; fi
    prev=$a
  done
  printf 'STDIN=%s\\n' "$(cat)"
} >> "$FAKE_LOG"
if [ -n "${FAKE_SLEEP-}" ]; then sleep "$FAKE_SLEEP"; fi
exit "${FAKE_RC-0}"
"""


class Lab:
    """A shim generated into a temp home, with fake signer and keygen recording their calls."""

    def __init__(
        self, root: Path, *, sock: str = "", program: bool = False, file_key: str = ""
    ) -> None:
        self.root = root
        self.run_dir = root / "run dir with 'quote'"
        self.run_dir.mkdir(parents=True, mode=0o700)
        self.log = root / "fake.log"
        self.keygen = self._fake(root / "keygen dir" / "ssh-keygen")
        self.program = self._fake(root / "prog dir" / "sign-program") if program else None
        self.sock = sock or str(root / "agent dir" / "it's.sock")
        self.params = shim.ShimParams(
            key=KEY,
            sock="" if program else self.sock,
            false_path="/usr/bin/false",
            keygen=str(self.keygen),
            run_dir=str(self.run_dir),
            signer=str(self.program or ""),
            file_key=file_key,
        )
        self.path = root / "bin dir" / "carter-ssh-sign"
        shim.write(self.path, shim.render(self.params))

    def _fake(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FAKE)
        path.chmod(0o755)
        return path

    def call(
        self,
        shell: list[str],
        *args: str,
        stdin: str = "",
        env: dict[str, str] | None = None,
        rc: int = 0,
        sleep: str = "",
    ) -> subprocess.CompletedProcess[str]:
        full = {"PATH": "/nonexistent", "FAKE_LOG": str(self.log), "FAKE_RC": str(rc)}
        if sleep:
            full["FAKE_SLEEP"] = sleep
        full.update(env or {})
        return subprocess.run(
            [*shell, str(self.path), *args],
            input=stdin,
            env=full,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def recorded(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def key_file(self, text: str = KEY + "\n") -> Path:
        path = self.root / "git tmp" / ".git_signing_key_tmpAbC123"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
        return path

    def sign_argv(self, key_file: Path | str, buffer: str = "buf") -> list[str]:
        return ["-Y", "sign", "-n", "git", "-f", str(key_file), "-U", str(self.root / buffer)]


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)


class TestGenerator:
    def test_the_script_is_posix_sh_with_the_banner_and_no_template_marks(self, lab: Lab) -> None:
        text = lab.path.read_text()
        assert text.startswith("#!/bin/sh\n# Managed by Carter")
        assert "@@" not in text and "bash" not in text.lower().split("posix sh only")[0]

    def test_bytes_are_deterministic_and_the_file_is_mode_0755(self, lab: Lab) -> None:
        assert shim.render(lab.params) == shim.render(lab.params) == lab.path.read_bytes()
        assert stat.S_IMODE(lab.path.stat().st_mode) == 0o755

    def test_a_second_write_of_the_same_bytes_changes_nothing(self, lab: Lab) -> None:
        before = lab.path.stat().st_ino
        assert shim.write(lab.path, shim.render(lab.params)) is False
        assert lab.path.stat().st_ino == before

    def test_a_changed_write_is_atomic_and_leaves_no_temp_file(self, lab: Lab) -> None:
        other = shim.ShimParams(**{**lab.params.__dict__, "sock": "/other/agent.sock"})
        assert shim.write(lab.path, shim.render(other)) is True
        assert "/other/agent.sock" in lab.path.read_text()
        assert [p.name for p in lab.path.parent.iterdir()] == ["carter-ssh-sign"]

    def test_every_value_is_shell_quoted_a_space_and_a_quote_survive(self, lab: Lab) -> None:
        text = lab.path.read_text()
        assert "it'\"'\"'s.sock" in text and shlex.quote(str(lab.run_dir)) in text

    @pytest.mark.parametrize("field", ["sock", "false_path", "keygen", "run_dir", "signer"])
    def test_a_relative_path_is_refused(self, lab: Lab, field: str) -> None:
        bad = {**lab.params.__dict__, field: "relative/path"}
        with pytest.raises(ValueError, match="absolute"):
            shim.render(shim.ShimParams(**bad))

    @pytest.mark.parametrize("key", ["ssh-ed25519", "a b c", "ssh-ed25519 AAAA\nssh-ed25519 BBBB"])
    def test_a_key_that_is_not_one_type_and_blob_line_is_refused(self, lab: Lab, key: str) -> None:
        with pytest.raises(ValueError, match="key"):
            shim.render(shim.ShimParams(**{**lab.params.__dict__, "key": key}))

    def test_the_allowed_operations_and_the_sentence_come_from_the_data(self, lab: Lab) -> None:
        text = lab.path.read_text()
        assert "|".join(load_rules().shim_y_ops) + ")" in text
        assert registry()[E_SHIM_REFUSED].message in text
        template = (Path(shim.__file__).parent / "templates" / "carter-ssh-sign.sh").read_text()
        assert "verify" not in template and "Signing refused" not in template  # not copied

    def test_the_recorded_hash_makes_the_shim_trusted_by_the_entry(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".carter").mkdir(parents=True)
        lab = Lab(tmp_path / "lab")
        data = shim.render(lab.params)
        target = shim.shim_path(home)
        shim.write(target, data)
        assert shim_state(home).ok is False  # not recorded yet
        record = {"files": [{"path": str(target), "sha256": shim.sha256_of(data)}]}
        (home / ".carter" / "guard-state.json").write_text(json.dumps(record))
        assert shim_state(home).ok is True


@pytest.mark.parametrize("shell", SHELLS)
class TestContract:
    def test_git_real_sign_argv_signs_with_a_private_copy_of_the_key(
        self, lab: Lab, shell: list[str]
    ) -> None:
        keyfile = lab.key_file(KEY + "\n")
        done = lab.call(shell, *lab.sign_argv(keyfile))
        assert done.returncode == 0 and done.stderr == ""
        seen = lab.recorded()
        assert seen[0] == "ARGC=8"
        assert seen[1:5] == ["ARG=-Y", "ARG=sign", "ARG=-n", "ARG=git"]
        assert seen[5] == "ARG=-f" and seen[7] == "ARG=-U"
        copy = Path(seen[6].removeprefix("ARG="))
        assert copy != keyfile and copy.name == "key.pub" and lab.run_dir in copy.parents
        assert seen[8] == f"ARG={lab.root / 'buf'}"
        assert f"FILE={KEY}" in seen  # the copy holds exactly the configured key
        assert not list(lab.run_dir.iterdir())  # the private directory is removed

    def test_a_trailing_comment_in_gits_file_is_tolerated_and_not_passed_on(
        self, lab: Lab, shell: list[str]
    ) -> None:
        done = lab.call(shell, *lab.sign_argv(lab.key_file(KEY + " llm@laptop some comment\n")))
        assert done.returncode == 0
        assert f"FILE={KEY}" in lab.recorded() and "laptop" not in "".join(lab.recorded())

    def test_a_key_file_without_a_final_newline_is_read(self, lab: Lab, shell: list[str]) -> None:
        assert lab.call(shell, *lab.sign_argv(lab.key_file(KEY))).returncode == 0

    def test_the_environment_is_ours_not_the_callers(self, lab: Lab, shell: list[str]) -> None:
        hostile = {
            "SSH_AUTH_SOCK": "/home/human/.ssh/agent.sock",
            "SSH_ASKPASS": "/tmp/evil",
            "SSH_ASKPASS_REQUIRE": "never",
            "PATH": "/tmp/evil-bin",
        }
        done = lab.call(shell, *lab.sign_argv(lab.key_file()), env=hostile)
        assert done.returncode == 0
        seen = lab.recorded()
        assert f"SOCK={lab.sock}" in seen
        assert "ASKPASS=/usr/bin/false" in seen and "REQUIRE=force" in seen

    @pytest.mark.parametrize(
        ("name", "argv", "text"),
        [
            ("path key: no -U", ["-Y", "sign", "-n", "git", "-f", "{kf}", "{buf}"], KEY),
            ("extra option", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}", "-O", "x"], KEY),
            ("other namespace", ["-Y", "sign", "-n", "file", "-f", "{kf}", "-U", "{buf}"], KEY),
            ("options reordered", ["-Y", "sign", "-f", "{kf}", "-n", "git", "-U", "{buf}"], KEY),
            ("no buffer", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U"], KEY),
            ("just the operation", ["-Y", "sign"], KEY),
            ("the human's key", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], OTHER),
            ("same type, other blob", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], KEY[:-4] + "XXXX"),
            ("two keys in the file", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], KEY + "\n" + OTHER),
            ("the other key first", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], OTHER + "\n" + KEY),
            ("empty file", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], ""),
            ("a private key header", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], "-----BEGIN OPENSSH PRIVATE KEY-----"),
            ("type only", ["-Y", "sign", "-n", "git", "-f", "{kf}", "-U", "{buf}"], "ssh-ed25519"),
        ],
    )  # fmt: skip
    def test_everything_but_the_exact_argv_with_the_exact_key_is_refused(
        self, lab: Lab, shell: list[str], name: str, argv: list[str], text: str
    ) -> None:
        keyfile = lab.key_file(text + "\n")
        argv = [a.format(kf=keyfile, buf=lab.root / "buf") for a in argv]
        done = lab.call(shell, *argv)
        assert done.returncode == 1, name
        assert done.stderr.startswith(f"{E_SHIM_REFUSED}: {registry()[E_SHIM_REFUSED].message}")
        assert lab.recorded() == [], name  # the signer never ran
        assert not list(lab.run_dir.iterdir())

    def test_a_missing_or_directory_key_file_is_refused(self, lab: Lab, shell: list[str]) -> None:
        for target in (lab.root / "absent", lab.root):
            done = lab.call(shell, *lab.sign_argv(target))
            assert done.returncode == 1 and lab.recorded() == []

    @pytest.mark.parametrize(
        "args",
        [
            ["-Y", "generate"],
            ["-Y", "match-principals"],
            ["-Y"],
            ["-Y", ""],
            ["-lf", "x"],
            ["-t", "ed25519"],
            ["-s", "x"],
            [],
            ["sign"],
            ["-y", "sign"],
        ],
        ids=lambda a: " ".join(a) or "none",
    )
    def test_any_other_operation_or_a_missing_dash_y_is_refused(
        self, lab: Lab, shell: list[str], args: list[str]
    ) -> None:
        done = lab.call(shell, *args)
        assert done.returncode == 1 and E_SHIM_REFUSED in done.stderr
        assert lab.recorded() == []

    @pytest.mark.parametrize(
        "args",
        [
            ["-Y", "verify", "-n", "git", "-f", "/a b/allowed", "-I", "llm@example.invalid",
             "-s", "/tmp/sig", "-Overify-time=20261104031502"],
            ["-Y", "find-principals", "-f", "/x/allowed", "-s", "/tmp/sig", "-O", "verify-time=20261104031502"],
            ["-Y", "check-novalidate", "-n", "git", "-s", "/tmp/sig", "-Overify-time=1"],
        ],
        ids=["verify", "find-principals", "check-novalidate"],
    )  # fmt: skip
    def test_verification_operations_pass_through_with_any_o_option_and_stdin(
        self, lab: Lab, shell: list[str], args: list[str]
    ) -> None:
        done = lab.call(shell, *args, stdin="the signed payload\n", rc=1)
        assert done.returncode == 1  # the exit status of ssh-keygen comes back unchanged
        seen = lab.recorded()
        assert seen[0] == f"ARGC={len(args)}"
        assert [s for s in seen if s.startswith("ARG=")] == [f"ARG={a}" for a in args]
        assert "STDIN=the signed payload" in seen
        assert f"SOCK={lab.sock}" in seen and "REQUIRE=force" in seen

    def test_the_exit_status_of_the_signer_is_the_shims(self, lab: Lab, shell: list[str]) -> None:
        done = lab.call(shell, *lab.sign_argv(lab.key_file()), rc=7)
        assert done.returncode == 7 and not list(lab.run_dir.iterdir())

    def test_paths_with_spaces_and_quotes_are_passed_intact(
        self, lab: Lab, shell: list[str]
    ) -> None:
        buffer = lab.root / "a b" / "it's a buffer"
        buffer.parent.mkdir()
        argv = ["-Y", "sign", "-n", "git", "-f", str(lab.key_file()), "-U", str(buffer)]
        assert lab.call(shell, *argv).returncode == 0
        assert f"ARG={buffer}" in lab.recorded()

    def test_a_signal_removes_the_private_directory(self, lab: Lab, shell: list[str]) -> None:
        argv = [*shell, str(lab.path), *lab.sign_argv(lab.key_file())]
        env = {"PATH": "/nonexistent", "FAKE_LOG": str(lab.log), "FAKE_SLEEP": "30"}
        proc = subprocess.Popen(argv, env=env, start_new_session=True, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not list(lab.run_dir.iterdir()):
            time.sleep(0.02)
        assert list(lab.run_dir.iterdir()), "the shim never reached the signer"
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
        assert not list(lab.run_dir.iterdir())

    def test_a_missing_run_directory_fails_closed(self, lab: Lab, shell: list[str]) -> None:
        shutil.rmtree(lab.run_dir)
        done = lab.call(shell, *lab.sign_argv(lab.key_file()))
        assert done.returncode == 1 and E_SHIM_REFUSED in done.stderr and lab.recorded() == []


@pytest.mark.parametrize("shell", SHELLS)
class TestFileMode:
    """a key without a passphrase is signed from its configured file, and from no other."""

    @pytest.fixture
    def file_lab(self, tmp_path: Path) -> Lab:
        private = tmp_path / "keys" / "id_llm"
        private.parent.mkdir()
        private.write_text("not read by the shim\n")
        return Lab(tmp_path, file_key=str(private))

    def test_it_signs_from_the_configured_file_without_an_agent_or_a_copy(
        self, file_lab: Lab, shell: list[str]
    ) -> None:
        done = file_lab.call(shell, *file_lab.sign_argv(file_lab.key_file()))
        assert done.returncode == 0 and done.stderr == ""
        seen = file_lab.recorded()
        assert seen[:7] == [
            "ARGC=7", "ARG=-Y", "ARG=sign", "ARG=-n", "ARG=git", "ARG=-f",
            f"ARG={file_lab.params.file_key}",
        ]  # fmt: skip
        assert seen[7] == f"ARG={file_lab.root / 'buf'}" and "ARG=-U" not in seen
        assert not list(file_lab.run_dir.iterdir())  # nothing was copied

    def test_the_key_git_names_must_still_be_the_configured_one(
        self, file_lab: Lab, shell: list[str]
    ) -> None:
        done = file_lab.call(shell, *file_lab.sign_argv(file_lab.key_file(OTHER + "\n")))
        assert done.returncode == 1 and file_lab.recorded() == []
        done = file_lab.call(shell, *file_lab.sign_argv(file_lab.key_file()), "extra")
        assert done.returncode == 1 and file_lab.recorded() == []

    def test_a_vanished_key_file_is_refused(self, file_lab: Lab, shell: list[str]) -> None:
        Path(file_lab.params.file_key).unlink()
        done = file_lab.call(shell, *file_lab.sign_argv(file_lab.key_file()))
        assert done.returncode == 1 and file_lab.recorded() == [] and "missing" in done.stderr

    def test_verification_still_passes_through(self, file_lab: Lab, shell: list[str]) -> None:
        done = file_lab.call(shell, "-Y", "check-novalidate", "-n", "git", "-s", "x.sig")
        assert done.returncode == 0 and file_lab.recorded()[1:3] == [
            "ARG=-Y",
            "ARG=check-novalidate",
        ]

    def test_the_path_must_be_absolute(self, tmp_path: Path, shell: list[str]) -> None:
        with pytest.raises(ValueError):
            Lab(tmp_path, file_key="relative/key")


@pytest.mark.parametrize("shell", SHELLS)
class TestProgramSetups:
    """``--signing-program`` keeps the shim: only *sign* goes to the program."""

    def test_sign_goes_to_the_program_and_verify_to_ssh_keygen(
        self, tmp_path: Path, shell: list[str]
    ) -> None:
        lab = Lab(tmp_path, program=True)
        assert lab.call(shell, *lab.sign_argv(lab.key_file())).returncode == 0
        assert lab.recorded()[0] == "ARGC=8"
        first = len(lab.recorded())
        lab.call(shell, "-Y", "check-novalidate", "-n", "git", "-s", "/tmp/s")
        assert len(lab.recorded()) > first
        # both fakes append to one log; tell them apart by the executable that ran
        text = lab.path.read_text()
        assert str(lab.program) in text and str(lab.keygen) in text

    def test_a_program_setup_without_a_socket_does_not_export_one(
        self, tmp_path: Path, shell: list[str]
    ) -> None:
        lab = Lab(tmp_path, program=True)
        lab.call(shell, *lab.sign_argv(lab.key_file()))
        assert "SOCK=<unset>" in lab.recorded()

    def test_the_human_key_still_cannot_reach_the_program(
        self, tmp_path: Path, shell: list[str]
    ) -> None:
        lab = Lab(tmp_path, program=True)
        done = lab.call(shell, *lab.sign_argv(lab.key_file(OTHER + "\n")))
        assert done.returncode == 1 and lab.recorded() == []


class TestPreflight:
    def test_openssh_below_the_minimum_is_e_ssh_old(self) -> None:
        assert shim.MIN_OPENSSH == (8, 4)
        with pytest.raises(IdentityError) as err:
            shim.check_openssh("/usr/bin", run=lambda argv: "OpenSSH_8.3p1, OpenSSL 1.1.1")
        assert err.value.code == E_SSH_OLD
        assert shim.check_openssh("/x", run=lambda argv: "OpenSSH_8.4p1, OpenSSL") == (8, 4)
        assert shim.check_openssh("/x", run=lambda argv: "OpenSSH_10.3p1, LibreSSL") == (10, 3)

    def test_the_ssh_binary_is_taken_from_the_configured_directory(self) -> None:
        seen: list[list[str]] = []

        def fake(argv: list[str]) -> str:
            seen.append(argv)
            return "OpenSSH_9.0p1"

        shim.check_openssh("/opt/homebrew/bin", run=fake)
        assert seen == [["/opt/homebrew/bin/ssh", "-V"]]

    def test_unparseable_output_is_an_error_not_a_pass(self) -> None:
        for bad in ("", "something else"):
            with pytest.raises(IdentityError) as err:
                shim.check_openssh("/usr/bin", run=lambda argv, text=bad: text)
            assert err.value.code == E_SSH_OLD

    def test_git_below_2_40_is_e_git_old_with_the_signing_text(self) -> None:
        assert shim.MIN_GIT_SIGNING == (2, 40)
        with pytest.raises(IdentityError) as err:
            shim.check_git(run=lambda argv: "git version 2.39.5")
        assert err.value.code == E_GIT_OLD and "2.40" in str(err.value)
        assert shim.check_git(run=lambda argv: "git version 2.40.0") == (2, 40)
        assert shim.check_git(run=lambda argv: "git version 2.51.0 (Apple Git-150)") == (2, 51)

    def test_the_real_tools_pass_the_preflight_on_this_machine(self) -> None:
        if not Path("/usr/bin/ssh").exists():
            pytest.skip("no OpenSSH in /usr/bin")
        assert shim.check_openssh("/usr/bin") >= shim.MIN_OPENSSH
        assert shim.check_git() >= shim.MIN_GIT_SIGNING


# --- the real tools -------------------------------------------------------------------------------

git_ok = (
    shutil.which("git") is not None
    and (
        shim.parse_version(
            subprocess.run(["git", "--version"], capture_output=True, text=True).stdout,
            r"git version (\d+)\.(\d+)",
        )
        or (0, 0)
    )
    >= shim.MIN_GIT_SIGNING
)
needs_git = pytest.mark.skipif(not git_ok, reason="git >= 2.40 is needed for -U with key::")


class Real:
    """The shim in front of a real dedicated agent, and a repo whose env is the real block."""

    def __init__(self, rig: Rig, agent: Any, key: KeyPair, tmp: Path, shell_path: str = "/bin/sh"):
        self.rig, self.agent, self.key = rig, agent, key
        self.run_dir = tmp / "run"
        self.run_dir.mkdir(mode=0o700)
        params = shim.ShimParams(
            key=key.blob,
            sock=str(agent.sock),
            false_path=shim.resolve_false(),
            keygen="/usr/bin/ssh-keygen",
            run_dir=str(self.run_dir),
        )
        self.shim = tmp / "home" / ".carter" / "bin" / "carter-ssh-sign"
        data = shim.render(params)
        shim.write(self.shim, data)
        self.allowed = tmp / "allowed_signers"
        self.allowed.write_text(f'llm@example.invalid namespaces="git" {key.blob}\n')
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.signing_env = self.env_for(key.blob)

    def env_for(self, blob: str, program: str | None = None) -> dict[str, str]:
        block = {
            "env": {
                "GIT_COMMITTER_NAME": "LLM Bot",
                "GIT_COMMITTER_EMAIL": "llm@example.invalid",
                "CARTER_IDENTITY": "llm-bot",
            },
            "git_config": [
                ["gpg.format", "ssh"],
                ["user.signingkey", f"key::{blob}"],
                ["gpg.ssh.program", program or str(self.shim)],
                ["commit.gpgsign", "true"],
            ],
            "fingerprint": self.key.fingerprint,
        }
        env = to_git_env({}, block).env
        n = int(env["GIT_CONFIG_COUNT"])
        env[f"GIT_CONFIG_KEY_{n}"] = "gpg.ssh.allowedSignersFile"
        env[f"GIT_CONFIG_VALUE_{n}"] = str(self.allowed)
        env["GIT_CONFIG_COUNT"] = str(n + 1)
        return env

    def git(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            timeout=30,
            check=False,
        )

    def stage(self, text: str = "x") -> None:
        (self.repo / "f.txt").write_text(text)
        self.git("add", "-A")

    def commit(self, message: str = "m", env: dict[str, str] | None = None, *flags: str):  # type: ignore[no-untyped-def]
        return self.git("commit", "-q", *flags, "-m", message, env=env or self.signing_env)


@pytest.fixture
def real(rig: Rig, real_ssh_agent: Any, throwaway_key: Any, tmp_path: Path) -> Real:
    key: KeyPair = throwaway_key("ed25519")
    assert real_ssh_agent.add(key) == 0
    return Real(rig, real_ssh_agent, key, tmp_path)


@real_ssh
@needs_git
class TestRoundTrip:
    def test_a_commit_is_signed_and_verifies_good_against_the_stored_fingerprint(
        self, real: Real
    ) -> None:
        real.stage()
        start = time.perf_counter()
        done = real.commit()
        elapsed = time.perf_counter() - start
        assert done.returncode == 0, done.stderr
        assert elapsed < 2  # 10-20 ms on Linux, ~385 ms on macOS: asserted loosely
        shown = real.git("log", "-1", "--format=%G?|%GF|%GS|%cn|%an", env=real.signing_env)
        who = "llm@example.invalid|LLM Bot|Fixture Human"  # committer = the LLM, author = the human
        assert shown.stdout.strip() == f"G|{real.key.fingerprint}|{who}"
        good = real.git("verify-commit", "HEAD", env=real.signing_env)
        assert (
            good.returncode == 0 and 'Good "git" signature for llm@example.invalid' in good.stderr
        )
        assert not list(real.run_dir.iterdir())  # the shim cleaned up its private directory

    def test_no_key_loaded_wrong_key_no_socket_and_a_stale_socket_fail_with_the_raw_strings(
        self, real: Real, throwaway_key: Any
    ) -> None:
        real.stage()
        real.rig.run("ssh-add", "-D", sock=real.agent.sock)
        done = real.commit()
        assert done.returncode == 128
        assert done.stderr.startswith("error: Couldn't find key in agent?")
        assert "fatal: failed to write commit object" in done.stderr
        assert "A  f.txt" in real.git("status", "--short").stdout  # still staged
        other: KeyPair = throwaway_key("ed25519")
        assert real.agent.add(other) == 0  # a decoy "human" key in the same agent
        done = real.commit()
        assert done.returncode == 128 and "Couldn't find key in agent?" in done.stderr
        real.agent.kill(hard=True)  # stale: the socket file stays
        done = real.commit()
        assert done.returncode == 128 and "Couldn't get agent socket?" in done.stderr
        real.agent.sock.unlink()
        done = real.commit()
        assert done.returncode == 128 and "Couldn't get agent socket?" in done.stderr

    def test_the_decoy_human_key_in_the_same_agent_cannot_sign(
        self, real: Real, throwaway_key: Any
    ) -> None:
        decoy: KeyPair = throwaway_key("ed25519")
        assert real.agent.add(decoy) == 0
        real.stage()
        by_literal = real.commit(env=real.env_for(decoy.blob))  # -S<decoy> via user.signingkey
        assert by_literal.returncode == 128
        assert (
            E_SHIM_REFUSED in by_literal.stderr
            and "not the configured LLM key" in by_literal.stderr
        )
        by_path = real.commit(env={**real.signing_env, "GIT_CONFIG_VALUE_1": str(decoy.pub_path)})
        assert by_path.returncode == 128 and E_SHIM_REFUSED in by_path.stderr  # no -U
        assert "unsigned" not in by_path.stderr
        assert real.git("rev-list", "--count", "--all").stdout.strip() == "0"  # nothing committed

    def test_it_never_prompts_even_with_a_terminal_and_askpass_in_the_environment(
        self, real: Real, tmp_path: Path
    ) -> None:
        real.stage()
        real.rig.run("ssh-add", "-D", sock=real.agent.sock)
        marker = tmp_path / "askpass-called"
        askpass = tmp_path / "askpass.sh"
        askpass.write_text(f"#!/bin/sh\necho called >> {marker}\nexit 1\n")
        askpass.chmod(0o755)
        env = {
            **os.environ,
            **real.signing_env,
            "DISPLAY": ":99",
            "SSH_ASKPASS": str(askpass),
            "SSH_ASKPASS_REQUIRE": "prefer",
        }
        done = pty_run(
            ["/usr/bin/git", "commit", "-q", "-m", "x"], env, [(PASSPHRASE_PROMPT, "")], cwd=real.repo, timeout=20
        )  # fmt: skip
        assert done.rc == 128, done.output
        assert "assphrase" not in done.output  # no prompt appeared on the terminal
        assert "Couldn't find key in agent?" in done.output
        assert not marker.exists()

    def test_a_tag_is_signed_by_the_configured_key_only(
        self, real: Real, throwaway_key: Any
    ) -> None:
        real.stage()
        assert real.commit().returncode == 0
        assert real.git("tag", "-s", "t1", "-m", "tag", env=real.signing_env).returncode == 0
        assert real.git("tag", "-v", "t1", env=real.signing_env).returncode == 0
        decoy: KeyPair = throwaway_key("ed25519")
        real.agent.add(decoy)
        refused = real.git("tag", "-s", "t2", "-m", "x", env=real.env_for(decoy.blob))
        assert refused.returncode != 0 and E_SHIM_REFUSED in refused.stderr

    def test_the_fingerprint_in_the_payload_is_the_one_the_commit_carries(
        self, real: Real, tmp_path: Path
    ) -> None:
        cfg = IdentityConfig(
            identity=Identity(login="llm-bot", id=1, email="1+llm-bot@users.noreply.github.com"),
            signing=Signing(public_key=real.key.blob, fingerprint=real.key.fingerprint),
            state="current",
        )
        built = build_payload(
            cfg, resolve(cfg, workspace=None, env={}), ShimState(str(real.shim), True)
        )
        assert built.block is not None and built.block["fingerprint"] == real.key.fingerprint
        real.stage()
        env = {**to_git_env({}, built.block).env}
        n = int(env["GIT_CONFIG_COUNT"])
        env[f"GIT_CONFIG_KEY_{n}"], env[f"GIT_CONFIG_VALUE_{n}"] = (
            "gpg.ssh.allowedSignersFile",
            str(real.allowed),
        )
        env["GIT_CONFIG_COUNT"] = str(n + 1)
        assert real.commit(env=env).returncode == 0
        shown = real.git("log", "-1", "--format=%GF", env=env).stdout.strip()
        assert shown == real.key.fingerprint


@real_ssh
@needs_git
def test_a_passphrase_free_key_signs_with_no_agent_at_all(
    rig: Rig, real_ssh_agent: Any, throwaway_key: Any, tmp_path: Path
) -> None:
    key: KeyPair = throwaway_key("ed25519")  # nothing is added to any agent
    real = Real(rig, real_ssh_agent, key, tmp_path)
    shim.write(
        real.shim,
        shim.render(
            shim.ShimParams(
                key=key.blob,
                sock=str(tmp_path / "no-agent.sock"),
                false_path=shim.resolve_false(),
                keygen="/usr/bin/ssh-keygen",
                run_dir=str(real.run_dir),
                file_key=str(key.path),
            )
        ),
    )
    real.stage()
    done = real.commit()
    assert done.returncode == 0, done.stderr
    shown = real.git("log", "-1", "--format=%G?|%GF", env=real.signing_env).stdout.strip()
    assert shown == f"G|{key.fingerprint}"
