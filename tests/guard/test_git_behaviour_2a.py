"""What git does that the slice-2a isolation block relies on (plan 004, step 6; spike E).

Observed on git 2.56.0, Linux, in the hermetic fixture home (``GIT_CONFIG_GLOBAL`` and
``GIT_CONFIG_NOSYSTEM`` point into the sandbox, ``GIT_ALLOW_PROTOCOL=file``). Every test is
local: file remotes only, no network, no credentials. The macOS repeat is step 38.

Each class records one finding. Where the finding says "the gate must forbid X", the matching
rule is RFC-0007 App C.4.1 and the corpus case comes in step 17.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from carter.guard.gitconfig import probe_scope


def _git_version() -> tuple[int, ...]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


GIT = _git_version()
needs_count = pytest.mark.skipif(GIT < (2, 31), reason="GIT_CONFIG_COUNT needs git >= 2.31")
needs_config_hooks = pytest.mark.skipif(
    GIT < (2, 54), reason="config-based hooks and `git hook list` need git >= 2.54"
)
needs_key_literal = pytest.mark.skipif(
    GIT < (2, 35), reason="`user.signingkey = key::<literal>` needs git >= 2.35 (RFC section 4.6)"
)


def git(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    full = {**os.environ, **(env or {})}
    return subprocess.run(
        ["git", *args], cwd=cwd, env=full, capture_output=True, text=True, input=stdin, timeout=60
    )


def counted(*pairs: tuple[str, str]) -> dict[str, str]:
    """``GIT_CONFIG_COUNT`` / ``KEY_n`` / ``VALUE_n`` for the pairs (the isolation block's form)."""
    env = {"GIT_CONFIG_COUNT": str(len(pairs))}
    for i, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def get_all(key: str, repo: Path, *pre: str, env: dict[str, str] | None = None) -> list[str]:
    done = git(*pre, "config", "--show-scope", "--get-all", key, cwd=repo, env=env)
    return [line.replace("\t", ":") for line in done.stdout.splitlines()]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    assert git("init", "-q", "-b", "main", cwd=path).returncode == 0
    return path


def set_global(text: str) -> None:
    Path(os.environ["GIT_CONFIG_GLOBAL"]).write_text(
        "[user]\n\tname = Fixture Human\n\temail = fixture-human@example.invalid\n" + text
    )


# --- 1. GIT_CONFIG_COUNT versus -c ------------------------------------------------------------


@needs_count
class TestPrecedence:
    """Order inside git's ``command`` scope: env entries first, then ``-c``; both after files.

    So the isolation block's env entries beat any config *file* (global, local), but an agent's
    ``-c commit.gpgsign=true`` beats the env entry ``commit.gpgsign=false``, and so does an
    inherited ``GIT_CONFIG_PARAMETERS`` (which is where ``-c`` lives). That is why isolation
    deletes an inherited ``GIT_CONFIG_PARAMETERS`` and why the gate forbids ``-c`` on
    ``commit.gpgsign``, ``gpg.*`` and the other keys of C.4.1.
    """

    @pytest.mark.parametrize(
        ("key", "carter", "agent"),
        [("commit.gpgsign", "false", "true"), ("gpg.format", "openpgp", "ssh")],
    )
    def test_env_beats_files_and_dash_c_beats_env(
        self, repo: Path, key: str, carter: str, agent: str
    ) -> None:
        section, name = key.split(".")
        set_global(f"[{section}]\n\t{name} = from-global\n")
        git("config", "--local", key, "from-local", cwd=repo)
        env = counted((key, carter))
        assert get_all(key, repo) == ["global:from-global", "local:from-local"]
        assert get_all(key, repo, env=env) == [
            "global:from-global",
            "local:from-local",
            f"command:{carter}",
        ]
        assert git("config", "--get", key, cwd=repo, env=env).stdout.strip() == carter
        both = get_all(key, repo, "-c", f"{key}={agent}", env=env)
        assert both[-2:] == [f"command:{carter}", f"command:{agent}"]  # -c comes last, so it wins
        assert (
            git("-c", f"{key}={agent}", "config", "--get", key, cwd=repo, env=env).stdout.strip()
            == agent
        )

    def test_an_inherited_config_parameters_also_beats_the_env_entries(self, repo: Path) -> None:
        env = {
            **counted(("commit.gpgsign", "false")),
            "GIT_CONFIG_PARAMETERS": "'commit.gpgsign=true'",
        }
        assert git("config", "--get", "commit.gpgsign", cwd=repo, env=env).stdout.strip() == "true"

    def test_a_child_of_dash_c_inherits_the_option_through_config_parameters(
        self, repo: Path
    ) -> None:
        done = git(
            "-c",
            "commit.gpgsign=true",
            "-c",
            "alias.pe=!printenv GIT_CONFIG_PARAMETERS",
            "pe",
            cwd=repo,
        )
        assert "commit.gpgsign" in done.stdout  # so a stale one in the server env must be deleted

    def test_pushurl_is_multi_valued_dash_c_adds_and_only_an_empty_value_resets(
        self, repo: Path, tmp_path: Path
    ) -> None:
        bare = tmp_path / "o.git"
        git("init", "-q", "--bare", str(bare))
        git("commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
        git("remote", "add", "origin", str(bare), cwd=repo)
        env = counted(("remote.origin.pushurl", "no_push"))
        refspec = "HEAD:refs/heads/b"
        assert git("push", "origin", refspec, cwd=repo, env=env).returncode != 0
        # adding a second pushurl keeps the first, which still fails
        added = git(
            "-c", f"remote.origin.pushurl={bare}", "push", "origin", refspec, cwd=repo, env=env
        )
        assert added.returncode != 0
        # an empty value clears the list: this is the bypass the gate closes (`-c remote.*`)
        reset = git("-c", "remote.origin.pushurl=", "push", "origin", refspec, cwd=repo, env=env)
        assert reset.returncode == 0


# --- 2. GIT_CONFIG_COUNT parsing ---------------------------------------------------------------


@needs_count
class TestCountParsing:
    """What git does with a malformed or inconsistent ``GIT_CONFIG_COUNT``.

    Every git command that reads config (``status``, ``config``, ``commit``...) dies with exit
    128 on a bad count; ``git --version`` is the only one that survives. A shell that inherits
    one is unusable, so the plugin must not append to it: C.2's strict parse (treat as polluted,
    start at 0) is right. Two additions to C.2 found here: a count larger than the keys present
    is fatal too (``missing config key GIT_CONFIG_KEY_n``), and git accepts forms a strict
    ``^[0-9]+$`` parse rejects (leading space, ``+1``), which the strict parse may refuse safely.
    """

    FATAL = [
        ("abc", "bogus count"),
        ("-1", "too many entries"),
        ("1.5", "bogus count"),
        ("0x1", "bogus count"),
        ("99999999999999", "too many entries"),
        ("3", "missing config key GIT_CONFIG_KEY_0"),
        ("1001", "missing config key GIT_CONFIG_KEY_0"),
    ]

    @pytest.mark.parametrize(("value", "message"), FATAL)
    def test_bad_counts_make_every_config_reading_command_fatal(
        self, repo: Path, value: str, message: str
    ) -> None:
        env = {"GIT_CONFIG_COUNT": value}
        status = git("status", "--short", cwd=repo, env=env)
        assert status.returncode == 128
        assert message in status.stderr and "unable to parse command-line config" in status.stderr
        assert git("--version", env=env).returncode == 0

    def test_a_count_larger_than_the_keys_present_is_fatal(self, repo: Path) -> None:
        env = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "x.a", "GIT_CONFIG_VALUE_0": "1"}
        done = git("config", "--get", "x.a", cwd=repo, env=env)
        assert done.returncode == 128 and "missing config key GIT_CONFIG_KEY_1" in done.stderr

    def test_a_key_without_its_value_or_without_a_section_is_fatal(self, repo: Path) -> None:
        no_value = git("status", cwd=repo, env={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "x.a"})
        assert (
            no_value.returncode == 128
            and "missing config value GIT_CONFIG_VALUE_0" in no_value.stderr
        )
        env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "nodot", "GIT_CONFIG_VALUE_0": "1"}
        assert git("status", cwd=repo, env=env).returncode == 128

    @pytest.mark.parametrize("value", ["", "0"])
    def test_empty_and_zero_mean_no_entries_and_keys_are_ignored(
        self, repo: Path, value: str
    ) -> None:
        env = {"GIT_CONFIG_COUNT": value, "GIT_CONFIG_KEY_0": "x.a", "GIT_CONFIG_VALUE_0": "1"}
        done = git("config", "--get", "x.a", cwd=repo, env=env)
        assert done.returncode == 1  # not found, not an error
        assert git("status", cwd=repo, env=env).returncode == 0

    def test_keys_without_a_count_are_ignored(self, repo: Path) -> None:
        env = {"GIT_CONFIG_KEY_0": "x.a", "GIT_CONFIG_VALUE_0": "1"}
        assert git("config", "--get", "x.a", cwd=repo, env=env).returncode == 1

    @pytest.mark.parametrize("value", [" 1", "+1"])
    def test_git_is_laxer_than_a_strict_parse(self, repo: Path, value: str) -> None:
        env = {"GIT_CONFIG_COUNT": value, "GIT_CONFIG_KEY_0": "x.a", "GIT_CONFIG_VALUE_0": "1"}
        assert git("config", "--get", "x.a", cwd=repo, env=env).stdout.strip() == "1"

    def test_the_last_entry_wins_so_carter_appended_last_overrides_a_collision(
        self, repo: Path
    ) -> None:
        env = counted(("x.a", "user"), ("x.b", "other"), ("x.a", "carter"))
        assert git("config", "--get", "x.a", cwd=repo, env=env).stdout.strip() == "carter"


# --- 3. credential helper order ----------------------------------------------------------------

HELPER = (
    '!f(){ test "$1" = get && printf \'username=x-access-token\\npassword=%s\\n\' "$GH_TOKEN"; }; f'
)
RESET_THEN_GITHUB = (("credential.helper", ""), ("credential.https://github.com.helper", HELPER))


@needs_count
class TestCredentialHelperOrder:
    """The empty reset removes every earlier helper; the URL-scoped one then serves github.com only.

    NB: ``;`` starts a comment in a config *file*, so a helper written to a file must be quoted;
    in the env form (``GIT_CONFIG_VALUE_n``) the value is taken verbatim.
    """

    SENTINEL = "TOKEN-SENTINEL-" + "0123456789"  # not token-shaped on purpose

    @pytest.fixture
    def system_helper(self, tmp_path: Path) -> tuple[dict[str, str], Path]:
        called = tmp_path / "system-helper-called"
        system = tmp_path / "system-gitconfig"
        system.write_text(
            f'[credential]\n\thelper = "!f() {{ echo called >> {called}; echo username=sys; '
            'echo password=SYSTEM-HELPER; }; f"\n'
        )
        return {"GIT_CONFIG_SYSTEM": str(system), "GIT_CONFIG_NOSYSTEM": "0"}, called

    def fill(self, host: str, repo: Path, env: dict[str, str]):
        return git(
            "credential", "fill", cwd=repo, env=env, stdin=f"protocol=https\nhost={host}\n\n"
        )

    def test_without_isolation_the_system_helper_answers(self, repo: Path, system_helper) -> None:
        env, called = system_helper
        out = self.fill("github.com", repo, env).stdout
        assert "password=SYSTEM-HELPER" in out and called.exists()

    def test_a_url_scoped_helper_alone_is_not_enough_the_reset_is_needed(
        self, repo: Path, system_helper
    ) -> None:
        env, called = system_helper
        env = {**env, "GH_TOKEN": self.SENTINEL, **counted(RESET_THEN_GITHUB[1])}
        assert "SYSTEM-HELPER" in self.fill("github.com", repo, env).stdout  # first helper wins
        assert called.exists()

    def test_after_the_reset_only_github_com_gets_the_token_and_the_system_helper_never_runs(
        self, repo: Path, system_helper
    ) -> None:
        env, called = system_helper
        env = {**env, "GH_TOKEN": self.SENTINEL, **counted(*RESET_THEN_GITHUB)}
        ok = self.fill("github.com", repo, env)
        assert ok.returncode == 0
        assert "username=x-access-token" in ok.stdout and f"password={self.SENTINEL}" in ok.stdout
        assert not called.exists()
        for other in ("gitlab.com", "api.github.com", "github.com.evil.example"):
            denied = self.fill(other, repo, {**env, "GIT_TERMINAL_PROMPT": "0"})
            assert denied.returncode == 128 and self.SENTINEL not in denied.stdout, other
            assert "terminal prompts disabled" in denied.stderr
        assert not called.exists()

    def test_the_reset_also_drops_a_global_helper(self, repo: Path) -> None:
        set_global(
            '[credential]\n\thelper = "!f() { echo username=glob; echo password=GLOBAL; }; f"\n'
        )
        env = {"GH_TOKEN": self.SENTINEL, **counted(*RESET_THEN_GITHUB)}
        out = self.fill("github.com", repo, env).stdout
        assert f"password={self.SENTINEL}" in out and "GLOBAL" not in out


# --- 4. no_push --------------------------------------------------------------------------------

REWRITES = (
    ("url.https://github.com/.insteadOf", "git@github.com:"),
    ("url.https://github.com/.insteadOf", "ssh://git@github.com/"),
    ("url.no_push://.pushInsteadOf", "https://github.com/"),
    ("url.no_push://.pushInsteadOf", "git@github.com:"),
    ("url.no_push://.pushInsteadOf", "ssh://git@github.com/"),
)
GITHUB_FORMS = [
    "https://github.com/o/r.git",
    "git@github.com:o/r.git",
    "ssh://git@github.com/o/r.git",
]


@needs_count
class TestNoPush:
    """Pushes to GitHub fail locally (no network) while fetches go over HTTPS."""

    @pytest.fixture
    def commit(self, repo: Path) -> Path:
        git(
            "-c",
            "user.name=a",
            "-c",
            "user.email=a@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
            cwd=repo,
        )
        return repo

    @pytest.mark.parametrize("url", GITHUB_FORMS)
    def test_push_is_rewritten_to_no_push_and_fetch_goes_to_https(
        self, commit: Path, url: str
    ) -> None:
        git("remote", "add", "origin", url, cwd=commit)
        env = counted(*REWRITES)
        assert git("ls-remote", "--get-url", "origin", cwd=commit, env=env).stdout.strip() == (
            "https://github.com/o/r.git"
        )
        assert git("remote", "get-url", "--push", "origin", cwd=commit, env=env).stdout.strip() == (
            "no_push://o/r.git"
        )
        pushed = git("push", "origin", "HEAD:refs/heads/x", cwd=commit, env=env)
        assert pushed.returncode == 128 and "protocol 'no_push' is not supported" in pushed.stderr

    @pytest.mark.parametrize("url", GITHUB_FORMS)
    def test_remote_origin_pushurl_alone_also_stops_the_push(self, commit: Path, url: str) -> None:
        git("remote", "add", "origin", url, cwd=commit)
        env = counted(*REWRITES[:2], ("remote.origin.pushurl", "no_push"))
        assert (
            git("remote", "get-url", "--push", "origin", cwd=commit, env=env).stdout.strip()
            == "no_push"
        )
        pushed = git("push", "origin", "HEAD:refs/heads/x", cwd=commit, env=env)
        assert (
            pushed.returncode == 128
            and "'no_push' does not appear to be a git repository" in pushed.stderr
        )

    def test_an_explicit_github_url_is_rewritten_but_another_host_is_not(
        self, commit: Path, tmp_path: Path
    ) -> None:
        env = counted(*REWRITES)
        github = git("push", "https://github.com/o/r.git", "HEAD:refs/heads/y", cwd=commit, env=env)
        assert github.returncode == 128 and "no_push" in github.stderr
        bare = tmp_path / "other.git"
        git("init", "-q", "--bare", str(bare))
        elsewhere = git("push", str(bare), "HEAD:refs/heads/y", cwd=commit, env=env)
        assert (
            elsewhere.returncode == 0
        )  # documented residual: pre-push, the gate and the 403 cover it


# --- 5. hooks -----------------------------------------------------------------------------------


@needs_config_hooks
class TestConfigHookSurvivesTheUsualBypasses:
    @pytest.fixture
    def pushing(self, repo: Path, tmp_path: Path):
        log = tmp_path / "hook.log"
        set_global(f'[hook "g"]\n\tevent = pre-push\n\tcommand = echo ran >> {log}\n')
        bare = tmp_path / "o.git"
        git("init", "-q", "--bare", str(bare))
        git("commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
        git("remote", "add", "origin", str(bare), cwd=repo)

        def push(*pre: str, env: dict[str, str] | None = None, extra: tuple[str, ...] = ()) -> bool:
            log.unlink(missing_ok=True)
            done = git(
                *pre,
                "push",
                *extra,
                "origin",
                f"HEAD:refs/heads/b{os.urandom(3).hex()}",
                cwd=repo,
                env=env,
            )
            assert done.returncode == 0, done.stderr
            return log.exists()

        push.log = log  # type: ignore[attr-defined]
        push.repo = repo  # type: ignore[attr-defined]
        return push

    def test_it_runs_and_is_listed_as_global(self, pushing) -> None:
        assert pushing()
        listed = git("hook", "list", "--show-scope", "pre-push", cwd=pushing.repo)
        assert listed.stdout.strip() == "global\tg"

    def test_core_hookspath_to_dev_null_does_not_disable_it_but_does_skip_classic_hooks(
        self, pushing
    ) -> None:
        classic = pushing.repo / ".git/hooks/pre-push"
        classic.write_text(f"#!/bin/sh\necho classic >> {pushing.log}\n")
        classic.chmod(0o755)
        assert pushing()
        assert pushing.log.read_text().split()[0] == "ran" and "classic" in pushing.log.read_text()
        assert pushing("-c", "core.hooksPath=/dev/null")
        assert (
            "classic" not in pushing.log.read_text()
        )  # the repo hook is skipped, the config hook is not

    def test_no_verify_skips_it_a_documented_limit_the_gate_rejects_every_git_push(
        self, pushing
    ) -> None:
        assert not pushing(extra=("--no-verify",))

    @pytest.mark.parametrize(
        "how",
        [
            {"pre": ("-c", "hook.g.enabled=false")},
            {"env": counted(("hook.g.enabled", "false"))},
            {"pre": ("-c", "hook.g.command=true")},  # replaces the command
            {"pre": ("-c", "hook.g.event=")},  # clears the event
        ],
        ids=["dash-c-enabled", "env-enabled", "dash-c-command", "dash-c-event"],
    )
    def test_dash_c_or_env_can_switch_it_off_so_the_gate_forbids_hook_keys(
        self, pushing, how
    ) -> None:
        assert not pushing(*how.get("pre", ()), env=how.get("env"))

    def test_an_extra_hook_added_with_dash_c_does_not_replace_it(self, pushing) -> None:
        assert pushing("-c", "hook.x.event=pre-push", "-c", "hook.x.command=true")

    def test_a_local_enabled_true_re_enables_a_globally_disabled_hook(self, pushing) -> None:
        hook = f'[hook "g"]\n\tevent = pre-push\n\tcommand = echo ran >> {pushing.log}\n'
        set_global(hook + "\tenabled = false\n")
        assert not pushing()
        git("config", "--local", "hook.g.enabled", "true", cwd=pushing.repo)
        assert pushing()


# --- 6. git < 2.54 (simulated) ------------------------------------------------------------------


class TestOldGitIsDetectedByBehaviour:
    """A PATH wrapper that behaves like a git without ``hook list`` (exit 129 and a usage text).

    This is a **simulation**: the real older git is on the user's Mac (Homebrew 2.51, step 38,
    which records the real text). The detection is behavioural (003 decision 3), so what matters
    is that a failing ``git hook list`` selects ``no-config-hooks`` and that the Carter probe
    never touches the real config.
    """

    def test_a_git_without_hook_list_selects_the_per_repo_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
        wrapper = tmp_path / "oldbin" / "git"
        wrapper.parent.mkdir()
        wrapper.write_text(
            '#!/bin/sh\nif [ "$1" = hook ] && [ "$2" = list ]; then\n'
            '  echo "usage: git hook run [--ignore-missing] <hook-name> [-- <hook-args>]" >&2\n'
            f'  exit 129\nfi\nexec {real} "$@"\n'
        )
        wrapper.chmod(0o755)
        monkeypatch.setenv("PATH", f"{wrapper.parent}{os.pathsep}{os.environ['PATH']}")
        assert probe_scope() == "no-config-hooks"

    @needs_config_hooks
    def test_a_modern_git_selects_the_include(self) -> None:
        assert probe_scope() == "include"


# --- 7. -U with key:: literals (input for 2b) ----------------------------------------------------


@needs_key_literal
class TestSigningProgramArgv:
    """git hands a ``key::`` literal to ``gpg.ssh.program`` as a temp key file plus ``-U``."""

    def test_argv_of_the_signing_program(self, repo: Path, tmp_path: Path) -> None:
        record = tmp_path / "argv.log"
        shim = tmp_path / "shim.sh"
        shim.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {record}\nexit 1\n')
        shim.chmod(0o755)
        done = git(
            "-c",
            "gpg.format=ssh",
            "-c",
            "user.signingkey=key::ssh-ed25519 AAAAFAKEKEYBLOB",
            "-c",
            f"gpg.ssh.program={shim}",
            "commit",
            "-S",
            "--allow-empty",
            "-m",
            "s",
            cwd=repo,
        )
        assert done.returncode != 0  # the shim refuses: nothing is signed or committed
        argv = record.read_text().splitlines()
        assert argv[:4] == ["-Y", "sign", "-n", "git"]
        assert argv[4] == "-f" and re.search(r"\.git_signing_key_tmp", argv[5])
        assert argv[6] == "-U" and re.search(r"\.git_signing_buffer_tmp", argv[7])
