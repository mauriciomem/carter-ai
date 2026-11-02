"""``carter github-token set|check`` (RFC-0007 App C.7; plan 003 step 16).

The token in these tests is a made-up sentinel, never a real credential, and the real
``~/.carter/secrets`` is never reachable (the sandbox home). ``check`` talks to a loopback
fake of api.github.com whose 403/422 bodies are the strings recorded in spike 4."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import ghtoken
from carter.cli import main
from carter.identity import IdentityError, load_identity
from carter.identity.errors import E_HUMAN_TERMINAL, E_PAT_PERM, E_PAT_TYPE
from carter.install.paths import token_path
from gh_api import EXPIRY_HEADER, SPIKE_401, SPIKE_403, SPIKE_404, SPIKE_422, ZERO_SHA, Reply

TAIL = "SENTINELSENTINEL_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TOKEN = "github_pat_11AAAAAAA0" + TAIL
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def leaks(token: str, *texts: str, n: int = 5) -> list[str]:
    """Substrings of ``token`` that are ``n`` characters long and found in any of ``texts``."""
    blob = "\n".join(texts)
    return [token[i : i + n] for i in range(len(token) - n + 1) if token[i : i + n] in blob]


class TestValidate:
    def test_a_fine_grained_token_passes_and_a_trailing_newline_is_dropped(self) -> None:
        assert ghtoken.validate_token(TOKEN) == TOKEN
        assert ghtoken.validate_token(TOKEN + "\n") == TOKEN
        assert ghtoken.validate_token(TOKEN + "\r\n") == TOKEN

    @pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"])
    def test_classic_and_app_tokens_are_refused_with_only_the_prefix_shown(
        self, prefix: str
    ) -> None:
        token = prefix + "x" * 36
        with pytest.raises(IdentityError) as exc:
            ghtoken.validate_token(token)
        assert exc.value.code == E_PAT_TYPE
        assert f"`{prefix}`" in str(exc.value)
        assert leaks(token, str(exc.value), exc.value.detail) == []

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", "\n", "github_pat_", "github_pat_short", "github_pat_ has space" + "x" * 30,
         TOKEN + "\n" + TOKEN, TOKEN + " ", " " + TOKEN, "github_pat_" + "é" * 30,
         "github_pat_" + "x" * 30 + "!", "x" * 5000, TOKEN + "x" * 5000, "hunter2-not-a-token"],
    )  # fmt: skip
    def test_everything_else_is_refused_without_echoing_it(self, raw: str) -> None:
        with pytest.raises(IdentityError) as exc:
            ghtoken.validate_token(raw)
        assert exc.value.code == E_PAT_TYPE
        text = str(exc.value) + exc.value.detail
        assert leaks(raw.replace(ghtoken.PAT_PREFIX, ""), text, n=8) == []  # nothing is echoed
        assert "hunter2" not in text

    def test_an_unknown_prefix_is_not_echoed_at_all(self) -> None:
        with pytest.raises(IdentityError) as exc:
            ghtoken.validate_token("hunter2-not-a-token")
        assert "hunter" not in str(exc.value) and "does not look like a GitHub token" in str(
            exc.value
        )

    def test_no_substring_beyond_four_characters_appears_in_any_error(self) -> None:
        for raw in (TOKEN[:-3] + "!!!", TOKEN + "\n" + TOKEN, "ghp_" + TOKEN[11:]):
            with pytest.raises(IdentityError) as exc:
                ghtoken.validate_token(raw)
            assert leaks(TOKEN[11:], str(exc.value), exc.value.detail, repr(exc.value)) == []


class TestStore:
    def test_writes_the_token_0600_in_a_0700_dir_without_a_newline(self, tmp_path: Path) -> None:
        res = ghtoken.store_token(TOKEN + "\n", tmp_path)
        path = token_path(tmp_path)
        assert res.path == path and path.read_bytes() == TOKEN.encode()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_the_process_umask_is_restored(self, tmp_path: Path) -> None:
        before = os.umask(0o022)
        try:
            ghtoken.store_token(TOKEN, tmp_path)
            assert os.umask(0o022) == 0o022
        finally:
            os.umask(before)

    def test_overwriting_replaces_atomically_and_a_failure_keeps_the_old_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        newer = "github_pat_22BBBBBBB0" + TAIL
        monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("busy")))
        with pytest.raises(OSError):
            ghtoken.store_token(newer, tmp_path)
        monkeypatch.undo()
        assert token_path(tmp_path).read_text() == TOKEN
        assert [p.name for p in token_path(tmp_path).parent.iterdir()] == ["gh-read.token"]
        ghtoken.store_token(newer, tmp_path)
        assert token_path(tmp_path).read_text() == newer

    def test_an_invalid_token_writes_nothing(self, tmp_path: Path) -> None:
        with pytest.raises(IdentityError):
            ghtoken.store_token("ghp_" + "x" * 36, tmp_path)
        assert not token_path(tmp_path).exists() and not token_path(tmp_path).parent.exists()

    def test_a_symlinked_target_is_refused(self, tmp_path: Path) -> None:
        path = token_path(tmp_path)
        path.parent.mkdir(parents=True, mode=0o700)
        real = tmp_path / "elsewhere"
        real.write_text("old")
        path.symlink_to(real)
        with pytest.raises(IdentityError) as exc:
            ghtoken.store_token(TOKEN, tmp_path)
        assert exc.value.code == E_PAT_PERM and real.read_text() == "old"

    def test_a_symlinked_secrets_dir_is_refused(self, tmp_path: Path) -> None:
        real = tmp_path / "real-secrets"
        real.mkdir(mode=0o700)
        path = token_path(tmp_path)
        path.parent.parent.mkdir(parents=True)
        path.parent.symlink_to(real)
        with pytest.raises(IdentityError) as exc:
            ghtoken.store_token(TOKEN, tmp_path)
        assert exc.value.code == E_PAT_PERM and list(real.iterdir()) == []

    @pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
    def test_a_wrong_mode_on_the_existing_file_is_refused(self, tmp_path: Path, mode: int) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        token_path(tmp_path).chmod(mode)
        with pytest.raises(IdentityError) as exc:
            ghtoken.store_token(TOKEN, tmp_path)
        assert exc.value.code == E_PAT_PERM

    def test_a_wrong_mode_on_the_secrets_dir_is_refused(self, tmp_path: Path) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        token_path(tmp_path).parent.chmod(0o755)
        with pytest.raises(IdentityError) as exc:
            ghtoken.store_token(TOKEN, tmp_path)
        assert exc.value.code == E_PAT_PERM and "0700" in exc.value.detail

    def test_a_file_not_owned_by_the_user_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        monkeypatch.setattr(ghtoken, "_euid", lambda: os.geteuid() + 1)
        with pytest.raises(IdentityError) as exc:
            ghtoken.store_token(TOKEN, tmp_path)
        assert exc.value.code == E_PAT_PERM and "owned" in exc.value.detail

    def test_a_location_inside_a_git_repository_is_refused(self, tmp_path: Path) -> None:
        base = tmp_path / "repo"
        (base / ".git").mkdir(parents=True)
        with pytest.raises(IdentityError) as exc:
            ghtoken.store_token(TOKEN, base)
        assert exc.value.code == E_PAT_PERM and "repository" in exc.value.detail
        assert not token_path(base).exists()

    def test_a_git_file_marker_counts_too(self, tmp_path: Path) -> None:
        base = tmp_path / "wt"
        base.mkdir()
        (base / ".git").write_text("gitdir: /elsewhere\n")
        with pytest.raises(IdentityError):
            ghtoken.store_token(TOKEN, base)

    def test_the_path_is_recorded_through_the_config_writer(self, tmp_path: Path) -> None:
        cfg = tmp_path / "carter" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            'schema = 2\n[identity]\nlogin = "llm"\nid = 7\n'
            'email = "7+llm@users.noreply.github.com"\n'
        )
        res = ghtoken.store_token(TOKEN, tmp_path)
        assert res.recorded is True
        loaded = load_identity(cfg)
        assert loaded.github.read_token_file == str(token_path(tmp_path))
        assert loaded.identity.login == "llm"  # the rest of the file survives

    def test_a_missing_config_is_created_with_schema_2(self, tmp_path: Path) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        cfg = tmp_path / "carter" / "config.toml"
        assert cfg.exists() and "schema = 2" in cfg.read_text()
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o600

    def test_a_schema_1_config_is_left_alone_and_the_token_is_still_stored(
        self, tmp_path: Path
    ) -> None:
        cfg = tmp_path / "carter" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[git]\nsigning_key = "x"\n')
        before = cfg.read_bytes()
        res = ghtoken.store_token(TOKEN, tmp_path)
        assert res.recorded is False and "carter install" in res.note
        assert cfg.read_bytes() == before and token_path(tmp_path).read_text() == TOKEN

    def test_a_broken_config_is_left_alone_too(self, tmp_path: Path) -> None:
        cfg = tmp_path / "carter" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("not = [toml")
        res = ghtoken.store_token(TOKEN, tmp_path)
        assert res.recorded is False and cfg.read_text() == "not = [toml"
        assert token_path(tmp_path).exists()

    def test_the_module_never_writes_the_token_into_the_config(self, tmp_path: Path) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        assert TAIL not in (tmp_path / "carter" / "config.toml").read_text()


class TestSetCommand:
    @pytest.fixture(autouse=True)
    def piped_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # `human_tty` fakes every stream; stdin is a pipe unless a test says otherwise.
        monkeypatch.setattr("carter.ghtoken_cli.stdin_is_tty", lambda: False)

    def run(self, *args: str, input: str | None = None):
        return CliRunner().invoke(
            main, ["github-token", "set", *args], input=input, catch_exceptions=False
        )

    def test_piped_stdin_with_a_terminal_on_stderr_stores_the_token(
        self, human_tty, tmp_path
    ) -> None:
        human_tty(True)
        res = self.run("--base-dir", str(tmp_path), input=TOKEN + "\n")
        assert res.exit_code == 0, res.output
        assert token_path(tmp_path).read_text() == TOKEN
        assert str(token_path(tmp_path)) in res.output
        assert "not printed" in res.output and "not injected into agent shells yet" in res.output
        assert leaks(TOKEN[11:], res.output) == []

    def test_a_terminal_on_stdin_uses_a_hidden_prompt(
        self, human_tty, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(True)
        import getpass

        asked: list[str] = []
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": asked.append(prompt) or TOKEN)
        monkeypatch.setattr("carter.ghtoken_cli.stdin_is_tty", lambda: True)
        res = self.run("--base-dir", str(tmp_path))
        assert res.exit_code == 0 and asked and "hidden" in asked[0]
        assert token_path(tmp_path).read_text() == TOKEN

    def test_a_wrong_token_type_is_reported_with_the_prefix_only(self, human_tty, tmp_path) -> None:
        human_tty(True)
        classic = "ghp_" + "Z" * 36
        res = self.run("--base-dir", str(tmp_path), input=classic)
        assert res.exit_code == 1 and "Error: E-PAT-TYPE" in res.output and "`ghp_`" in res.output
        assert "ZZZZZ" not in res.output
        assert not token_path(tmp_path).exists()

    def test_it_refuses_in_an_agent_shell_before_reading_stdin(
        self, human_tty, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(True)
        monkeypatch.setenv("AGENT", "x")
        res = self.run("--base-dir", str(tmp_path), input=TOKEN)
        assert res.exit_code == 1 and f"Error: {E_HUMAN_TERMINAL}" in res.output
        assert not token_path(tmp_path).exists() and TAIL not in res.output

    def test_it_needs_a_terminal_on_stderr(self, human_tty, tmp_path) -> None:
        human_tty(False)
        res = self.run("--base-dir", str(tmp_path), input=TOKEN)
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output and "stderr" in res.output
        assert not token_path(tmp_path).exists()

    def test_it_takes_no_arguments(self, human_tty, tmp_path) -> None:
        human_tty(True)
        res = CliRunner().invoke(main, ["github-token", "set", TOKEN])
        assert res.exit_code == 2 and TAIL not in res.output and "takes no arguments" in res.output

    def test_help_lists_set_and_check(self) -> None:
        out = CliRunner().invoke(main, ["github-token", "--help"]).output
        assert "set" in out and "check" in out


class TestExpiry:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("2027-01-31 15:17:13 UTC", datetime(2027, 1, 31, 15, 17, 13, tzinfo=UTC)),
            (" 2026-11-10 00:00:00 UTC ", datetime(2026, 11, 10, tzinfo=UTC)),
        ],
    )
    def test_parses_the_recorded_format(self, header: str, expected: datetime) -> None:
        assert ghtoken.parse_expiry(header) == expected

    @pytest.mark.parametrize(
        "bad",
        ["", "soon", "2027-01-31", "2027-13-31 00:00:00 UTC", "2027-01-31 15:17:13 PST", "None"],
    )
    def test_anything_else_is_none(self, bad: str) -> None:
        assert ghtoken.parse_expiry(bad) is None


class TestClassifyProbe:
    """The recorded spike-4 strings, classified by status and text (never an exit code)."""

    def test_the_recorded_403_is_read_only(self) -> None:
        assert ghtoken.classify_probe(403, SPIKE_403) == "read-only"

    def test_the_gh_cli_wording_is_read_only_too(self) -> None:
        assert (
            ghtoken.classify_probe(
                403, "gh: Resource not accessible by personal access token (HTTP 403)"
            )
            == "read-only"
        )

    @pytest.mark.parametrize("status", [201, 422])
    def test_201_and_422_mean_writable(self, status: int) -> None:
        assert ghtoken.classify_probe(status, SPIKE_422) == "writable"
        assert ghtoken.classify_probe(status, "") == "writable"

    @pytest.mark.parametrize(
        ("status", "body"),
        [(404, SPIKE_404), (401, SPIKE_401), (403, '{"message":"API rate limit exceeded"}'),
         (403, ""), (500, "boom"), (0, ""), (302, "")],
    )  # fmt: skip
    def test_everything_else_is_unprobed(self, status: int, body: str) -> None:
        assert ghtoken.classify_probe(status, body) == "unprobed"


def levels(items) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i in items:
        out.setdefault(i.level, []).append(f"{i.area}: {i.text}")
    return out


class TestCheck:
    @pytest.fixture
    def stored(self, tmp_path: Path) -> Path:
        ghtoken.store_token(TOKEN, tmp_path)
        return tmp_path

    def test_a_read_only_token_with_a_distant_expiry_is_all_green(self, stored, github_api) -> None:
        github_api.readonly_token_world(expiry="2027-01-31 15:17:13 UTC")
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert "red" not in got and "warn" not in got
        text = " ".join(got["ok"])
        assert "github_pat_" in text and "read-only" in text and "2027-01-31" in text

    def test_the_probe_is_the_only_write_and_carries_exactly_the_zero_sha(
        self, stored, github_api
    ) -> None:
        github_api.readonly_token_world()
        ghtoken.check_token(stored, now=NOW)
        assert [(r.method, r.path.split("?")[0]) for r in github_api.requests] == [
            ("GET", "/user"),
            ("GET", "/user/repos"),
            ("POST", "/repos/o/r/git/refs"),
        ]
        assert github_api.unexpected == []
        post = github_api.requests[-1]
        assert json.loads(post.body) == {"ref": "refs/heads/carter-write-probe", "sha": ZERO_SHA}
        assert ZERO_SHA == "0" * 40

    def test_the_token_is_only_ever_in_the_authorization_header(self, stored, github_api) -> None:
        github_api.readonly_token_world()
        ghtoken.check_token(stored, now=NOW)
        for req in github_api.requests:
            assert req.headers["authorization"] == f"Bearer {TOKEN}"
            assert TAIL not in req.path and TAIL.encode() not in req.body
            others = {k: v for k, v in req.headers.items() if k != "authorization"}
            assert TAIL not in json.dumps(others)

    def test_expiry_within_14_days_warns(self, stored, github_api) -> None:
        github_api.readonly_token_world(expiry="2026-11-14 12:00:00 UTC")
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert "red" not in got and any("12 day" in w for w in got["warn"])

    @pytest.mark.parametrize(
        ("expiry", "warns"), [("2026-11-16 12:00:00 UTC", True), ("2026-11-17 12:00:01 UTC", False)]
    )
    def test_the_threshold_is_14_days(self, stored, github_api, expiry: str, warns: bool) -> None:
        github_api.readonly_token_world(expiry=expiry)
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert bool(got.get("warn")) is warns

    def test_no_expiry_header_is_an_info(self, stored, github_api) -> None:
        github_api.readonly_token_world(expiry=None)
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("no expiry header" in t for t in got["info"]) and "warn" not in got

    def test_an_unparseable_expiry_header_warns(self, stored, github_api) -> None:
        github_api.readonly_token_world(expiry="tomorrow-ish")
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("cannot read the expiry" in w for w in got["warn"])

    @pytest.mark.parametrize("status", [422, 201])
    def test_a_writable_token_is_red(self, stored, github_api, status: int) -> None:
        github_api.readonly_token_world()
        github_api.on("POST", "/repos/o/r/git/refs", Reply(status, SPIKE_422))
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("WRITABLE" in t and "o/r" in t for t in got["red"])

    def test_probe_404_means_unprobed_not_ok(self, stored, github_api) -> None:
        github_api.readonly_token_world()
        github_api.on("POST", "/repos/o/r/git/refs", Reply(404, SPIKE_404))
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert "red" not in got and any("unprobed" in w for w in got["warn"])
        assert not any("read-only" in t for t in got.get("ok", []))

    def test_no_covered_repository_is_unprobed(self, stored, github_api) -> None:
        github_api.readonly_token_world()
        github_api.on("GET", "/user/repos", Reply(200, "[]"))
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("unprobed" in w and "covers no repository" in w for w in got["warn"])
        assert [r.method for r in github_api.requests] == ["GET", "GET"]  # nothing to POST to

    def test_an_unexpected_403_text_is_unprobed(self, stored, github_api) -> None:
        github_api.readonly_token_world()
        github_api.on("POST", "/repos/o/r/git/refs", Reply(403, '{"message":"SAML enforcement"}'))
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert "red" not in got and any("unprobed" in w for w in got["warn"])

    def test_a_rejected_token_is_red(self, stored, github_api) -> None:
        github_api.on("GET", "/user", Reply(401, SPIKE_401))
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("rejected" in t for t in got["red"])
        assert [r.method for r in github_api.requests] == ["GET"]

    def test_a_classic_token_header_is_red_even_with_the_right_prefix(
        self, stored, github_api
    ) -> None:
        github_api.readonly_token_world()
        github_api.on("GET", "/user", Reply(200, "{}", {"X-OAuth-Scopes": "repo, gist"}))
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any(E_PAT_TYPE in t for t in got["red"])

    def test_the_repository_selection_is_documented_as_an_info(self, stored, github_api) -> None:
        github_api.readonly_token_world()
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("repository selection" in t and "narrow" in t for t in got["info"])

    def test_nothing_reachable_is_red_for_the_type_and_warn_for_the_probe(
        self, stored, github_api
    ) -> None:
        github_api.stop()
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any("could not reach GitHub" in t for t in got["red"])

    def test_no_token_file_is_red_when_required_and_a_warn_when_optional(
        self, tmp_path, github_api
    ) -> None:
        required = levels(ghtoken.check_token(tmp_path, now=NOW))
        assert any("carter github-token set" in t for t in required["red"])
        optional = levels(ghtoken.check_token(tmp_path, now=NOW, required=False))
        assert "red" not in optional and any("not provisioned" in t for t in optional["warn"])
        assert github_api.requests == []

    def test_a_file_with_wrong_perms_is_red_and_no_request_is_made(
        self, stored, github_api
    ) -> None:
        token_path(stored).chmod(0o644)
        got = levels(ghtoken.check_token(stored, now=NOW))
        assert any(E_PAT_PERM in t for t in got["red"]) and github_api.requests == []

    def test_a_symlinked_file_is_red_and_never_read_through(self, tmp_path, github_api) -> None:
        path = token_path(tmp_path)
        path.parent.mkdir(parents=True, mode=0o700)
        real = tmp_path / "real"
        real.write_text(TOKEN)
        path.symlink_to(real)
        got = levels(ghtoken.check_token(tmp_path, now=NOW))
        assert any(E_PAT_PERM in t for t in got["red"]) and github_api.requests == []

    def test_a_file_inside_a_repo_is_red(self, tmp_path, github_api) -> None:
        base = tmp_path / "repo"
        path = token_path(base)
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text(TOKEN)
        path.chmod(0o600)
        (base / ".git").mkdir()
        got = levels(ghtoken.check_token(base, now=NOW))
        assert any("inside a git repository" in t for t in got["red"]) and github_api.requests == []

    def test_a_non_pat_prefix_in_the_file_is_red_with_the_type_code_and_no_request(
        self, tmp_path, github_api
    ) -> None:
        path = token_path(tmp_path)
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text("ghp_" + "Q" * 36)
        path.chmod(0o600)
        got = levels(ghtoken.check_token(tmp_path, now=NOW))
        assert any(E_PAT_TYPE in t and "`ghp_`" in t for t in got["red"])
        assert github_api.requests == []
        assert "QQQQQ" not in repr(ghtoken.check_token(tmp_path, now=NOW))

    def test_the_token_never_appears_in_any_item(self, stored, github_api) -> None:
        github_api.readonly_token_world(expiry="2026-11-10 00:00:00 UTC")
        github_api.on("POST", "/repos/o/r/git/refs", Reply(422, SPIKE_422))
        assert leaks(TOKEN[11:], repr(ghtoken.check_token(stored, now=NOW))) == []


class TestApiBase:
    def test_default_is_github(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_API_URL", raising=False)
        assert ghtoken.api_base() == "https://api.github.com"

    @pytest.mark.parametrize(
        "url", ["http://127.0.0.1:8080", "http://localhost:1/", "https://ghe.example.com/api/v3"]
    )
    def test_loopback_http_and_any_https_are_accepted(self, url: str, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_API_URL", url)
        assert ghtoken.api_base() == url.rstrip("/")

    @pytest.mark.parametrize(
        "url", ["http://evil.example/", "ftp://x", "file:///etc", "javascript:1", "http://10.0.0.5"]
    )
    def test_a_plain_http_remote_would_leak_the_token_and_is_refused(
        self, url: str, monkeypatch
    ) -> None:
        monkeypatch.setenv("GITHUB_API_URL", url)
        with pytest.raises(IdentityError):
            ghtoken.api_base()

    def test_check_refuses_to_send_the_token_there(self, tmp_path, monkeypatch) -> None:
        ghtoken.store_token(TOKEN, tmp_path)
        monkeypatch.setenv("GITHUB_API_URL", "http://evil.example")
        got = levels(ghtoken.check_token(tmp_path, now=NOW))
        assert any("refusing to send the token" in t for t in got["red"])


class TestCheckCommand:
    def run(self, tmp_path: Path):
        return CliRunner().invoke(
            main, ["github-token", "check", "--base-dir", str(tmp_path)], catch_exceptions=False
        )

    def test_exit_0_and_nothing_secret_printed(self, tmp_path, github_api, human_tty) -> None:
        human_tty(True)
        ghtoken.store_token(TOKEN, tmp_path)
        github_api.readonly_token_world(expiry="2027-01-31 15:17:13 UTC")
        res = self.run(tmp_path)
        assert res.exit_code == 0, res.output
        assert "Token OK" in res.output and leaks(TOKEN[11:], res.output) == []

    def test_a_writable_token_exits_1(self, tmp_path, github_api, human_tty) -> None:
        human_tty(True)
        ghtoken.store_token(TOKEN, tmp_path)
        github_api.readonly_token_world()
        github_api.on("POST", "/repos/o/r/git/refs", Reply(422, SPIKE_422))
        res = self.run(tmp_path)
        assert res.exit_code == 1 and "WRITABLE" in res.output

    def test_it_refuses_in_an_agent_shell_and_makes_no_request(
        self, tmp_path, github_api, human_tty, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(True)
        ghtoken.store_token(TOKEN, tmp_path)
        monkeypatch.setenv("OPENCODE_SESSION_ID", "s")
        res = self.run(tmp_path)
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output and github_api.requests == []

    def test_it_does_not_need_a_terminal(self, tmp_path, github_api, human_tty) -> None:
        human_tty(False)
        ghtoken.store_token(TOKEN, tmp_path)
        github_api.readonly_token_world()
        assert self.run(tmp_path).exit_code == 0


class TestModuleHygiene:
    def test_no_subprocess_no_argv_for_secrets_no_print(self) -> None:
        import ast

        tree = ast.parse(Path(ghtoken.__file__).read_text(encoding="utf-8"))
        roots = {
            a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
        } | {
            (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        }
        assert not roots & {"subprocess", "click", "requests"}
        calls = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "print" not in calls

    def test_the_test_fixtures_are_the_recorded_spike_strings(self) -> None:
        assert "Resource not accessible by personal access token" in SPIKE_403
        assert json.loads(SPIKE_422)["message"] == "Object does not exist"
        assert EXPIRY_HEADER == "Github-Authentication-Token-Expiration"
