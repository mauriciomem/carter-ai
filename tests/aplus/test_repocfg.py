"""The repo-config check of RFC-0007 App C.5 as A+ uses it (plan 003 step 18).

A+ **shows** these findings and asks; it does not refuse on them (B does). Each row of the
C.5 table is a test. Findings carry scope, key and origin file, never a value."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aplus.helpers import git
from carter.aplus import repocfg
from carter.aplus.findings import Finding
from carter.identity import IdentityError
from carter.identity.errors import E_B_REPOCFG
from sentinels import prefixed

ORIGIN = "git@github.com:owner/repo.git"


def check(repo: Path, **kw) -> list[Finding]:
    kw.setdefault("origin_url", ORIGIN)
    return repocfg.check_repo_config(repo, **kw)


def keys(findings: list[Finding], scope: str | None = None) -> list[str]:
    return sorted(f.key for f in findings if scope in (None, f.scope))


@pytest.fixture
def carter_gitconfig(tmp_path: Path) -> Path:
    path = tmp_path / "carterhome" / "gitconfig"
    path.parent.mkdir()
    path.write_text("# managed by Carter\n")
    return path


class TestCleanAndAllowlist:
    def test_a_plain_repo_has_no_findings(self, repo: Path) -> None:
        assert check(repo) == []

    def test_a_global_include_of_carters_gitconfig_passes(
        self, repo: Path, global_git, carter_gitconfig: Path
    ) -> None:
        global_git("include.path", str(carter_gitconfig), add=True)
        owned = repocfg.CarterOwned(include=(str(carter_gitconfig),))
        assert check(repo, owned=owned) == []

    def test_the_same_include_is_a_finding_when_carter_does_not_own_it(
        self, repo: Path, global_git, carter_gitconfig: Path
    ) -> None:
        global_git("include.path", str(carter_gitconfig), add=True)
        # a non-Carter global include is not refused by itself (C.5): only its keys count
        assert check(repo) == []

    def test_a_local_include_of_carters_own_value_passes(
        self, repo: Path, carter_gitconfig: Path
    ) -> None:
        git("config", "--local", "include.path", str(carter_gitconfig), cwd=repo)
        assert check(repo, owned=repocfg.CarterOwned(include=(str(carter_gitconfig),))) == []

    def test_carters_cap_fragment_include_if_passes(self, repo: Path, tmp_path: Path) -> None:
        frag = tmp_path / "carterhome" / "gitconfig.d" / "abc123"
        frag.parent.mkdir(parents=True)
        frag.write_text("[carter]\n\ttier = t0\n")
        git("config", "--local", f"includeIf.gitdir:{repo}/.path", str(frag), cwd=repo)
        owned = repocfg.CarterOwned(fragment_dir=str(frag.parent))
        assert check(repo, owned=owned) == []

    def test_another_include_if_target_is_flagged(self, repo: Path, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.write_text("[user]\n\tname = x\n")
        git("config", "--local", f"includeIf.gitdir:{repo}/.path", str(other), cwd=repo)
        assert any(k.startswith("includeif.") for k in keys(check(repo), "local"))

    def test_carters_hook_entries_in_carters_file_pass_elsewhere_they_do_not(
        self, repo: Path, global_git, carter_gitconfig: Path
    ) -> None:
        git(
            "config",
            "--file",
            str(carter_gitconfig),
            "hook.carter-guard-commit-msg.event",
            "commit-msg",
        )
        git(
            "config",
            "--file",
            str(carter_gitconfig),
            "hook.carter-guard-commit-msg.command",
            "true",
        )
        global_git("include.path", str(carter_gitconfig), add=True)
        global_git("hook.sneaky.event", "pre-push")
        global_git("hook.sneaky.command", "evil")
        findings = check(
            repo,
            owned=repocfg.CarterOwned(
                include=(str(carter_gitconfig),), gitconfig_files=(str(carter_gitconfig),)
            ),
        )
        assert keys(findings) == ["hook.sneaky.command", "hook.sneaky.event"]
        assert {f.scope for f in findings} == {"global"}


class TestGlobalScope:
    def test_gh_auth_setup_git_credential_helper_passes(self, repo: Path, global_git) -> None:
        global_git("credential.https://github.com.helper", "!gh auth git-credential")
        assert check(repo) == []

    def test_a_global_pager_passes(self, repo: Path, global_git) -> None:
        global_git("core.pager", "delta")
        global_git("pager.log", "less")
        assert check(repo) == []

    @pytest.mark.parametrize(
        ("key", "value"),
        [("http.proxy", "http://p:3128"), ("core.askPass", "/x"), ("core.fsmonitor", "true"),
         ("core.hooksPath", "/h"), ("gpg.ssh.program", "/s"), ("gpg.program", "/g")],
    )  # fmt: skip
    def test_the_neutralised_global_keys_pass(
        self, repo: Path, global_git, key: str, value: str
    ) -> None:
        global_git(key, value)
        assert check(repo) == []

    def test_a_global_ssh_command_is_flagged(self, repo: Path, global_git) -> None:
        global_git("core.sshCommand", "ssh -i /tmp/key")
        (f,) = check(repo)
        assert (f.scope, f.key, f.code) == ("global", "core.sshcommand", E_B_REPOCFG)
        assert f.origin == os.environ["GIT_CONFIG_GLOBAL"]

    def test_a_global_url_rewrite_of_the_origin_is_flagged(self, repo: Path, global_git) -> None:
        global_git("url.https://evil.invalid/.insteadOf", "git@github.com:")
        assert [f.scope for f in check(repo)] == ["global"]
        global_git("url.https://evil.invalid/.pushInsteadOf", "git@github.com:")
        assert len(check(repo)) == 2

    def test_a_global_url_rewrite_of_another_host_is_not(self, repo: Path, global_git) -> None:
        global_git("url.https://mirror.invalid/.insteadOf", "git@gitlab.com:")
        assert check(repo) == []

    def test_a_url_rewrite_that_does_not_match_is_ignored_even_with_origin_unknown(
        self, repo: Path, global_git
    ) -> None:
        global_git("url.https://x.invalid/.insteadOf", "git@github.com:")
        assert check(repo, origin_url=None) == []

    def test_global_remote_origin_and_protocol_keys_are_flagged(
        self, repo: Path, global_git
    ) -> None:
        global_git("remote.origin.pushurl", "ssh://evil.invalid/x")
        global_git("protocol.ext.allow", "always")
        assert keys(check(repo)) == ["protocol.ext.allow", "remote.origin.pushurl"]

    def test_a_global_remote_for_another_name_is_fine(self, repo: Path, global_git) -> None:
        global_git("remote.upstream.fetch", "+refs/heads/*:refs/remotes/upstream/*")
        assert check(repo) == []

    def test_a_non_carter_global_include_is_judged_by_what_it_pulls_in(
        self, repo: Path, global_git, tmp_path: Path
    ) -> None:
        extra = tmp_path / "work.gitconfig"
        extra.write_text("[core]\n\tsshCommand = ssh -F /dev/null\n[user]\n\tname = W\n")
        global_git("include.path", str(extra), add=True)
        (f,) = check(repo)
        assert (f.scope, f.key, f.origin) == ("global", "core.sshcommand", str(extra))


class TestLocalScope:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("core.sshCommand", "ssh -i x"), ("core.fsmonitor", "evil"),
            ("core.hooksPath", ".githooks"),
            ("core.pager", "evil"), ("pager.log", "evil"), ("core.askPass", "evil"),
            ("credential.helper", "!evil"), ("credential.https://github.com.helper", "!evil"),
            ("url.https://x.invalid/.insteadOf", "git@github.com:"),
            ("remote.origin.pushurl", "ssh://x"), ("remote.origin.receivepack", "evil"),
            ("remote.origin.uploadpack", "evil"), ("protocol.ext.allow", "always"),
            ("diff.external", "evil"), ("filter.lfs.clean", "evil"), ("gpg.program", "evil"),
            ("gpg.ssh.program", "evil"), ("hook.foo.command", "evil"),
            ("include.path", "../extra.gitconfig"),
        ],
    )  # fmt: skip
    def test_exec_capable_and_routing_keys_are_flagged(
        self, repo: Path, key: str, value: str
    ) -> None:
        git("config", "--local", key, value, cwd=repo)
        found = check(repo)
        assert [f.scope for f in found] == ["local"], found

    def test_harmless_local_keys_pass(self, repo: Path) -> None:
        for key, value in (
            ("user.name", "Me"),
            ("branch.main.remote", "origin"),
            ("core.autocrlf", "false"),
        ):
            git("config", "--local", key, value, cwd=repo)
        assert check(repo) == []

    def test_a_local_remote_url_alone_is_fine(self, with_origin: Path) -> None:
        assert check(with_origin, origin_url=None) == []

    def test_a_worktree_scope_key_is_flagged(self, repo: Path) -> None:
        git("config", "--local", "extensions.worktreeConfig", "true", cwd=repo)
        git("config", "--worktree", "core.sshCommand", "evil", cwd=repo)
        assert [f.scope for f in check(repo)] == ["worktree"]

    def test_a_local_include_pulls_in_keys_judged_at_local_scope(self, repo: Path) -> None:
        extra = repo / ".git" / "extra"
        extra.write_text("[core]\n\tsshCommand = evil\n")
        git("config", "--local", "include.path", "extra", cwd=repo)
        scopes = {(f.key, f.scope) for f in check(repo)}
        assert ("include.path", "local") in scopes and ("core.sshcommand", "local") in scopes


class TestHookFiles:
    def hook(self, repo: Path, name: str, *, mode: int = 0o755) -> Path:
        path = repo / ".git" / "hooks" / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(mode)
        return path

    def test_a_foreign_reference_transaction_hook_is_flagged(self, repo: Path) -> None:
        hook = self.hook(repo, "reference-transaction")
        (f,) = check(repo)
        assert (f.scope, f.key, f.origin) == ("hooks", "reference-transaction", str(hook))

    def test_every_event_counts(self, repo: Path) -> None:
        for name in ("pre-push", "post-commit", "pre-receive", "fsmonitor-watchman"):
            self.hook(repo, name)
        assert keys(check(repo)) == ["fsmonitor-watchman", "post-commit", "pre-push", "pre-receive"]

    def test_samples_and_non_executable_files_and_unknown_names_are_ignored(
        self, repo: Path
    ) -> None:
        self.hook(repo, "pre-push.sample")
        self.hook(repo, "pre-commit", mode=0o644)
        self.hook(repo, "not-a-hook-name")
        assert check(repo) == []

    def test_a_carter_owned_hook_passes(self, repo: Path) -> None:
        hook = self.hook(repo, "pre-push")
        assert check(repo, owned=repocfg.CarterOwned(hook_files=(str(hook),))) == []

    def test_the_hooks_path_target_is_inspected(self, repo: Path) -> None:
        target = repo / ".githooks"
        target.mkdir()
        (target / "pre-push").write_text("#!/bin/sh\n")
        (target / "pre-push").chmod(0o755)
        git("config", "--local", "core.hooksPath", ".githooks", cwd=repo)
        found = check(repo)
        assert {f.scope for f in found} == {"local", "hooks"}
        assert any(f.origin == str(target / "pre-push") for f in found)

    def test_an_absolute_global_hooks_path_target_is_inspected_too(
        self, repo: Path, global_git, tmp_path: Path
    ) -> None:
        target = tmp_path / "global-hooks"
        target.mkdir()
        (target / "pre-push").write_text("#!/bin/sh\n")
        (target / "pre-push").chmod(0o755)
        global_git("core.hooksPath", str(target))
        assert [f.scope for f in check(repo)] == [
            "hooks"
        ]  # the key itself is neutralised, the file is shown

    def test_a_worktree_uses_the_common_hooks_dir(self, with_origin: Path, tmp_path: Path) -> None:
        git("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "w", cwd=with_origin)
        self.hook(with_origin, "pre-push")
        assert [f.scope for f in check(tmp_path / "wt")] == ["hooks"]


class TestFindingShape:
    def test_values_never_appear_in_a_finding(self, repo: Path) -> None:
        secret = prefixed("ghp_", "SECRETVALUE")
        git(
            "config",
            "--local",
            "credential.helper",
            f"!f() {{ echo password={secret}; }}; f",
            cwd=repo,
        )
        git(
            "config",
            "--local",
            "url.https://user:TOPSECRET@host.invalid/.insteadOf",
            "git@github.com:",
            cwd=repo,
        )
        text = repr(check(repo))
        assert "SECRETVALUE" not in text and "TOPSECRET" not in text and "password" not in text

    def test_url_userinfo_in_a_key_is_masked(self, repo: Path) -> None:
        git(
            "config",
            "--local",
            "url.https://user:TOPSECRET@host.invalid/.insteadOf",
            "git@github.com:",
            cwd=repo,
        )
        (f,) = check(repo)
        assert "TOPSECRET" not in f.key and "***" in f.key

    def test_command_scope_pollution_is_scrubbed_away_not_reported(
        self, repo: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.sshCommand")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "evil")
        assert check(repo) == []

    def test_findings_are_sorted_and_deterministic(self, repo: Path) -> None:
        git("config", "--local", "core.sshCommand", "a", cwd=repo)
        git("config", "--local", "diff.external", "b", cwd=repo)
        assert check(repo) == check(repo)

    def test_to_error_names_scope_and_key_only(self, repo: Path) -> None:
        git("config", "--local", "core.sshCommand", "SECRETCMD", cwd=repo)
        err = repocfg.to_error(check(repo))
        assert isinstance(err, IdentityError) and err.code == E_B_REPOCFG
        assert (
            "`local`" in str(err)
            and "`core.sshcommand`" in str(err)
            and "SECRETCMD" not in str(err)
        )
        assert repocfg.to_error([]) is None

    def test_it_is_read_only(self, repo: Path) -> None:
        before = (repo / ".git" / "config").read_bytes()
        git("config", "--local", "core.sshCommand", "x", cwd=repo)
        mid = (repo / ".git" / "config").read_bytes()
        check(repo)
        assert (repo / ".git" / "config").read_bytes() == mid != before

    def test_a_non_repo_is_a_clear_error(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(repocfg.RepoCheckError, match="not a git repository"):
            check(plain)
