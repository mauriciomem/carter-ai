"""The hermetic fixture: no test reaches the developer's real
``~/.gitconfig``, ``~/.carter`` or ``~/.config/opencode``.

The autouse fixture lives in ``conftest.py``. These tests pin what it guarantees,
so later steps can write config and run git in temp repos without a second thought.
"""

from __future__ import annotations

import http.server
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

import pytest

from carter.home import carter_home
from carter.install.paths import _opencode_base
from host_guard import (
    HOST_FILES,
    STAT_ONLY_FILES,
    changed,
    digest_host,
    is_allowed_connect,
    is_local_host,
)

# Variables that can redirect git's author/committer or inject config.
POLLUTION_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0",
    "GIT_CONFIG_VALUE_0",
    "CARTER_IDENTITY",
    "CARTER_IDENTITY_ROLE",
    "CARTER_IDENTITY_MODE",
)


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


class TestHomeIsIsolated:
    def test_home_is_not_the_real_home(self, real_home: Path) -> None:
        assert Path(os.environ["HOME"]).resolve() != real_home.resolve()
        assert Path.home().resolve() != real_home.resolve()

    def test_carter_home_is_under_the_fixture_home(self, real_home: Path) -> None:
        assert not _inside(carter_home(), real_home)
        assert _inside(carter_home(), Path(os.environ["HOME"]))

    def test_opencode_config_dir_is_not_the_real_one(self, real_home: Path) -> None:
        assert not _inside(_opencode_base(None), real_home)

    def test_xdg_config_home_is_under_the_fixture_home(self, real_home: Path) -> None:
        xdg = Path(os.environ["XDG_CONFIG_HOME"])
        assert _inside(xdg, Path(os.environ["HOME"]))
        assert not _inside(xdg, real_home)

    def test_fixture_home_is_not_the_per_test_tmp_path(
        self, tmp_path: Path, base_dir: Path
    ) -> None:
        # Tests that list tmp_path/base_dir must not see the fixture's files.
        assert not _inside(Path(os.environ["HOME"]), tmp_path)
        assert not _inside(Path(os.environ["HOME"]), base_dir)
        assert list(tmp_path.iterdir()) == []


class TestGitIsIsolated:
    def test_git_config_global_points_into_the_fixture_home(self, real_home: Path) -> None:
        path = Path(os.environ["GIT_CONFIG_GLOBAL"])
        assert _inside(path, Path(os.environ["HOME"]))
        assert not _inside(path, real_home)
        assert path.is_file()

    def test_system_config_is_disabled(self) -> None:
        assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"

    def test_global_user_name_is_the_fixture_value(self) -> None:
        out = subprocess.run(
            ["git", "config", "--global", "--get", "user.name"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == "Fixture Human"

    def test_global_user_email_is_the_fixture_value(self) -> None:
        out = subprocess.run(
            ["git", "config", "--global", "--get", "user.email"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out == "fixture-human@example.invalid"

    def test_no_signing_key_is_visible(self) -> None:
        proc = subprocess.run(
            ["git", "config", "--get", "user.signingkey"], capture_output=True, text=True
        )
        assert proc.returncode == 1  # key not set
        assert proc.stdout == ""

    def test_ambient_git_identity_variables_are_cleared(self) -> None:
        leaked = [v for v in POLLUTION_VARS if v in os.environ]
        assert leaked == []

    @pytest.mark.parametrize("var", ["CARTER_IDENTITY_ROLE", "CARTER_IDENTITY_MODE"])
    def test_carter_identity_session_variables_are_cleared(self, var: str) -> None:
        # The resolver reads CARTER_IDENTITY_ROLE; a developer's shell must not leak in.
        assert var not in os.environ


class TestPollutedEnvHelper:
    def test_sets_every_pollution_variable(self, pollute_git_env) -> None:
        pollute_git_env()
        missing = [v for v in POLLUTION_VARS if v not in os.environ]
        assert missing == []

    def test_polluted_values_override_the_fixture_identity(self, pollute_git_env) -> None:
        pollute_git_env()
        proc = subprocess.run(
            ["git", "var", "GIT_COMMITTER_IDENT"], capture_output=True, text=True, check=True
        )
        assert "Polluter" in proc.stdout

    def test_pollution_is_undone_after_the_test(self) -> None:
        # Runs after the test above in file order; monkeypatch must have restored env.
        assert "GIT_COMMITTER_NAME" not in os.environ
        assert "CARTER_IDENTITY" not in os.environ

    def test_helper_accepts_an_explicit_monkeypatch(
        self, pollute_git_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pollute_git_env(monkeypatch)
        assert os.environ["GIT_AUTHOR_NAME"] == "Polluter"


class TestAmbientCarterVariablesDoNotLeak:
    """Run a nested pytest with a polluted environment: the fixture must clear it."""

    def test_polluted_shell_is_cleaned_before_the_test_body(self, tmp_path: Path) -> None:
        import sys

        probe = Path(__file__).parent / "test_hermetic.py"
        env = {
            **os.environ,
            "CARTER_IDENTITY_ROLE": "author",
            "CARTER_IDENTITY_MODE": "review",
            "CARTER_IDENTITY": "x",
        }
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"{probe}::TestGitIsIsolated::test_carter_identity_session_variables_are_cleared",
                f"{probe}::TestGitIsIsolated::test_ambient_git_identity_variables_are_cleared",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=probe.parent.parent,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr


# --- the host surfaces (OpenCode config, gh, network) ---------------


class TestOpencodeConfigIsSandboxed:
    """The guards write the global OpenCode config; a bug must land in the sandbox."""

    def test_default_config_path_resolves_into_the_fixture_home(self, real_home: Path) -> None:
        path = Path.home() / ".config" / "opencode" / "opencode.json"
        assert _inside(path, Path(os.environ["HOME"]))
        assert not _inside(path, real_home)

    def test_the_installer_config_writers_get_sandbox_paths(self, real_home: Path) -> None:
        from carter.install.mcp import config_target, global_config_files

        paths = (*global_config_files(None), config_target(None))
        assert all(_inside(p, Path(os.environ["HOME"])) for p in paths)
        assert not any(_inside(p, real_home) for p in paths)

    def test_writing_there_leaves_the_real_host_untouched(
        self, real_home: Path, real_host_digest: dict[str, str]
    ) -> None:
        from carter.install.mcp import config_target

        target = config_target(None)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"provider": {}}\n')
        assert digest_host(real_home) == real_host_digest

    @pytest.mark.parametrize(
        "var", ["OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT"]
    )
    def test_opencode_config_overrides_are_cleared(self, var: str) -> None:
        assert var not in os.environ


class TestHostDigest:
    def test_lists_every_guarded_file_even_when_absent(self, tmp_path: Path) -> None:
        digest = digest_host(tmp_path)
        assert tuple(digest) == (*HOST_FILES, *STAT_ONLY_FILES)
        assert set(digest.values()) == {"absent"}

    def test_the_guarded_files_cover_the_1g_surfaces(self) -> None:
        assert set(HOST_FILES) >= {
            ".gitconfig",
            ".config/opencode/opencode.json",
            ".config/opencode/opencode.jsonc",
            ".carter/config.toml",
            ".carter/manifest.json",
            ".carter/guard-state.json",
            ".carter/gitconfig",
            ".config/git/config",
        }
        assert ".carter/secrets/gh-read.token" in STAT_ONLY_FILES

    def test_detects_modification_creation_and_deletion(self, tmp_path: Path) -> None:
        (tmp_path / ".carter").mkdir()
        (tmp_path / ".gitconfig").write_text("a")
        (tmp_path / ".carter" / "manifest.json").write_text("m")
        before = digest_host(tmp_path)
        (tmp_path / ".gitconfig").write_text("b")
        (tmp_path / ".carter" / "guard-state.json").write_text("{}")
        (tmp_path / ".carter" / "manifest.json").unlink()
        after = digest_host(tmp_path)
        assert changed(before, after) == [
            ".carter/guard-state.json",
            ".carter/manifest.json",
            ".gitconfig",
        ]

    def test_unchanged_files_report_nothing(self, tmp_path: Path) -> None:
        (tmp_path / ".gitconfig").write_text("a")
        assert changed(digest_host(tmp_path), digest_host(tmp_path)) == []

    def test_repointing_a_symlink_counts_even_with_equal_content(self, tmp_path: Path) -> None:
        (tmp_path / "one").write_text("same")
        (tmp_path / "two").write_text("same")
        link = tmp_path / ".gitconfig"
        link.symlink_to(tmp_path / "one")
        before = digest_host(tmp_path)
        link.unlink()
        link.symlink_to(tmp_path / "two")
        assert changed(before, digest_host(tmp_path)) == [".gitconfig"]

    def test_the_token_file_is_looked_at_by_stat_and_never_opened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = tmp_path / ".carter" / "secrets" / "gh-read.token"
        token.parent.mkdir(parents=True)
        token.write_text("github_pat_SECRET")
        opened: list[object] = []
        real_read_bytes = Path.read_bytes
        monkeypatch.setattr(
            Path, "read_bytes", lambda self: opened.append(self) or real_read_bytes(self)
        )
        before = digest_host(tmp_path)
        assert token not in opened
        assert before[".carter/secrets/gh-read.token"].startswith("stat:17:")
        assert "SECRET" not in repr(before)
        token.write_text("github_pat_OTHER-VALUE")
        assert changed(before, digest_host(tmp_path)) == [".carter/secrets/gh-read.token"]

    def test_contents_never_appear_in_the_digest(self, tmp_path: Path) -> None:
        (tmp_path / ".gitconfig").write_text("super-secret-value")
        assert "super-secret" not in repr(digest_host(tmp_path))

    def test_the_session_baseline_was_taken_from_the_real_home(
        self, real_home: Path, real_host_digest: dict[str, str]
    ) -> None:
        assert real_host_digest == digest_host(real_home)


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True)


class TestRealToolsAreGuarded:
    @pytest.mark.parametrize(
        ("tool", "fixture"),
        [("gh", "fake_gh"), ("opencode", "fake_opencode"), ("ssh-keygen", "real_ssh_keygen")],
    )
    def test_the_real_tool_is_replaced_by_a_loud_stub(
        self, tool: str, fixture: str, guard_bin: Path
    ) -> None:
        assert Path(shutil.which(tool) or "").parent == guard_bin
        proc = _run(tool, "--version")
        assert proc.returncode == 97
        assert tool in proc.stderr
        assert fixture in proc.stderr
        assert proc.stdout == ""

    def test_git_is_still_the_real_git(self, guard_bin: Path) -> None:
        found = shutil.which("git")
        assert found is not None
        assert Path(found).parent != guard_bin
        assert _run("git", "--version").stdout.startswith("git version")

    def test_the_stubs_are_per_test_and_outside_the_fixture_home(self, guard_bin: Path) -> None:
        assert guard_bin.is_dir()
        assert not _inside(guard_bin, Path(os.environ["HOME"]))

    def test_real_ssh_keygen_is_an_explicit_opt_in(self, real_ssh_keygen: None) -> None:
        found = shutil.which("ssh-keygen")
        if found is None:
            pytest.skip("ssh-keygen is not installed")
        assert _run("ssh-keygen", "-?").returncode != 97


class TestFakeGh:
    def test_replaces_the_stub_and_keeps_git_reachable(self, fake_gh) -> None:
        fake_gh(stdout="gh version 0.0.0 (fake)\n")
        assert _run("gh", "--version").stdout == "gh version 0.0.0 (fake)\n"
        assert _run("git", "--version").returncode == 0

    def test_records_every_call_with_its_arguments(self, fake_gh) -> None:
        gh = fake_gh()
        _run("gh", "pr", "create", "--title", "a b", "--body", "line1\nline2")
        _run("gh", "auth", "status")
        assert gh.calls() == [
            ["pr", "create", "--title", "a b", "--body", "line1\nline2"],
            ["auth", "status"],
        ]

    def test_default_reply_and_scripted_rules_by_longest_prefix(self, fake_gh) -> None:
        gh = fake_gh(
            stdout="default\n",
            rules={
                "api": {"stdout": "api\n"},
                "api repos/o/r": {"stderr": "HTTP 403: Resource not accessible\n", "rc": 1},
            },
        )
        assert _run("gh", "version").stdout == "default\n"
        assert _run("gh", "api", "user").stdout == "api\n"
        denied = _run("gh", "api", "repos/o/r")
        assert (denied.returncode, denied.stdout) == (1, "")
        assert "HTTP 403" in denied.stderr
        assert len(gh.calls()) == 3

    def test_fake_gh_and_fake_opencode_work_together(self, fake_gh, fake_opencode) -> None:
        fake_gh(stdout="gh\n")
        fake_opencode("opencode v2.1.4")
        assert _run("gh", "x").stdout == "gh\n"
        assert _run("opencode", "--version").stdout == "opencode v2.1.4\n"

    def test_order_of_the_two_fakes_does_not_matter(self, fake_gh, fake_opencode) -> None:
        fake_opencode("opencode v2.1.4")
        fake_gh(stdout="gh\n")
        assert _run("gh", "x").stdout == "gh\n"
        assert _run("opencode", "--version").stdout == "opencode v2.1.4\n"


class TestFakeOpencodeConfigMode:
    def test_debug_config_prints_the_scripted_output(self, fake_opencode) -> None:
        fake_opencode(config_output='{"permission": {}}')
        proc = _run("opencode", "debug", "config")
        assert (proc.returncode, proc.stdout) == (0, '{"permission": {}}')

    def test_a_sequence_serves_one_output_per_call_and_repeats_the_last(
        self, fake_opencode
    ) -> None:
        fake_opencode(config_sequence=['{"n": 1}', '{"n": 2}'])
        seen = [_run("opencode", "debug", "config").stdout for _ in range(3)]
        assert seen == ['{"n": 1}', '{"n": 2}', '{"n": 2}']

    def test_exit_code_is_scripted(self, fake_opencode) -> None:
        fake_opencode(config_output="boom", config_exit=3)
        assert _run("opencode", "debug", "config").returncode == 3

    def test_unconfigured_debug_config_fails_loudly_instead_of_returning_agents(
        self, fake_opencode
    ) -> None:
        fake_opencode(agents_output='[{"name": "x"}]')
        proc = _run("opencode", "debug", "config")
        assert proc.returncode == 2
        assert "config_output" in proc.stderr
        assert proc.stdout == ""

    def test_debug_agents_is_unchanged(self, fake_opencode) -> None:
        fake_opencode(agents_output='[{"name": "x"}]', config_output="{}")
        assert _run("opencode", "debug", "agents").stdout == '[{"name": "x"}]'

    def test_config_and_agents_counters_are_independent(self, fake_opencode) -> None:
        fake_opencode(agents_sequence=["a1", "a2"], config_sequence=["c1", "c2"])
        assert _run("opencode", "debug", "config").stdout == "c1"
        assert _run("opencode", "debug", "agents").stdout == "a1"
        assert _run("opencode", "debug", "agents").stdout == "a2"
        assert _run("opencode", "debug", "config").stdout == "c2"


class TestNetworkIsBlocked:
    def test_a_non_loopback_connect_raises_and_is_recorded(
        self, blocked_connections: list[str]
    ) -> None:
        with pytest.raises(AssertionError, match="network"):
            socket.create_connection(("192.0.2.1", 443), timeout=1)
        assert blocked_connections
        blocked_connections.clear()  # expected here; the teardown check must not fail us

    def test_the_connect_primitive_is_guarded_too(self, blocked_connections: list[str]) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(AssertionError, match="network"):
                sock.connect(("198.51.100.7", 80))
            with pytest.raises(AssertionError, match="network"):
                sock.connect_ex(("198.51.100.7", 80))
        finally:
            sock.close()
        blocked_connections.clear()

    def test_name_resolution_of_a_remote_host_is_blocked(
        self, blocked_connections: list[str]
    ) -> None:
        with pytest.raises(AssertionError, match="network"):
            socket.getaddrinfo("api.github.com", 443)
        blocked_connections.clear()

    def test_a_unix_socket_outside_the_temp_tree_is_blocked(
        self, blocked_connections: list[str]
    ) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with pytest.raises(AssertionError, match="network"):
                sock.connect("/run/user/0/agent.sock")
        finally:
            sock.close()
        blocked_connections.clear()

    def test_a_unix_socket_in_the_temp_tree_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A relative name: macOS temp paths (/private/var/folders/...) plus pytest's names
        # exceed the 104-byte AF_UNIX limit, and "path too long" is not what is under test.
        monkeypatch.chdir(tmp_path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with pytest.raises(FileNotFoundError):  # reached the OS: the guard let it through
                sock.connect("nobody-listens.sock")
        finally:
            sock.close()

    def test_the_guard_judges_a_long_unix_path_without_touching_the_os(
        self, tmp_path: Path
    ) -> None:
        long_inside = str(tmp_path / ("d" * 120) / "nobody-listens.sock")  # > 108 bytes
        assert len(long_inside) > 108
        assert is_allowed_connect(long_inside, socket.AF_UNIX, tmp_path) is True
        outside = "/run/user/0/" + "d" * 120 + ".sock"
        assert is_allowed_connect(outside, socket.AF_UNIX, tmp_path) is False

    def test_a_loopback_http_server_still_works(self) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"pong")

            def log_message(self, *args: object) -> None:  # silence
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://localhost:{server.server_port}/"
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
                assert resp.read() == b"pong"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("127.0.0.1", True),
            ("127.1.2.3", True),
            ("::1", True),
            ("::ffff:127.0.0.1", True),
            ("localhost", True),
            ("0.0.0.0", True),
            (None, True),
            ("10.0.0.5", False),
            ("192.168.1.1", False),
            ("api.github.com", False),
            ("github.com", False),
            ("::ffff:8.8.8.8", False),
        ],
    )
    def test_is_local_host(self, host: str | None, expected: bool) -> None:
        assert is_local_host(host) is expected

    def test_git_subprocesses_cannot_use_network_transports(self, tmp_path: Path) -> None:
        proc = _run("git", "ls-remote", "https://example.invalid/x.git")
        assert proc.returncode != 0
        assert "not allowed" in proc.stderr
        # local transports stay available for tests that need a bare "remote"
        remote = tmp_path / "remote.git"
        assert _run("git", "init", "-q", "--bare", str(remote)).returncode == 0
        assert _run("git", "ls-remote", f"file://{remote}").returncode == 0


class TestAmbientHostSurfaces:
    @pytest.mark.parametrize("var", ["XDG_RUNTIME_DIR", "TMPDIR"])
    def test_runtime_and_tmp_dirs_are_in_the_sandbox(self, var: str, real_home: Path) -> None:
        path = Path(os.environ[var])
        assert _inside(path, Path(os.environ["HOME"]))
        assert path.is_dir()

    def test_tempfile_follows_the_sandbox_tmpdir(self) -> None:
        assert _inside(Path(tempfile.gettempdir()), Path(os.environ["HOME"]))

    @pytest.mark.parametrize(
        "var",
        [
            "SSH_AUTH_SOCK",
            "SSH_AGENT_PID",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GH_HOST",
            "AGENT",
            "AI_AGENT",
            "OPENCODE",
            "OPENCODE_SESSION_ID",
            "CARTER_AGENT_SHELL",
            "CARTER_HUMAN_SHELL",
        ],
    )
    def test_agent_sockets_and_tokens_do_not_leak_in(self, var: str) -> None:
        assert var not in os.environ


class TestPollutedShellIsCleaned:
    """A nested pytest in a polluted environment: the fixture must clean the new surfaces."""

    def test_ambient_agent_tokens_and_runtime_dirs_are_replaced(self) -> None:
        probe = Path(__file__)
        env = {
            **os.environ,
            "SSH_AUTH_SOCK": "/run/user/1000/ssh-agent.sock",
            "SSH_AGENT_PID": "4242",
            "GIT_SSH_COMMAND": "ssh -i /real/key",
            "GH_TOKEN": "x",
            "GITHUB_TOKEN": "y",
            "AGENT": "x",
            "OPENCODE_SESSION_ID": "ses_1",
            "CARTER_AGENT_SHELL": "1",
            "OPENCODE_CONFIG": "/real/opencode.json",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "TMPDIR": "/var/tmp",
        }
        nodes = [
            "TestAmbientHostSurfaces::test_runtime_and_tmp_dirs_are_in_the_sandbox",
            "TestAmbientHostSurfaces::test_tempfile_follows_the_sandbox_tmpdir",
            "TestAmbientHostSurfaces::test_agent_sockets_and_tokens_do_not_leak_in",
            "TestOpencodeConfigIsSandboxed::test_opencode_config_overrides_are_cleared",
        ]
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
            + [f"{probe}::{n}" for n in nodes],
            capture_output=True,
            text=True,
            env=env,
            cwd=probe.parent.parent,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
