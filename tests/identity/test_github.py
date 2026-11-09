"""The unauthenticated GitHub client against the loopback fake."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from carter.identity import github
from carter.identity.errors import E_CONFIG, IdentityError
from carter.identity.github import GitHubError
from gh_api import RATE_HEADERS, FakeGitHub, Reply, fixture
from gh_api import web_base as oracle_web_base
from sentinels import fine_grained

KEY_A = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
KEY_B = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFDQnea8LgFZ8D5U5LltihuJT5SwVYKxvc17OZNaCgaU"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    server = FakeGitHub().start()
    monkeypatch.setenv("GITHUB_API_URL", server.url)
    yield server
    server.stop()


class TestNeverAuthenticated:
    def test_no_credentials_are_sent_even_with_tokens_in_the_environment(
        self, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", fine_grained("ENV"))
        monkeypatch.setenv("GITHUB_TOKEN", fine_grained("ENV2"))
        secrets = tmp_path / "home"  # a token file where ghtoken would look is not read either
        fake.public_world()
        fake.commit_world("octocat/hello", "a1" * 20)
        github.get_user("octocat")
        github.get_signing_keys("octocat")
        github.get_auth_keys("octocat")
        github.get_commit_verification("octocat", "hello", "a1" * 20)
        assert len(fake.requests) == 4
        assert fake.authorized_requests() == []
        for rec in fake.requests:
            assert set(rec.headers) <= {
                "host",
                "accept",
                "user-agent",
                "connection",
                "accept-encoding",
            }
            assert "ENV" not in json.dumps(rec.headers)
        assert not secrets.exists()
        assert fake.unexpected == []

    def test_accept_header_is_json_and_there_is_no_version_header(self, fake: FakeGitHub) -> None:
        fake.public_world()
        github.get_user("octocat")
        assert fake.requests[0].headers["accept"] == "application/vnd.github+json"
        assert "x-github-api-version" not in fake.requests[0].headers


class TestBaseUrl:
    def test_https_anywhere_http_only_on_loopback(self) -> None:
        assert github.api_base({"GITHUB_API_URL": "https://ghe.example.test/api/v3/"}) == (
            "https://ghe.example.test/api/v3"
        )
        assert (
            github.api_base({"GITHUB_API_URL": "http://127.0.0.1:8123"}) == "http://127.0.0.1:8123"
        )
        assert github.api_base({"GITHUB_API_URL": "http://localhost:9"}) == "http://localhost:9"
        assert github.api_base({}) == "https://api.github.com"

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.test",
            "ftp://x",
            "https://u:p@example.test",
            "http://10.0.0.1:1",
            "file:///x",
            "https://",
            "https://x?y=1",
        ],
    )
    def test_anything_else_is_e_config_before_a_request(self, url: str, fake: FakeGitHub) -> None:
        with pytest.raises(IdentityError) as err:
            github.get_user("octocat", {"GITHUB_API_URL": url})
        assert err.value.code == E_CONFIG and fake.requests == []

    @pytest.mark.parametrize(
        "api",
        [
            None,
            "https://api.github.com",
            "https://ghe.example.test/api/v3",
            "http://127.0.0.1:8123",
            "http://127.0.0.1:8123/",
        ],
    )
    def test_the_web_base_rule_equals_the_spike_d_oracle(self, api: str | None) -> None:
        assert github.web_base(api or github.DEFAULT_API) == oracle_web_base(api)

    def test_the_keys_page_is_read_from_the_same_server_for_a_fake(self, fake: FakeGitHub) -> None:
        fake.public_world(auth_keys="keys-with.txt")
        assert github.get_auth_keys("octocat") == [KEY_B, KEY_A]
        assert fake.requests[0].path == "/octocat.keys"

    def test_redirects_are_not_followed(self, fake: FakeGitHub) -> None:
        fake.on(
            "GET", "/users/octocat", Reply(302, "", {"location": f"{fake.url}/users/elsewhere"})
        )
        with pytest.raises(GitHubError) as err:
            github.get_user("octocat")
        assert err.value.kind == "bad-response" and "redirect" in str(err.value)
        assert [r.path for r in fake.requests] == ["/users/octocat"]

    def test_loopback_bypasses_a_proxy(
        self, fake: FakeGitHub, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")  # a dead proxy
        fake.public_world()
        assert github.get_user("octocat").id == 583231


class TestCalls:
    def test_get_user_gives_the_id_and_the_canonical_login(self, fake: FakeGitHub) -> None:
        fake.public_world()
        assert github.get_user("octocat") == github.User("octocat", 583231)

    @pytest.mark.parametrize("name", ["user-org.json", "user-bot.json"])
    def test_an_organization_or_a_bot_is_not_a_user(self, fake: FakeGitHub, name: str) -> None:
        fake.public_world("someone", user=name)
        with pytest.raises(GitHubError) as err:
            github.get_user("someone")
        assert err.value.kind == "not-a-user"

    def test_signing_keys_are_type_blob_with_the_comment_stripped(self, fake: FakeGitHub) -> None:
        fake.public_world(signing_keys="signing-keys-comment.json")
        (key,) = github.get_signing_keys("octocat")
        assert key.blob == KEY_A and "fixture-a" not in key.blob and key.id == 1002

    def test_two_keys_keep_their_order_and_empty_is_empty(self, fake: FakeGitHub) -> None:
        fake.public_world(signing_keys="signing-keys-two.json")
        assert [k.blob for k in github.get_signing_keys("octocat")] == [KEY_B, KEY_A]
        fake.public_world(signing_keys="signing-keys-empty.json")
        assert github.get_signing_keys("octocat") == []

    def test_a_missing_title_is_fine_it_is_display_only(self, fake: FakeGitHub) -> None:
        body = json.dumps([{"id": 7, "key": KEY_A, "created_at": "2026-01-01T00:00:00Z"}])
        fake.on("GET", "/users/octocat/ssh_signing_keys", Reply(200, body))
        assert github.get_signing_keys("octocat")[0].title == ""

    def test_at_most_two_pages_of_100_are_read(self, fake: FakeGitHub) -> None:
        page = json.dumps([{"id": i, "key": KEY_B, "title": "t"} for i in range(100)])
        fake.on("GET", "/users/octocat/ssh_signing_keys", Reply(200, page))
        assert len(github.get_signing_keys("octocat")) == 200
        assert len(fake.requests) == 2
        assert fake.requests[0].path.endswith("per_page=100&page=1")

    def test_auth_keys_skip_blank_and_comment_free_lines(self, fake: FakeGitHub) -> None:
        fake.on(
            "GET", "/octocat.keys", Reply(200, f"\n{KEY_A} laptop\n\n", content_type="text/plain")
        )
        assert github.get_auth_keys("octocat") == [KEY_A]
        fake.public_world(auth_keys="keys-empty.txt")
        assert github.get_auth_keys("octocat") == []

    @pytest.mark.parametrize(
        ("name", "verified", "reason"),
        [("commit-verified.json", True, "valid"), ("commit-unsigned.json", False, "unsigned"),
         ("commit-unknown-key.json", False, "unknown_key")],
    )  # fmt: skip
    def test_commit_verification(
        self, fake: FakeGitHub, name: str, verified: bool, reason: str
    ) -> None:
        fake.commit_world("octocat/hello", "a1" * 20, name)
        got = github.get_commit_verification("octocat", "hello", "a1" * 20)
        assert got == github.Verification(verified, reason)

    @pytest.mark.parametrize(
        "login", ["", "-bad", "a" * 40, "a b", "a/b", "a?b", "../x", "é", "a\n"]
    )
    def test_a_login_is_validated_before_it_goes_into_a_url(
        self, fake: FakeGitHub, login: str
    ) -> None:
        for call in (github.get_user, github.get_signing_keys, github.get_auth_keys):
            with pytest.raises(ValueError):
                call(login)
        assert fake.requests == []

    @pytest.mark.parametrize(
        ("owner", "repo", "sha"),
        [("o/x", "r", "abcdef1"), ("o", "r r", "abcdef1"), ("o", "r", "xyz"), ("o", "r", "abc")],
    )
    def test_repository_and_sha_are_validated(
        self, fake: FakeGitHub, owner: str, repo: str, sha: str
    ) -> None:
        with pytest.raises(ValueError):
            github.get_commit_verification(owner, repo, sha)
        assert fake.requests == []


class TestFailures:
    def kind(self, fake: FakeGitHub, call=github.get_user) -> GitHubError:  # type: ignore[no-untyped-def]
        with pytest.raises(GitHubError) as err:
            call("octocat")
        return err.value

    def test_404_is_not_found(self, fake: FakeGitHub) -> None:
        fake.on("GET", "/users/octocat", Reply(404, fixture("err-404.json")))
        assert self.kind(fake).kind == "not-found"

    def test_rate_limit_names_the_reset_time_and_is_not_retried(self, fake: FakeGitHub) -> None:
        fake.on(
            "GET", "/users/octocat", Reply(403, fixture("err-403-rate.json"), dict(RATE_HEADERS))
        )
        err = self.kind(fake)
        assert err.kind == "rate-limit" and "resets at 2026-" in str(err)
        assert len(fake.requests) == 1
        fake.requests.clear()
        fake.on(
            "GET",
            "/users/octocat",
            Reply(429, fixture("err-403-secondary.json"), {"retry-after": "60"}),
        )
        assert self.kind(fake).kind == "rate-limit" and len(fake.requests) == 1

    def test_5xx_is_a_server_error(self, fake: FakeGitHub) -> None:
        fake.on("GET", "/users/octocat", Reply(502, fixture("err-5xx.json")))
        assert self.kind(fake).kind == "server"

    def test_truncated_json_and_wrong_types_are_bad_responses(self, fake: FakeGitHub) -> None:
        fake.on("GET", "/users/octocat", Reply(200, fixture("truncated.json")))
        assert self.kind(fake).kind == "bad-response"
        for body in (
            '"text"',
            "[]",
            '{"id": "7", "login": "x", "type": "User"}',
            '{"id": true, "login": "x", "type": "User"}',
            "{}",
        ):
            fake.on("GET", "/users/octocat", Reply(200, body))
            assert self.kind(fake).kind == "bad-response", body
        fake.on("GET", "/users/octocat/ssh_signing_keys", Reply(200, '[{"id": 1, "key": "nokey"}]'))
        assert self.kind(fake, github.get_signing_keys).kind == "bad-response"
        fake.on("GET", "/users/octocat/ssh_signing_keys", Reply(200, '{"not": "a list"}'))
        assert self.kind(fake, github.get_signing_keys).kind == "bad-response"

    def test_a_body_over_the_cap_is_refused(self, fake: FakeGitHub) -> None:
        fake.on("GET", "/users/octocat", Reply(200, '{"bio": "' + "x" * (2 * 1024 * 1024) + '"}'))
        err = self.kind(fake)
        assert err.kind == "bad-response" and "1 MiB" in str(err)

    def test_the_content_type_is_checked(self, fake: FakeGitHub) -> None:
        fake.on("GET", "/users/octocat", Reply(200, "{}", content_type="text/html"))
        assert self.kind(fake).kind == "bad-response"
        fake.on("GET", "/octocat.keys", Reply(200, KEY_A, content_type="application/json"))
        assert self.kind(fake, github.get_auth_keys).kind == "bad-response"

    def test_a_connection_failure_is_a_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        server = FakeGitHub().start()
        url = server.url
        server.stop()
        monkeypatch.setenv("GITHUB_API_URL", url)
        assert self.kind(server).kind == "network"

    def test_messages_are_one_short_line_and_never_echo_a_body(self, fake: FakeGitHub) -> None:
        secret = fine_grained("BODY")
        fake.on("GET", "/users/octocat", Reply(500, "x" * 5000 + secret))
        err = self.kind(fake)
        assert len(str(err)) <= 200 and secret not in str(err) and "\n" not in str(err)
        fake.on("GET", "/users/octocat", Reply(200, "{" + secret))
        assert secret not in str(self.kind(fake))
