"""The GitHub API shapes ``identity add`` / ``identity verify --remote`` rely on (plan 005, step 5).

Modelled from the public REST documentation (Users, SSH signing keys, Commits, Rate limits) read
on 2026-11-04; the web page ``/<login>.keys`` is not part of the REST API. Everything here runs
against the loopback fake: no network, no credentials. The real-service confirmation is step 33.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

import pytest

from gh_api import (
    FIXTURES,
    RATE_HEADERS,
    FakeGitHub,
    Reply,
    fixture,
    web_base,
)

KEY_A = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBQUck5VvSpXHhZ5JFCGxR3zhC07GvQUN5j6rv6VJbaY"
KEY_B = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFDQnea8LgFZ8D5U5LltihuJT5SwVYKxvc17OZNaCgaU"
BLOB = re.compile(r"^ssh-ed25519 [A-Za-z0-9+/]+={0,2}$")
JSON_FIXTURES = sorted(p.name for p in FIXTURES.glob("*.json") if p.name != "truncated.json")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def get(url: str) -> tuple[int, dict[str, str], str]:
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with opener.open(request, timeout=5) as resp:
            return (
                resp.status,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.read().decode(),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode()


@pytest.fixture
def fake() -> FakeGitHub:
    server = FakeGitHub().start()
    yield server  # type: ignore[misc]
    server.stop()


@pytest.mark.parametrize("name", JSON_FIXTURES)
def test_every_json_fixture_parses(name: str) -> None:
    assert json.loads(fixture(name)) is not None


def test_the_truncated_fixture_is_invalid_on_purpose() -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(fixture("truncated.json"))


@pytest.mark.parametrize(
    ("name", "kind"),
    [("user.json", "User"), ("user-org.json", "Organization"), ("user-bot.json", "Bot")],
)
def test_user_shape_carries_the_fields_identity_add_uses(name: str, kind: str) -> None:
    doc = json.loads(fixture(name))
    assert isinstance(doc["id"], int) and doc["login"] and doc["type"] == kind
    assert doc["id"] > 0  # the noreply address is <id>+<login>@users.noreply.github.com


def test_signing_keys_are_a_list_of_id_key_title_created_at() -> None:
    for name in ("signing-keys-match.json", "signing-keys-two.json", "signing-keys-nomatch.json"):
        for item in json.loads(fixture(name)):
            assert set(item) == {"id", "key", "title", "created_at"}
            assert BLOB.match(item["key"])
    assert json.loads(fixture("signing-keys-empty.json")) == []
    (with_comment,) = json.loads(fixture("signing-keys-comment.json"))
    assert with_comment["key"].startswith(KEY_A + " ")  # compare the first two tokens only


def test_auth_keys_page_is_one_key_per_line() -> None:
    assert fixture("keys-with.txt").split("\n")[:2] == [KEY_B, KEY_A]
    assert fixture("keys-without.txt").strip() == KEY_B
    assert fixture("keys-empty.txt").strip() == ""


@pytest.mark.parametrize(
    ("name", "verified", "reason", "signed"),
    [
        ("commit-verified.json", True, "valid", True),
        ("commit-unsigned.json", False, "unsigned", False),
        ("commit-unknown-key.json", False, "unknown_key", True),
    ],
)
def test_commit_verification_object(name: str, verified: bool, reason: str, signed: bool) -> None:
    verification = json.loads(fixture(name))["commit"]["verification"]
    assert set(verification) == {"verified", "reason", "signature", "payload", "verified_at"}
    assert (verification["verified"], verification["reason"]) == (verified, reason)
    assert (verification["signature"] is not None) is signed


def test_the_fake_serves_each_public_route_and_sends_no_credentials(fake: FakeGitHub) -> None:
    fake.public_world(signing_keys="signing-keys-two.json", auth_keys="keys-with.txt")
    fake.commit_world("octocat/hello", "a1" * 20)
    status, _, body = get(f"{fake.url}/users/octocat")
    assert status == 200 and json.loads(body)["type"] == "User"
    status, _, body = get(f"{fake.url}/users/octocat/ssh_signing_keys")
    assert status == 200 and [k["id"] for k in json.loads(body)] == [1004, 1005]
    status, headers, body = get(f"{fake.url}/octocat.keys")
    assert status == 200 and headers["content-type"].startswith("text/plain")
    assert KEY_A in body.splitlines()
    status, _, body = get(f"{fake.url}/repos/octocat/hello/commits/{'a1' * 20}")
    assert status == 200 and json.loads(body)["commit"]["verification"]["verified"] is True
    assert len(fake.requests) == 4
    assert fake.authorized_requests() == []  # unauthenticated by design
    assert fake.unexpected == []


def test_error_replies_match_the_documented_shapes(fake: FakeGitHub) -> None:
    fake.on("GET", "/users/ghost", Reply(404, fixture("err-404.json")))
    fake.on("GET", "/users/limited", Reply(403, fixture("err-403-rate.json"), dict(RATE_HEADERS)))
    fake.on(
        "GET",
        "/users/secondary",
        Reply(429, fixture("err-403-secondary.json"), {"retry-after": "60"}),
    )
    fake.on("GET", "/users/broken", Reply(502, fixture("err-5xx.json")))
    fake.on("GET", "/users/cut", Reply(200, fixture("truncated.json")))
    status, _, body = get(f"{fake.url}/users/ghost")
    assert status == 404 and json.loads(body)["message"] == "Not Found"
    status, headers, body = get(f"{fake.url}/users/limited")
    assert status == 403 and headers["x-ratelimit-remaining"] == "0"
    assert "rate limit" in json.loads(body)["message"]
    status, headers, _ = get(f"{fake.url}/users/secondary")
    assert status == 429 and headers["retry-after"] == "60"
    assert get(f"{fake.url}/users/broken")[0] == 502
    status, _, body = get(f"{fake.url}/users/cut")
    assert status == 200
    with pytest.raises(json.JSONDecodeError):
        json.loads(body)


def test_a_huge_body_is_served_so_the_client_size_cap_can_be_tested(fake: FakeGitHub) -> None:
    fake.on("GET", "/users/huge", Reply(200, '{"bio": "' + "x" * (2 * 1024 * 1024) + '"}'))
    status, _, body = get(f"{fake.url}/users/huge")
    assert status == 200 and len(body) > 2 * 1024 * 1024


def test_redirects_are_not_followed(fake: FakeGitHub) -> None:
    fake.on("GET", "/users/moved", Reply(301, "", {"location": "https://elsewhere.invalid/x"}))
    assert get(f"{fake.url}/users/moved")[0] == 301  # as in ghtoken: nothing leaves the host


@pytest.mark.parametrize(
    ("api", "web"),
    [
        (None, "https://github.com"),
        ("https://api.github.com", "https://github.com"),
        ("https://api.github.com/", "https://github.com"),
        ("https://ghe.example.test/api/v3", "https://ghe.example.test"),
        ("http://127.0.0.1:8123", "http://127.0.0.1:8123"),
        ("http://127.0.0.1:8123/", "http://127.0.0.1:8123"),
    ],
)
def test_the_web_base_rule(api: str | None, web: str) -> None:
    assert web_base(api) == web


def test_the_web_base_rule_reaches_the_keys_page_on_the_fake(fake: FakeGitHub) -> None:
    fake.public_world(auth_keys="keys-with.txt")
    base = web_base(fake.url)
    assert base == fake.url
    assert KEY_B in get(f"{base}/octocat.keys")[2]
