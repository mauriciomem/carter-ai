# ruff: noqa: E501
"""The real ``identity env`` entry and the plugin core together, no OpenCode.

Python writes the answer, node (``tests/plugin/roundtrip.mjs``) applies it the way the plugin does
(isolation entries, then the signing block on top), and real git runs with the resulting env:
T2 valid -> a K1 commit; every failure -> no commit; below T2 -> unsigned and no committer env.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from carter.identity import shim
from carter.identity.payload import shim_path
from guard.test_carter_guard_commit_events import EMAIL, LOGIN, World
from ssh_rig import KeyPair, real_ssh

REPO = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
BASE = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "GIT_AUTHOR_NAME": "Hu Man",
    "GIT_AUTHOR_EMAIL": "human@example.invalid",
}


def entry(world: World, cwd: Path, **env: str) -> str:
    done = subprocess.run(
        [sys.executable, "-I", "-m", "carter.identity.env", "--json", "--cwd", str(cwd)],
        env={**os.environ, "HOME": str(world.home), "PYTHONPATH": str(REPO), **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def plugin(answer: str, tmp: Path) -> dict:
    path = tmp / "answer.json"
    path.write_text(answer)
    done = subprocess.run(
        [
            NODE or "node",
            str(REPO / "tests" / "plugin" / "roundtrip.mjs"),
            str(path),
            json.dumps(BASE),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def commit(world: World, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    repo = world.repo
    # isolation deletes the identity variables: below T2 the human's own git config names the author
    (world.home / ".gitconfig").write_text(
        "[user]\n\tname = Hu Man\n\temail = human@example.invalid\n"
    )
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "-q"], cwd=repo, env={**BASE, "HOME": str(world.home)}, check=True
        )
    (repo / "f").write_text("x\n")
    subprocess.run(["git", "add", "f"], cwd=repo, env={**BASE, "HOME": str(world.home)}, check=True)
    return subprocess.run(
        ["git", "commit", "-q", "-m", "agent"],
        cwd=repo,
        env={**env, "HOME": str(world.home)},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def world(tmp_path: Path, throwaway_key: Callable[..., KeyPair], real_ssh_agent) -> World:  # type: ignore[no-untyped-def]
    key = throwaway_key("ed25519")
    assert real_ssh_agent.add(key) == 0
    w = World(Path(os.environ["HOME"]), tmp_path / "repo", key, str(real_ssh_agent.sock))
    w.configure("t2")
    return w


def log(world: World) -> str:
    allowed = shim.allowed_signers_path(world.home)
    done = subprocess.run(
        [
            "git",
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.allowedSignersFile={allowed}",
            "-c",
            f"gpg.ssh.program={shim_path(world.home)}",
            "log",
            "-1",
            "--format=%G?|%GF|%an|%ce",
        ],
        cwd=world.repo,
        env={**BASE, "HOME": str(world.home)},
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@real_ssh
class TestValidT2:
    def test_the_block_goes_after_the_isolation_entries_and_the_commit_is_k1(
        self, world: World
    ) -> None:
        out = plugin(entry(world, world.repo), world.repo.parent)
        assert out["decision"]["block"] is False and out["decision"]["reason"] is None
        env = out["env"]
        assert env["GIT_COMMITTER_EMAIL"] == EMAIL and env["CARTER_IDENTITY"]
        pairs = [
            (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        ]
        keys = [k for k, _ in pairs]
        # isolation first (gpgsign false + the four programs false), the signing block after: the later entries win
        assert (
            keys.index("commit.gpgsign") < len(keys) - 1
            and pairs[-1][0] == "commit.gpgsign"
            and pairs[-1][1] == "true"
        )
        assert dict(pairs)["gpg.ssh.program"] == str(shim_path(world.home))
        assert {
            dict(pairs)[k] for k in ("gpg.program", "gpg.openpgp.program", "gpg.x509.program")
        } <= {"/usr/bin/false", "/bin/false"}
        done = commit(world, env)
        assert done.returncode == 0, done.stderr
        assert log(world) == f"G|{world.key.fingerprint}|Hu Man|{EMAIL}"  # type: ignore[union-attr]


@real_ssh
class TestEveryFailureBlocks:
    def blocked(self, world: World) -> None:
        out = plugin(entry(world, world.repo), world.repo.parent)
        assert out["decision"]["block"] is True and out["decision"]["signing"] is None
        assert "GIT_COMMITTER_EMAIL" not in out["env"] and "CARTER_IDENTITY" not in out["env"]
        done = commit(world, out["env"])
        assert done.returncode != 0
        assert subprocess.run(
            ["git", "rev-list", "--count", "--all"],
            cwd=world.repo,
            env={**BASE, "HOME": str(world.home)},
            capture_output=True,
            text=True,
        ).stdout.strip() in ("0", "")
        assert (
            "A  f"
            in subprocess.run(
                ["git", "status", "--short"],
                cwd=world.repo,
                env={**BASE, "HOME": str(world.home)},
                capture_output=True,
                text=True,
            ).stdout
        )

    def test_the_shim_changed_since_it_was_recorded(self, world: World) -> None:
        shim_path(world.home).write_text(shim_path(world.home).read_text() + "# edited\n")
        assert json.loads(entry(world, world.repo))["reason"] == "shim-missing"
        self.blocked(world)

    def test_the_shim_is_gone(self, world: World) -> None:
        shim_path(world.home).unlink()
        self.blocked(world)

    def test_a_broken_config(self, world: World) -> None:
        (world.home / ".carter" / "config.toml").write_text("schema = 2\n[identity\nbroken")
        assert json.loads(entry(world, world.repo))["reason"] == "config-error"
        self.blocked(world)

    def test_a_fingerprint_that_is_not_the_keys(self, world: World) -> None:
        cfg = world.home / ".carter" / "config.toml"
        cfg.write_text(cfg.read_text().replace(world.key.fingerprint, "SHA256:" + "A" * 43))  # type: ignore[union-attr]
        assert json.loads(entry(world, world.repo))["reason"] == "fingerprint-mismatch"
        self.blocked(world)

    def test_an_unmet_require_tier(self, world: World) -> None:
        cfg = world.home / ".carter" / "config.toml"
        ws = str(world.repo.parent.resolve())
        cfg.write_text(
            cfg.read_text() + f'\n[workspaces."{ws}"]\nmax_tier = "t1"\nrequire_tier = "t2"\n'
        )
        assert json.loads(entry(world, world.repo))["reason"] == "tier-required"
        self.blocked(world)


@real_ssh
class TestBelowT2:
    @pytest.mark.parametrize("how", ["cap", "t1", "t0"])
    def test_unsigned_human_human_and_no_committer_env(self, world: World, how: str) -> None:
        cfg = world.home / ".carter" / "config.toml"
        if how == "cap":
            ws = str(world.repo.parent.resolve())
            cfg.write_text(cfg.read_text() + f'\n[workspaces."{ws}"]\nmax_tier = "t1"\n')
        elif how == "t1":
            world.configure("t1")
        else:
            world.configure("t0")
            cfg.unlink()
        out = plugin(entry(world, world.repo), world.repo.parent)
        assert out["decision"] == {"block": False, "flags": [], "signing": None, "reason": None}
        assert "GIT_COMMITTER_EMAIL" not in out["env"] and "CARTER_IDENTITY" not in out["env"]
        done = commit(world, out["env"])
        assert done.returncode == 0, done.stderr
        raw = subprocess.run(
            ["git", "cat-file", "commit", "HEAD"],
            cwd=world.repo,
            env={**BASE, "HOME": str(world.home)},
            capture_output=True,
            text=True,
        ).stdout
        assert "gpgsig" not in raw

    def test_bare_dash_capital_s_and_tag_s_fail_and_create_nothing_below_t2(
        self, world: World
    ) -> None:
        world.configure("t1")
        out = plugin(entry(world, world.repo), world.repo.parent)
        assert commit(world, out["env"]).returncode == 0
        for argv in (
            ["commit", "-q", "-S", "--allow-empty", "-m", "s"],
            ["tag", "-s", "t1", "-m", "s"],
        ):
            done = subprocess.run(
                ["git", *argv],
                cwd=world.repo,
                env={**out["env"], "HOME": str(world.home)},
                capture_output=True,
                text=True,
            )
            assert done.returncode != 0, argv
        assert (
            subprocess.run(
                ["git", "tag"],
                cwd=world.repo,
                env={**BASE, "HOME": str(world.home)},
                capture_output=True,
                text=True,
            ).stdout
            == ""
        )


def pin_role_author(world: World) -> None:
    cfg = world.home / ".carter" / "config.toml"
    text = cfg.read_text()
    cfg.write_text(
        text.replace('role = "co-author"', 'role = "author"')
        if 'role = "co-author"' in text
        else text.replace("[identity]\n", '[identity]\nrole = "author"\n', 1)
    )


@real_ssh
class TestRoleB:
    """the real entry, the plugin core and real git, role ``author``."""

    def test_with_a_human_identity_the_commit_is_l_l_g_and_the_human_is_not_in_the_block(
        self, world: World
    ) -> None:
        pin_role_author(world)
        answer = entry(world, world.repo)
        assert "human@example.invalid" not in answer
        out = plugin(answer, world.repo.parent)
        assert out["decision"]["block"] is False and out["decision"]["reason"] is None
        env = out["env"]
        assert env["GIT_AUTHOR_EMAIL"] == EMAIL == env["GIT_COMMITTER_EMAIL"]
        done = commit(world, env)
        assert done.returncode == 0, done.stderr
        assert log(world) == f"G|{world.key.fingerprint}|{LOGIN}|{EMAIL}"  # type: ignore[union-attr]
        authors = subprocess.run(
            ["git", "log", "-1", "--format=%an|%ae"], cwd=world.repo,
            env={**BASE, "HOME": str(world.home)}, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
        assert authors == f"{LOGIN}|{EMAIL}"

    @pytest.mark.parametrize(
        "config",
        [
            "",
            "[user]\n\tname = Hu Man\n",
            "[user]\n\tname = Carter\n\temail = state@carter.invalid\n",
        ],
    )
    def test_without_a_usable_human_identity_nothing_is_signed_and_nothing_is_committed(
        self, world: World, tmp_path: Path, config: str
    ) -> None:
        pin_role_author(world)
        empty = tmp_path / "gitconfig-empty"
        empty.write_text(config)
        answer = entry(world, world.repo, GIT_CONFIG_GLOBAL=str(empty))
        assert json.loads(answer)["reason"] == "human-identity-invalid"
        out = plugin(answer, world.repo.parent)
        assert out["decision"]["block"] is True and out["decision"]["signing"] is None
        assert (
            "GIT_AUTHOR_EMAIL" not in out["env"]
            or out["env"]["GIT_AUTHOR_EMAIL"] == BASE["GIT_AUTHOR_EMAIL"]
        )
        done = commit(world, out["env"])
        assert done.returncode != 0
        count = subprocess.run(
            ["git", "rev-list", "--count", "--all"], cwd=world.repo,
            env={**BASE, "HOME": str(world.home)}, capture_output=True, text=True,
        ).stdout.strip()  # fmt: skip
        assert count in ("0", "")

    def test_role_b_below_t2_or_under_a_cap_is_refused_never_a_role_a_block(
        self, world: World
    ) -> None:
        pin_role_author(world)
        cfg = world.home / ".carter" / "config.toml"
        ws = str(world.repo.parent.resolve())
        cfg.write_text(cfg.read_text() + f'\n[workspaces."{ws}"]\nmax_tier = "t1"\n')
        answer = entry(world, world.repo)
        assert json.loads(answer)["reason"] == "tier-required"
        out = plugin(answer, world.repo.parent)
        assert out["decision"]["block"] is True and "GIT_COMMITTER_EMAIL" not in out["env"]
