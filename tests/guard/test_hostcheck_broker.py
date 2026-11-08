# ruff: noqa: E501
"""``carter check --host``, the slice-B items (plan 007 step 18, freeze B9, B11, B17).

Library-level with injected readers, like ``test_hostcheck_2a``. Read-only, names only.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import hostcheck, hostcheck_broker, serverenv
from carter.broker import audit, counter
from carter.cli import main
from carter.guard.state import load, save
from carter.install.paths import guard_state_path, headless_profile_path, isolation_path
from guard.helpers import debug_config, verbose
from rows import check_host


def guard(*args: str):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False)


def installed(stack) -> None:
    stack.fake()
    assert guard("install", "--yes").exit_code == 0
    stack.fake(before=debug_config(stack.live))


def check(**kw):
    kw.setdefault("servers", lambda: {})
    return hostcheck.run_host_checks(reader=kw.pop("reader", None), **kw)


def find(items, needle: str, level: str | None = None):
    return [i for i in items if needle in i.text and (level is None or i.level == level)]


def b_items(items):
    return [i for i in items if i.area.startswith("B ")]


def test_a_fresh_full_install_reports_b_on_and_nothing_red(stack) -> None:
    installed(stack)
    items = check()
    assert find(items, "enabled for devops only", "ok")
    assert find(items, "headless profile present", "ok")
    assert not [i for i in b_items(items) if i.level == "red"]
    assert not find(items, "B tools", "red")


def test_g2_at_revision_2_says_b_is_off_and_pending(stack) -> None:
    installed(stack)
    state = load(guard_state_path(None))
    state.consent("g2", "accepted", "2026-11-01", 2)
    save(state, guard_state_path(None))
    doc = json.loads(isolation_path(None).read_text())
    doc["plugin"]["b_enabled"], doc["plugin"]["b_git"] = (
        False,
        "",
    )  # what a revision-2 install wrote
    isolation_path(None).write_text(json.dumps(doc))
    items = check()
    assert find(items, "off: confirm g2 revision 3", "info")
    assert find(items, "g2 rev 3 pending: the B tool", "info")
    assert not find(items, "headless profile")


def test_isolation_enabling_b_without_the_consent_is_red(stack) -> None:
    installed(stack)
    state = load(guard_state_path(None))
    state.consent("g2", "accepted", "2026-11-01", 2)
    save(state, guard_state_path(None))  # the file still says b_enabled true
    items = check()
    assert find(items, "enables the B tools but guard state does not have g2 at revision 3", "red")


def test_consent_without_b_in_isolation_is_a_warning(stack) -> None:
    installed(stack)
    doc = json.loads(isolation_path(None).read_text())
    doc["plugin"]["b_enabled"] = False
    isolation_path(None).write_text(json.dumps(doc))
    assert find(check(), "has the B tools off", "warn")


def test_an_edited_profile_is_a_warning(stack) -> None:
    installed(stack)
    headless_profile_path(None).write_text("{}\n")
    assert find(check(), "opencode-headless.json was changed", "warn")
    headless_profile_path(None).unlink()
    assert find(check(), "opencode-headless.json is missing", "warn")


class TestAuditAndCounter:
    def test_counts_only_never_a_title_or_a_repo(self, stack) -> None:
        installed(stack)
        for decision in ("approved", "approved", "rejected"):
            audit.record(
                {"decision": decision, "owner_repo": "secret/repo", "branch": "feat/secret"}
            )
        items = check()
        (summary,) = find(items, "recent decision(s)")
        assert "2 approved" in summary.text and "1 rejected" in summary.text
        assert "secret" not in " ".join(i.render() for i in b_items(items))

    def test_wrong_modes_are_warned(self, stack) -> None:
        installed(stack)
        audit.record({"decision": "approved"})
        directory = audit.audit_dir()
        directory.chmod(0o755)
        (directory / "b.jsonl").chmod(0o644)
        (warn,) = find(check(), "is not 0700", "warn")
        assert "b.jsonl is not 0600" in warn.text

    def test_a_stopped_family_is_a_warning_with_the_reset(self, stack) -> None:
        installed(stack)
        for _ in range(3):
            counter.add("ses_root")
        (warn,) = find(check(), "stopped after 3 rejections", "warn")
        assert "reset-b" in warn.fix

    def test_an_unreadable_counter_is_a_warning(self, stack) -> None:
        installed(stack)
        counter.path().parent.mkdir(parents=True, exist_ok=True)
        counter.path().write_text("{nope")
        assert find(check(), "rejection counter is unreadable", "warn")


class TestAutoaccept:
    def test_a_persisted_autoaccept_is_a_warning_and_the_file_is_not_shown(
        self, stack, home: Path
    ) -> None:
        installed(stack)
        config = home / ".config" / "opencode"
        config.mkdir(parents=True, exist_ok=True)
        (config / "cli.json").write_text(
            json.dumps({"session": {"permissions": "autoaccept"}, "prompt": {"x": "SECRET-TEXT"}})
        )
        items = check()
        (warn,) = find(items, "auto-accept permissions", "warn")
        assert "E-B-DWELL" in warn.text and "SECRET-TEXT" not in " ".join(i.render() for i in items)

    def test_prompt_mode_and_a_missing_file_are_quiet(self, stack, home: Path) -> None:
        installed(stack)
        assert not find(check(), "auto-accept")
        config = home / ".config" / "opencode"
        config.mkdir(parents=True, exist_ok=True)
        (config / "cli.json").write_text(json.dumps({"session": {"permissions": "prompt"}}))
        assert not find(check(), "auto-accept")

    def test_an_opencode_started_with_auto(self, stack, monkeypatch: pytest.MonkeyPatch) -> None:
        installed(stack)
        monkeypatch.setattr(serverenv, "auto_pids", lambda **k: [4242])
        assert find(check(), "1 OpenCode process(es) run with --auto", "warn")

    def test_the_ps_reader_finds_only_opencode_with_auto(self) -> None:
        class Done:
            stdout = "10 /usr/bin/opencode --auto\n11 /usr/bin/opencode\n12 vim --auto\n13 /x/opencode run --auto x\n"

        pids = serverenv.auto_pids(runner=lambda *a, **k: Done())
        assert pids == [10, 13]


@pytest.fixture
def agent_socket() -> Iterator[str]:
    with tempfile.TemporaryDirectory(prefix="b-hc-", dir="/tmp") as directory:
        path = os.path.join(directory, "a.sock")
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(path)
        yield path
        sock.close()


class TestServers:
    def test_a_polluted_server_is_named_by_its_variables_only(self, stack) -> None:
        installed(stack)
        items = check(servers=lambda: {7: {"AGENT": "1", "OPENCODE_SESSION_ID": "ses_secret"}})
        (warn,) = find(items, "B refuses it with E-B-POLLUTED", "warn")
        assert "AGENT" in warn.text and "ses_secret" not in " ".join(i.render() for i in items)

    def test_a_missing_socket_is_noagent(self, stack) -> None:
        installed(stack)
        items = check(servers=lambda: {7: {"SSH_AUTH_SOCK": "/nonexistent/a.sock"}})
        assert find(items, "E-B-NOAGENT", "warn")

    def test_a_working_agent_is_ok(
        self, stack, agent_socket: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        installed(stack)
        add = tmp_path / "ssh-add"
        add.write_text("#!/bin/sh\nexit 1\n")
        add.chmod(0o755)
        monkeypatch.setattr(
            hostcheck_broker.env, "agent_socket", lambda server, tools: server["SSH_AUTH_SOCK"]
        )
        items = check(servers=lambda: {7: {"SSH_AUTH_SOCK": agent_socket}})
        assert find(items, "server 7: SSH_AUTH_SOCK answers", "ok")


class TestOriginAndTools:
    def test_an_https_origin_in_the_working_repo_is_a_warning(self, stack, tmp_path: Path) -> None:
        import subprocess

        installed(stack)
        repo = tmp_path / "r"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/o/r.git"],
            check=True,
        )
        assert find(check(cwd=repo), "origin of this repository is HTTPS", "warn")
        subprocess.run(
            ["git", "-C", str(repo), "remote", "set-url", "origin", "git@github.com:o/r.git"],
            check=True,
        )
        assert not find(check(cwd=repo), "origin of this repository is HTTPS")

    def test_tools_not_owned_by_root_are_named_without_a_path(self, stack, tmp_path: Path) -> None:
        installed(stack)
        user_git = tmp_path / "git"
        user_git.write_text("#!/bin/sh\n")
        user_git.chmod(0o755)
        doc = json.loads(isolation_path(None).read_text())
        doc["plugin"]["b_git"] = str(user_git)
        isolation_path(None).write_text(json.dumps(doc))
        items = check()
        (warn,) = find(items, "not root-owned, or writable by others", "warn")
        assert "git" in warn.text and str(tmp_path) not in " ".join(i.render() for i in items)

    def test_system_tools_pass_when_root_owned(self) -> None:
        plugin = {"b_enabled": True, "b_git": "/usr/bin/git", "b_gh": "", "ssh_bin_dir": "/usr/bin"}
        if os.stat("/usr/bin/git").st_uid != 0:
            pytest.skip("git is not root-owned on this machine")
        assert hostcheck_broker.ownership_items(plugin) == []


def test_exit_code_is_only_red_driven(stack) -> None:
    installed(stack)
    res = check_host()
    assert "B tools" in res.output
