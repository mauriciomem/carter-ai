# ruff: noqa: E501, F811
"""``carter check --host`` for role b (plan 006 step 11; freeze K3, K7, K8, K12)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from carter import hostcheck_id
from carter.checkitems import Item
from carter.guard import hooks
from carter.identity import coauthor
from carter.identity.config import load_identity
from carter.identity.schema import Workspace
from carter.identity.writer import write_config
from gh_api import FakeGitHub, Reply
from guard.test_hostcheck_2b import fake, find, home, key, levels, make, run  # noqa: F401 - fixtures
from ssh_rig import KeyPair

HUMAN = ("Hu Man", "human@example.invalid")


def git_user(name: str, email: str) -> None:
    lines = (
        ["[user]"]
        + ([f"\tname = {name}"] if name else [])
        + ([f"\temail = {email}"] if email else [])
    )
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text("\n".join(lines) + "\n")


def set_role(home: Path, role: str, **ws: Workspace) -> None:
    cfg = load_identity()
    write_config(
        replace(
            cfg, identity=replace(cfg.identity, role=role), workspaces=dict(ws) or cfg.workspaces
        ),
        home / ".carter" / "config.toml",
    )


@pytest.fixture(autouse=True)
def human() -> None:
    git_user(*HUMAN)


class TestRoleItems:
    def test_role_author_at_t2_checks_the_humans_identity_and_the_link_from_the_cache_only(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        set_role(home, "author")
        fake.requests.clear()
        items = run(tmp_path)  # no reader: nothing leaves the machine
        assert find(items, "human identity", "usable").level == "ok"  # type: ignore[union-attr]
        link = find(items, "co-author link")
        assert link and link.level == "warn" and "only credit" in link.text
        assert all(HUMAN[1] not in i.text and HUMAN[0] not in i.text for i in items)
        assert fake.requests == []

    def test_a_cached_link_is_ok(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        set_role(home, "author")
        coauthor.record_link(HUMAN[1], "verified", home)
        assert find(run(tmp_path), "co-author link").level == "ok"  # type: ignore[union-attr]

    def test_a_live_run_looks_the_noreply_address_up_and_caches_it(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        git_user("Hu Man", "999+humanlogin@users.noreply.github.com")
        make(fake, key)
        fake.on(
            "GET",
            "/users/humanlogin",
            Reply(200, json.dumps({"login": "humanlogin", "id": 999, "type": "User"})),
        )
        set_role(home, "author")
        items = run(tmp_path, fetch=hostcheck_id.live_fetch)
        assert find(items, "co-author link", "noreply").level == "ok"  # type: ignore[union-attr]
        assert coauthor.cached_link("999+humanlogin@users.noreply.github.com", home) == "noreply"
        assert fake.authorized_requests() == []

    def test_a_live_run_in_an_agent_shell_does_not_ask_or_write(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        git_user("Hu Man", "999+humanlogin@users.noreply.github.com")
        make(fake, key)
        set_role(home, "author")
        monkeypatch.setenv("CARTER_AGENT_SHELL", "1")
        fake.requests.clear()
        items = run(tmp_path, fetch=lambda login: hostcheck_id.KeyLists(None, None))
        assert find(items, "co-author link").level == "warn"  # type: ignore[union-attr]
        assert not coauthor.cache_path(home).exists()
        assert not [r for r in fake.requests if r.path == "/users/humanlogin"]

    @pytest.mark.parametrize(
        ("name", "email", "problem"),
        [
            ("", "", "missing-name"),
            ("Hu Man", "", "missing-email"),
            ("Carter", "state@carter.invalid", "fallback"),
        ],
    )
    def test_an_unusable_identity_is_red_with_the_code_and_the_token(
        self,
        home: Path,
        fake: FakeGitHub,
        key: KeyPair,
        tmp_path: Path,
        name: str,
        email: str,
        problem: str,
    ) -> None:
        make(fake, key)
        set_role(home, "author")
        git_user(name, email)
        item = find(run(tmp_path), "human identity")
        assert (
            item
            and item.level == "red"
            and "E-HUMAN-IDENTITY" in item.text
            and problem in item.text
        )

    @pytest.mark.parametrize(
        ("name", "email"),
        [("Carter", "carter@example.invalid"), ("Hu Man", "state@carter.invalid")],
    )
    def test_a_person_named_carter_is_not_flagged(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path, name: str, email: str
    ) -> None:
        make(fake, key)
        set_role(home, "author")
        git_user(name, email)
        assert find(run(tmp_path), "human identity", "usable").level == "ok"  # type: ignore[union-attr]

    def test_role_a_has_none_of_these_items(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        areas = {i.area for i in run(tmp_path)}
        assert not areas & {"human identity", "co-author link", "dco", "role"}

    def test_role_author_below_t2_is_red_never_a_downgrade(
        self, home: Path, fake: FakeGitHub, tmp_path: Path
    ) -> None:
        from carter import identity_add

        identity_add.apply_add(identity_add.plan_add(identity_add.AddRequest("octocat")))
        set_role(home, "author")
        item = find(run(tmp_path), "role", "needs T2")
        assert (
            item
            and item.level == "red"
            and "E-ROLE-B-TIER" in item.text
            and "configured tier is t1" in item.text
        )

    def test_role_author_with_a_cap_is_red_and_says_cap(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        ws = tmp_path / "ws"
        ws.mkdir()
        import subprocess

        subprocess.run(["git", "init", "-q", str(ws)], check=True)
        set_role(home, "author", **{str(ws.resolve()): Workspace(max_tier="t1")})
        item = find(run(ws), "role", "needs T2")
        assert item and item.level == "red" and "workspace cap" in item.text

    def test_a_precedence_conflict_is_a_warning(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        ws = tmp_path / "ws"
        ws.mkdir()
        set_role(home, "author", **{str(ws.resolve()): Workspace(role="co-author")})
        item = find(run(ws), "role", "workspace pin wins")
        assert item and item.level == "warn"

    @pytest.mark.parametrize("name", [".github/dco.yml", ".github/dco.yaml", ".dco.yml", "DCO"])
    def test_a_dco_file_in_the_repository_is_a_warning_for_role_b_only(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path, name: str
    ) -> None:
        make(fake, key)
        repo = tmp_path / "repo"
        (repo / "sub").mkdir(parents=True)
        (repo / ".git").mkdir()
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n")
        assert find(run(repo / "sub"), "dco") is None  # role a: not for DCO to worry about here
        set_role(home, "author")
        item = find(run(repo / "sub"), "dco")
        assert item and item.level == "warn" and name in item.text and "sign-off" in item.text

    def test_a_dco_file_above_the_repository_root_is_not_looked_at(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        set_role(home, "author")
        (tmp_path / "DCO").write_text("x\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        assert find(run(repo), "dco") is None

    def test_a_guard_script_from_an_older_carter_is_red_for_role_b(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        make(fake, key)
        set_role(home, "author")
        script = hooks.script_path(None)
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(hooks.render_script().replace("2.1.0", "2.0.0") + "\n# old\n")
        item = find(run(tmp_path), "guards", "older Carter")
        assert item and item.level == "red" and "guard install" in item.fix
        script.write_text(hooks.render_script())
        assert find(run(tmp_path), "guards", "older Carter") is None

    def test_the_command_is_names_only_and_exits_1_on_a_red_role_item(
        self, home: Path, fake: FakeGitHub, key: KeyPair, tmp_path: Path
    ) -> None:
        from click.testing import CliRunner

        from carter.cli import main

        make(fake, key)
        set_role(home, "author")
        git_user("", "")
        done = CliRunner().invoke(main, ["check", "--host", str(tmp_path)], catch_exceptions=False)
        assert done.exit_code == 1 and "RED   human identity: E-HUMAN-IDENTITY" in done.output
        assert HUMAN[1] not in done.output


def test_levels_helper_is_the_2b_one() -> None:
    assert levels([Item("ok", "a", "x")], "a") == ["ok"] and json.dumps([]) == "[]"
