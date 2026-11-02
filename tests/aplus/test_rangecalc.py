"""The range ``carter push`` shows and the signature check walks (RFC-0007 C.6.6; plan 003
step 18): ``origin/<branch>`` if it exists, else ``merge-base(origin/HEAD, HEAD)``."""

from __future__ import annotations

from pathlib import Path

import pytest

from aplus.helpers import commit_file, git, make_repo
from carter.aplus import rangecalc as rc
from carter.identity import IdentityError
from carter.identity.errors import E_APLUS_ARGS


def sha(repo: Path, ref: str = "HEAD") -> str:
    return git("rev-parse", ref, cwd=repo).stdout.strip()


class TestBase:
    def test_origin_branch_is_the_base_when_it_exists(self, with_origin: Path) -> None:
        a = commit_file(with_origin, "a.txt")
        b = commit_file(with_origin, "b.txt")
        info = rc.compute_range(with_origin)
        assert info.branch == "main" and info.base == sha(with_origin, "origin/main")
        assert info.base_ref == "origin/main" and info.base_label == "as of origin/main"
        assert info.commits == (a, b) and not info.new_branch and info.fast_forward

    def test_a_new_branch_uses_the_merge_base_with_origin_head(self, with_origin: Path) -> None:
        git("checkout", "-q", "-b", "feat/x", cwd=with_origin)
        c = commit_file(with_origin, "x.txt")
        info = rc.compute_range(with_origin)
        assert info.new_branch and info.base == sha(with_origin, "origin/main")
        assert info.base_ref == "merge-base(origin/HEAD, HEAD)"
        assert info.base_label == "as of merge-base(origin/HEAD, HEAD)"
        assert info.commits == (c,) and info.branch == "feat/x"

    def test_a_new_branch_off_an_older_main_commit(self, with_origin: Path) -> None:
        git("checkout", "-q", "-b", "feat/old", cwd=with_origin)
        commit_file(with_origin, "o.txt")
        git("checkout", "-q", "main", cwd=with_origin)
        commit_file(with_origin, "m.txt")
        git("push", "-q", "origin", "main", cwd=with_origin)
        git("checkout", "-q", "feat/old", cwd=with_origin)
        info = rc.compute_range(with_origin)
        assert info.base == git("merge-base", "origin/HEAD", "HEAD", cwd=with_origin).stdout.strip()
        assert len(info.commits) == 1

    def test_upstream_tracking_is_ignored_in_a_fork_flow(
        self, with_origin: Path, tmp_path: Path
    ) -> None:
        upstream = tmp_path / "upstream.git"
        git("init", "-q", "--bare", "-b", "main", str(upstream))
        git("remote", "add", "upstream", f"file://{upstream}", cwd=with_origin)
        git("push", "-q", "upstream", "main", cwd=with_origin)
        other = make_repo(tmp_path / "other")
        git("remote", "add", "origin", f"file://{upstream}", cwd=other)
        git("fetch", "-q", "origin", cwd=other)
        git("checkout", "-q", "-B", "main", "origin/main", cwd=other)
        commit_file(other, "up.txt")
        git("push", "-q", "origin", "main", cwd=other)
        git("fetch", "-q", "upstream", cwd=with_origin)
        git("checkout", "-q", "-b", "feat/fork", "--track", "upstream/main", cwd=with_origin)
        c = commit_file(with_origin, "mine.txt")
        assert (
            git("rev-parse", "--abbrev-ref", "@{u}", cwd=with_origin).stdout.strip()
            == "upstream/main"
        )
        info = rc.compute_range(with_origin)
        assert info.base == git("merge-base", "origin/HEAD", "HEAD", cwd=with_origin).stdout.strip()
        # @{u} would have made upstream/main the base; the commits that origin lacks are shown
        assert info.base != sha(with_origin, "upstream/main") and c in info.commits

    def test_the_source_never_uses_the_upstream_shortcut(self) -> None:
        assert "@{u" not in Path(rc.__file__).read_text(encoding="utf-8")

    def test_nothing_to_push_is_an_empty_range(self, with_origin: Path) -> None:
        info = rc.compute_range(with_origin)
        assert info.commits == () and info.changes == () and info.sensitive == ()

    def test_a_diverged_branch_is_not_fast_forward(self, with_origin: Path, tmp_path: Path) -> None:
        clone = tmp_path / "clone"
        git("clone", "-q", f"file://{tmp_path / 'origin.git'}", str(clone))
        commit_file(clone, "theirs.txt")
        git("push", "-q", "origin", "main", cwd=clone)
        commit_file(with_origin, "mine.txt")
        git("fetch", "-q", "origin", cwd=with_origin)
        info = rc.compute_range(with_origin)
        assert info.fast_forward is False and len(info.commits) == 1

    def test_commits_are_oldest_first(self, with_origin: Path) -> None:
        shas = [commit_file(with_origin, f"f{i}.txt") for i in range(4)]
        assert list(rc.compute_range(with_origin).commits) == shas


class TestRefused:
    def test_detached_head_is_e_aplus_args(self, with_origin: Path) -> None:
        git("checkout", "-q", "--detach", cwd=with_origin)
        with pytest.raises(IdentityError) as exc:
            rc.compute_range(with_origin)
        assert exc.value.code == E_APLUS_ARGS and "detached" in exc.value.detail

    def test_no_origin_remote(self, repo: Path) -> None:
        with pytest.raises(IdentityError) as exc:
            rc.compute_range(repo)
        assert exc.value.code == E_APLUS_ARGS and "origin" in exc.value.detail

    def test_new_branch_without_origin_head_cannot_pick_a_base(self, with_origin: Path) -> None:
        git("remote", "set-head", "origin", "-d", cwd=with_origin)
        git("checkout", "-q", "-b", "feat/y", cwd=with_origin)
        commit_file(with_origin, "y.txt")
        with pytest.raises(IdentityError) as exc:
            rc.compute_range(with_origin)
        assert "origin/HEAD" in exc.value.detail

    def test_a_missing_origin_head_is_fine_when_origin_branch_exists(
        self, with_origin: Path
    ) -> None:
        git("remote", "set-head", "origin", "-d", cwd=with_origin)
        commit_file(with_origin, "z.txt")
        assert len(rc.compute_range(with_origin).commits) == 1

    def test_not_a_repository(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(IdentityError) as exc:
            rc.compute_range(plain)
        assert exc.value.code == E_APLUS_ARGS


class TestSensitivePaths:
    def changed(self, repo: Path) -> dict[str, str]:
        return {c.path: c.status for c in rc.compute_range(repo).sensitive}

    @pytest.mark.parametrize(
        "path",
        [
            ".husky/pre-push", ".githooks/pre-commit", ".pre-commit-config.yaml", "lefthook.yml",
            "lefthook.json", ".lefthook.yml", ".github/workflows/ci.yml", "packages/a/.husky/h",
            "services/api/.pre-commit-config.yaml", "tools/lefthook.toml",
        ],
    )  # fmt: skip
    def test_each_listed_location_is_reported(self, with_origin: Path, path: str) -> None:
        commit_file(with_origin, path)
        assert self.changed(with_origin) == {path: "A"}

    def test_ordinary_files_are_not(self, with_origin: Path) -> None:
        for path in (
            "src/app.py",
            "docs/husky.md",
            ".github/CODEOWNERS",
            "my.githooks.txt",
            "lefthooks.md",
        ):
            commit_file(with_origin, path)
        info = rc.compute_range(with_origin)
        assert info.sensitive == () and len(info.changes) == 5

    def test_the_core_hooks_path_target_is_added(self, with_origin: Path) -> None:
        git("config", "--local", "core.hooksPath", "tools/hooks", cwd=with_origin)
        commit_file(with_origin, "tools/hooks/pre-push")
        commit_file(with_origin, "tools/other/x")
        assert self.changed(with_origin) == {"tools/hooks/pre-push": "A"}

    def test_deletions_are_counted(self, with_origin: Path) -> None:
        commit_file(with_origin, ".github/workflows/old.yml")
        git("push", "-q", "origin", "main", cwd=with_origin)
        git("rm", "-q", ".github/workflows/old.yml", cwd=with_origin)
        git("commit", "-q", "-m", "drop", cwd=with_origin)
        assert self.changed(with_origin) == {".github/workflows/old.yml": "D"}

    def test_a_rename_into_a_sensitive_location_is_counted_with_both_paths(
        self, with_origin: Path
    ) -> None:
        commit_file(
            with_origin,
            "scripts/hook.sh",
            "#!/bin/sh\necho a long enough body for rename detection\n" * 5,
        )
        git("push", "-q", "origin", "main", cwd=with_origin)
        (with_origin / ".husky").mkdir()
        git("mv", "scripts/hook.sh", ".husky/pre-push", cwd=with_origin)
        git("commit", "-q", "-m", "mv", cwd=with_origin)
        (change,) = rc.compute_range(with_origin).sensitive
        assert (change.status, change.path, change.old_path) == (
            "R",
            ".husky/pre-push",
            "scripts/hook.sh",
        )

    def test_a_rename_out_of_a_sensitive_location_is_counted_too(self, with_origin: Path) -> None:
        commit_file(
            with_origin,
            ".githooks/pre-push",
            "#!/bin/sh\necho a long enough body for rename detection\n" * 5,
        )
        git("push", "-q", "origin", "main", cwd=with_origin)
        git("mv", ".githooks/pre-push", "scripts_pre-push", cwd=with_origin)
        git("commit", "-q", "-m", "mv", cwd=with_origin)
        (change,) = rc.compute_range(with_origin).sensitive
        assert (change.status, change.old_path) == ("R", ".githooks/pre-push")

    def test_odd_file_names_survive(self, with_origin: Path) -> None:
        commit_file(with_origin, ".husky/pre push é.sh")
        commit_file(with_origin, "dir/new\nline.txt")
        info = rc.compute_range(with_origin)
        assert [c.path for c in info.sensitive] == [".husky/pre push é.sh"]
        assert "dir/new\nline.txt" in [c.path for c in info.changes]

    def test_sensitive_paths_pure_helper(self) -> None:
        changes = (
            rc.Change("A", ".husky/x"),
            rc.Change("M", "src/a.py"),
            rc.Change("D", "lefthook.yml"),
        )
        assert [c.path for c in rc.sensitive_paths(changes)] == [".husky/x", "lefthook.yml"]
        assert [c.path for c in rc.sensitive_paths(changes, hooks_path="src")] == [
            ".husky/x",
            "src/a.py",
            "lefthook.yml",
        ]
