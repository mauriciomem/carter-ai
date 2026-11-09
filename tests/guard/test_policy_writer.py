"""Atomic, verified, reversible writes of ``policies`` into the OpenCode config
. Only ``fake_opencode`` is ever run, never the real
binary, and only under the sandbox home."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from carter.guard import configwrite, policies
from carter.guard.state import GuardState
from carter.identity import IdentityError
from carter.identity.errors import E_POLICIES_MISSING
from carter.identity.policyset import Statement, policy_statements
from carter.install.mcp import config_target, global_config_files
from carter.install.paths import backups_dir

SENTINEL = "sk-SENTINEL-provider-key-0123456789"
PROVIDERS = {"anthropic": {"settings": {"apiKey": SENTINEL}}, "openai": {}}


def st(id_: str, resource: str, effect: str = "deny") -> Statement:
    return Statement(id_, "g2", "tool.use", resource, effect)


A = st("deny-a", "shell:aaa *")
B = st("deny-b", "shell:bbb *")
ALLOW = st("allow-c", "shell:ccc *", "allow")


def as_json(stmts: list[Statement]) -> list[dict]:
    return [{"action": s.action, "resource": s.resource, "effect": s.effect} for s in stmts]


def dbg(policies_: list[Statement] | list[dict] = (), providers: dict | None = None) -> str:
    items = [s if isinstance(s, dict) else as_json([s])[0] for s in policies_]
    return json.dumps(
        {"providers": PROVIDERS if providers is None else providers, "policies": items}
    )


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    """The jsonc/json target under the sandbox ``base_dir``; created by tests that need it."""
    return config_target(tmp_path)


def run_apply(tmp_path: Path, stmts: list[Statement], state: GuardState | None = None, **kw):
    state = state if state is not None else GuardState()
    result = policies.apply(tmp_path, state, stmts, backup_root=backups_dir(tmp_path) / "t0", **kw)
    return state, result


def write_cfg(path: Path, data: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2) + "\n")


def stray_tmp(path: Path) -> list[str]:
    return [p.name for p in path.parent.iterdir() if p.name.startswith(".") and path.name in p.name]


class TestMerge:
    def test_creates_the_file_when_absent_and_records_ownership(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg([A, B])])
        state, res = run_apply(tmp_path, [A, B])
        assert res.changed and res.target == cfg
        assert json.loads(cfg.read_text()) == {"policies": as_json([A, B])}
        assert state.opencode_config == str(cfg)
        assert [p["id"] for p in state.owned_policies()] == ["deny-a", "deny-b"]
        assert all(p["preexisting"] is False for p in state.opencode_policies)
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o600

    def test_keeps_unrelated_keys_and_other_policies_and_puts_ours_at_the_tail(
        self, tmp_path, cfg, fake_opencode
    ):
        mine = {"action": "provider.use", "resource": "openai", "effect": "deny"}
        write_cfg(cfg, {"providers": PROVIDERS, "model": "x", "policies": [mine]})
        fake_opencode(config_sequence=[dbg([mine]), dbg([mine, A, ALLOW])])
        run_apply(tmp_path, [A, ALLOW])
        data = json.loads(cfg.read_text())
        assert data["model"] == "x" and data["providers"] == PROVIDERS
        assert data["policies"] == [mine, *as_json([A, ALLOW])]

    def test_denies_then_allows_in_the_given_order(self, tmp_path, cfg, fake_opencode):
        stmts = list(policy_statements(("g2", "sudo-docker"), home=str(tmp_path)))
        fake_opencode(config_sequence=[dbg(), dbg(stmts)])
        run_apply(tmp_path, stmts)
        effects = [p["effect"] for p in json.loads(cfg.read_text())["policies"]]
        assert effects == sorted(effects, key=lambda e: e == "allow")

    def test_the_jsonc_file_wins_when_both_exist(self, tmp_path, fake_opencode):
        json_p, jsonc_p = global_config_files(tmp_path)
        write_cfg(json_p, {"model": "a"})
        write_cfg(jsonc_p, {"model": "b"})
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        run_apply(tmp_path, [A])
        assert "policies" in json.loads(jsonc_p.read_text())
        assert json.loads(json_p.read_text()) == {"model": "a"}

    def test_uses_opencode_json_when_only_it_exists(self, tmp_path, fake_opencode):
        json_p, jsonc_p = global_config_files(tmp_path)
        write_cfg(json_p, {"model": "a"})
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        run_apply(tmp_path, [A])
        assert not jsonc_p.exists() and "policies" in json.loads(json_p.read_text())

    def test_unparseable_config_is_refused_and_untouched(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, "{ nope")
        fake_opencode(config_sequence=[dbg()])
        with pytest.raises(policies.PolicyWriteError, match="parse"):
            run_apply(tmp_path, [A])
        assert cfg.read_text() == "{ nope"

    @pytest.mark.parametrize("bad", ['{"policies": "x"}', '{"policies": {"a": 1}}', "[1]"])
    def test_a_wrongly_shaped_policies_key_is_refused(self, tmp_path, cfg, fake_opencode, bad):
        write_cfg(cfg, bad)
        fake_opencode(config_sequence=[dbg()])
        with pytest.raises(policies.PolicyWriteError):
            run_apply(tmp_path, [A])
        assert cfg.read_text() == bad


class TestIdempotentAndUpgrade:
    def test_second_run_writes_nothing(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg([A, B])])
        state, _ = run_apply(tmp_path, [A, B])
        before = (cfg.read_bytes(), cfg.stat().st_mtime_ns, cfg.stat().st_ino)
        os.utime(cfg, ns=(1_000_000_000, 1_000_000_000))
        fake_opencode(config_sequence=[dbg([A, B])])
        _, res = run_apply(tmp_path, [A, B], state)
        assert res.changed is False
        assert cfg.read_bytes() == before[0]
        assert cfg.stat().st_mtime_ns == 1_000_000_000 and cfg.stat().st_ino == before[2]

    def test_upgrade_replaces_the_recorded_tuples_and_reappends(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg([A, B])])
        state, _ = run_apply(tmp_path, [A, B])
        newer = st("deny-b", "shell:BBB *")
        fake_opencode(config_sequence=[dbg([A, B]), dbg([A, newer])])
        _, res = run_apply(tmp_path, [A, newer], state)
        assert json.loads(cfg.read_text())["policies"] == as_json([A, newer])
        assert res.removed == ["deny-b"] and res.added == ["deny-b"]
        assert [p["resource"] for p in state.opencode_policies if p["id"] == "deny-b"] == [
            newer.resource
        ]

    def test_a_dropped_statement_is_removed(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg([A, B])])
        state, _ = run_apply(tmp_path, [A, B])
        fake_opencode(config_sequence=[dbg([A, B]), dbg([A])])
        run_apply(tmp_path, [A], state)
        assert json.loads(cfg.read_text())["policies"] == as_json([A])
        assert [p["id"] for p in state.opencode_policies] == ["deny-a"]

    def test_our_block_moves_back_to_the_tail_after_the_user_appends_after_it(
        self, tmp_path, cfg, fake_opencode
    ):
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        state, _ = run_apply(tmp_path, [A])
        data = json.loads(cfg.read_text())
        late = {"action": "tool.use", "resource": "shell:git push *", "effect": "allow"}
        data["policies"].append(late)  # would lift a deny that comes before it
        write_cfg(cfg, data)
        fake_opencode(config_sequence=[dbg([A, late]), dbg([late, A])])
        run_apply(tmp_path, [A], state)
        assert json.loads(cfg.read_text())["policies"] == [late, *as_json([A])]

    def test_a_statement_the_user_already_has_is_preexisting_and_left_alone(
        self, tmp_path, cfg, fake_opencode
    ):
        theirs = as_json([A])[0]
        write_cfg(cfg, {"policies": [theirs]})
        fake_opencode(config_sequence=[dbg([A]), dbg([A, B])])
        state, res = run_apply(tmp_path, [A, B])
        assert json.loads(cfg.read_text())["policies"] == [theirs, *as_json([B])]
        assert {p["id"]: p["preexisting"] for p in state.opencode_policies} == {
            "deny-a": True,
            "deny-b": False,
        }
        assert res.preexisting == ["deny-a"] and res.added == ["deny-b"]

    def test_preexisting_entries_survive_a_later_run_untouched(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"policies": as_json([A])})
        fake_opencode(config_sequence=[dbg([A]), dbg([A, B])])
        state, _ = run_apply(tmp_path, [A, B])
        fake_opencode(config_sequence=[dbg([A, B])])
        _, res = run_apply(tmp_path, [A, B], state)
        assert res.changed is False


class TestAtomicWrite:
    def test_a_symlinked_config_keeps_its_link(self, tmp_path, cfg, fake_opencode):
        real = tmp_path / "dotfiles" / "opencode.jsonc"
        write_cfg(real, {"model": "x"})
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.symlink_to(real)
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        run_apply(tmp_path, [A])
        assert cfg.is_symlink() and cfg.resolve() == real.resolve()
        assert json.loads(real.read_text())["policies"] == as_json([A])

    def test_the_existing_file_mode_is_kept(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"model": "x"})
        cfg.chmod(0o640)
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        run_apply(tmp_path, [A])
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o640

    @pytest.mark.parametrize("point", ["write", "fsync", "replace"])
    def test_failure_leaves_the_original_intact_and_no_tmp(
        self, tmp_path, cfg, fake_opencode, monkeypatch, point
    ):
        write_cfg(cfg, {"providers": PROVIDERS})
        original = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        calls = {"n": 0}

        def second_call_fails(real):
            # Call 1 writes the backup copy; call 2 is the config itself. Failing only the
            # second proves the *config* write is the atomic one.
            def wrapper(*a, **k):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError(f"injected at {point}")
                return real(*a, **k)

            return wrapper

        if point == "write":
            real_fdopen = os.fdopen

            class Failing:
                def __init__(self, handle):
                    self._h = handle

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    self._h.close()
                    return False

                def write(self, _data):
                    raise OSError("injected at write")

            def fdopen(fd, *a, **k):
                handle = real_fdopen(fd, *a, **k)
                calls["n"] += 1
                return Failing(handle) if calls["n"] == 2 else handle

            monkeypatch.setattr("carter.install.atomic.os.fdopen", fdopen)
        elif point == "fsync":
            monkeypatch.setattr(os, "fsync", second_call_fails(os.fsync))
        else:
            monkeypatch.setattr(os, "replace", second_call_fails(os.replace))
        with pytest.raises(OSError, match="injected"):
            run_apply(tmp_path, [A])
        assert calls["n"] >= 2
        assert cfg.read_bytes() == original
        assert stray_tmp(cfg) == []

    def test_fsync_happens_before_the_replace(self, tmp_path, cfg, fake_opencode, monkeypatch):
        order: list[str] = []
        real_fsync, real_replace = os.fsync, os.replace
        monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
        monkeypatch.setattr(
            os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1]
        )
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        run_apply(tmp_path, [A])
        assert order.index("fsync") < order.index("replace")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
class TestReadOnlyTarget:
    def test_read_only_file_is_refused_and_untouched(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"model": "x"})
        cfg.chmod(0o444)
        fake_opencode(config_sequence=[dbg()])
        with pytest.raises(policies.PolicyWriteError, match="read-only"):
            run_apply(tmp_path, [A])
        assert json.loads(cfg.read_text()) == {"model": "x"}

    def test_read_only_directory_is_refused(self, tmp_path, cfg, fake_opencode):
        cfg.parent.mkdir(parents=True)
        cfg.parent.chmod(0o555)
        try:
            fake_opencode(config_sequence=[dbg()])
            with pytest.raises(policies.PolicyWriteError, match="read-only"):
                run_apply(tmp_path, [A])
        finally:
            cfg.parent.chmod(0o755)
        assert not cfg.exists()


class TestComments:
    def test_a_commented_file_is_backed_up_and_the_warning_names_the_alternative(
        self, tmp_path, cfg, fake_opencode
    ):
        text = '{\n  // my notes\n  "model": "x"\n}\n'
        write_cfg(cfg, text)
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        _, res = run_apply(tmp_path, [A])
        backup = cfg.with_name(cfg.name + ".carter-backup")
        assert backup.read_text() == text
        assert any("comments" in w and "carter-backup" in w for w in res.warnings)
        assert "// my notes" not in cfg.read_text()

    def test_a_file_without_comments_is_rewritten_without_a_comment_backup(
        self, tmp_path, cfg, fake_opencode
    ):
        write_cfg(cfg, {"model": "x"})
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        _, res = run_apply(tmp_path, [A])
        assert not cfg.with_name(cfg.name + ".carter-backup").exists()
        assert not any("comments" in w for w in res.warnings)

    def test_a_backup_copy_of_the_original_is_kept_under_the_backup_root(
        self, tmp_path, cfg, fake_opencode
    ):
        write_cfg(cfg, {"model": "x"})
        original = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        _, res = run_apply(tmp_path, [A])
        assert res.backup is not None and res.backup.read_bytes() == original
        assert res.backup.is_relative_to(backups_dir(tmp_path))
        assert stat.S_IMODE(res.backup.stat().st_mode) == 0o600


class TestVerifyAndRollback:
    def test_success_needs_every_provider_and_every_statement(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg([A, B])])
        _, res = run_apply(tmp_path, [A, B])
        assert res.changed

    def test_a_missing_statement_restores_the_backup_and_names_it(
        self, tmp_path, cfg, fake_opencode
    ):
        write_cfg(cfg, {"providers": PROVIDERS})
        original = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg(), dbg([A])])  # B was dropped by OpenCode
        state = GuardState()
        with pytest.raises(IdentityError) as exc:
            run_apply(tmp_path, [A, B], state)
        assert exc.value.code == E_POLICIES_MISSING
        assert "deny-b" in str(exc.value) and "deny-a" not in str(exc.value)
        assert cfg.read_bytes() == original
        assert state.opencode_policies == [] and state.opencode_config is None

    def test_a_lost_provider_restores_the_backup(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"providers": PROVIDERS})
        original = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg(), dbg([A], providers={"anthropic": {}})])
        with pytest.raises(IdentityError) as exc:
            run_apply(tmp_path, [A])
        assert exc.value.code == E_POLICIES_MISSING and "openai" in str(exc.value)
        assert cfg.read_bytes() == original

    def test_a_new_file_is_removed_again_on_rollback(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg()])
        with pytest.raises(IdentityError):
            run_apply(tmp_path, [A])
        assert not cfg.exists()

    def test_an_unreadable_after_state_rolls_back(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"providers": PROVIDERS})
        original = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg(), "not json"])
        with pytest.raises(policies.PolicyWriteError, match="rolled back"):
            run_apply(tmp_path, [A])
        assert cfg.read_bytes() == original

    def test_an_unreadable_before_state_writes_nothing(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"providers": PROVIDERS})
        original = cfg.read_bytes()
        fake_opencode(config_output="boom", config_exit=1)
        with pytest.raises(policies.PolicyWriteError, match="nothing was written"):
            run_apply(tmp_path, [A])
        assert (
            cfg.read_bytes() == original and not cfg.with_name(cfg.name + ".carter-backup").exists()
        )

    def test_the_real_opencode_is_never_used(self, tmp_path, cfg):
        # No fake requested: the guard stub on PATH exits 97, so the writer must refuse.
        with pytest.raises(policies.PolicyWriteError):
            run_apply(tmp_path, [A])
        assert not cfg.exists()

    def test_debug_output_never_reaches_a_backup_an_error_or_the_state(
        self, tmp_path, cfg, fake_opencode
    ):
        write_cfg(cfg, {"model": "x"})
        fake_opencode(config_sequence=[dbg(), dbg([A], providers={})])
        state = GuardState()
        with pytest.raises(IdentityError) as exc:
            run_apply(tmp_path, [A], state)
        assert SENTINEL not in str(exc.value) + exc.value.detail
        for path in tmp_path.rglob("*"):
            if path.is_file() and "fakebin" not in path.parts:  # the fake holds its script's output
                assert SENTINEL not in path.read_text(errors="ignore"), path
        assert SENTINEL not in json.dumps(state.to_dict())

    def test_a_failed_rollback_says_where_the_original_is(
        self, tmp_path, cfg, fake_opencode, monkeypatch
    ):
        write_cfg(cfg, {"providers": PROVIDERS})
        fake_opencode(config_sequence=[dbg(), dbg()])
        real = configwrite.atomic_write_bytes
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:  # the restore
                raise OSError("busy")
            return real(*a, **k)

        monkeypatch.setattr(configwrite, "atomic_write_bytes", flaky)
        with pytest.raises(policies.PolicyWriteError, match="ROLLBACK FAILED.*backups"):
            run_apply(tmp_path, [A])


class TestMissingStatements:
    def test_reports_each_missing_statement_alone(self):
        got = json.loads(dbg([A, ALLOW]))
        assert policies.missing_statements(got, [A, B, ALLOW]) == [B]

    def test_nothing_missing(self):
        assert policies.missing_statements(json.loads(dbg([A, B])), [A, B]) == []

    def test_all_missing_when_policies_were_dropped_wholesale(self):
        assert policies.missing_statements(json.loads(dbg([])), [A, B]) == [A, B]

    def test_effect_and_resource_must_both_match(self):
        other = st("deny-a", "shell:aaa *", "allow")
        assert policies.missing_statements(json.loads(dbg([other])), [A]) == [A]


class TestDryRun:
    def test_writes_nothing_and_never_calls_opencode(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"model": "x"})
        before = cfg.read_bytes()
        fake_opencode()  # `debug config` unconfigured: exit 2 if it were called
        state, res = run_apply(tmp_path, [A, B], dry_run=True)
        assert res.changed and res.added == ["deny-a", "deny-b"] and res.backup is None
        assert cfg.read_bytes() == before
        assert state == GuardState()
        assert list((tmp_path / "carter").glob("**/*")) == []

    def test_dry_run_on_an_unchanged_config_reports_no_change(self, tmp_path, cfg, fake_opencode):
        fake_opencode(config_sequence=[dbg(), dbg([A])])
        state, _ = run_apply(tmp_path, [A])
        _, res = run_apply(tmp_path, [A], state, dry_run=True)
        assert res.changed is False


class TestRemove:
    def install(self, tmp_path, fake_opencode, stmts=(A, B)):
        fake_opencode(config_sequence=[dbg(), dbg(list(stmts))])
        return run_apply(tmp_path, list(stmts))[0]

    def run_remove(self, tmp_path, state, **kw):
        return policies.remove(tmp_path, state, backup_root=backups_dir(tmp_path) / "t1", **kw)

    def test_removes_only_what_it_owns_and_keeps_the_rest(self, tmp_path, cfg, fake_opencode):
        write_cfg(
            cfg,
            {"model": "x", "policies": [{"action": "mcp.use", "resource": "z", "effect": "deny"}]},
        )
        fake_opencode(config_sequence=[dbg(), dbg([A, B])])
        state, _ = run_apply(tmp_path, [A, B])
        fake_opencode(config_sequence=[dbg([A, B]), dbg()])
        res = self.run_remove(tmp_path, state)
        data = json.loads(cfg.read_text())
        assert data["policies"] == [{"action": "mcp.use", "resource": "z", "effect": "deny"}]
        assert data["model"] == "x"
        assert res.removed == ["deny-a", "deny-b"] and state.opencode_policies == []

    def test_an_empty_policies_list_is_dropped(self, tmp_path, cfg, fake_opencode):
        state = self.install(tmp_path, fake_opencode)
        fake_opencode(config_sequence=[dbg([A, B]), dbg()])
        self.run_remove(tmp_path, state)
        assert "policies" not in json.loads(cfg.read_text())

    def test_an_edited_statement_is_kept_and_reported(self, tmp_path, cfg, fake_opencode):
        state = self.install(tmp_path, fake_opencode)
        data = json.loads(cfg.read_text())
        data["policies"][0]["resource"] = "shell:aaa --user-edit *"
        write_cfg(cfg, data)
        fake_opencode(config_sequence=[dbg(), dbg()])
        res = self.run_remove(tmp_path, state)
        assert res.kept_edited == ["deny-a"] and res.removed == ["deny-b"]
        assert json.loads(cfg.read_text())["policies"][0]["resource"] == "shell:aaa --user-edit *"
        assert [p["id"] for p in state.opencode_policies] == []  # nothing left that we own

    def test_preexisting_statements_are_never_touched(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"policies": as_json([A])})
        fake_opencode(config_sequence=[dbg([A]), dbg([A, B])])
        state, _ = run_apply(tmp_path, [A, B])
        fake_opencode(config_sequence=[dbg([A, B]), dbg([A])])
        res = self.run_remove(tmp_path, state)
        assert json.loads(cfg.read_text())["policies"] == as_json([A])
        assert res.removed == ["deny-b"]
        assert [p["id"] for p in state.opencode_policies] == []

    def test_remove_with_nothing_recorded_is_a_no_op(self, tmp_path, cfg, fake_opencode):
        write_cfg(cfg, {"model": "x"})
        before = cfg.read_bytes()
        fake_opencode()
        res = self.run_remove(tmp_path, GuardState())
        assert res.changed is False and cfg.read_bytes() == before

    def test_remove_twice_is_a_no_op(self, tmp_path, cfg, fake_opencode):
        state = self.install(tmp_path, fake_opencode)
        fake_opencode(config_sequence=[dbg([A, B]), dbg()])
        self.run_remove(tmp_path, state)
        fake_opencode()
        assert self.run_remove(tmp_path, state).changed is False

    def test_remove_rolls_back_when_a_provider_is_lost(self, tmp_path, cfg, fake_opencode):
        state = self.install(tmp_path, fake_opencode)
        after_install = cfg.read_bytes()
        fake_opencode(config_sequence=[dbg([A, B]), dbg(providers={})])
        with pytest.raises(IdentityError):
            self.run_remove(tmp_path, state)
        assert cfg.read_bytes() == after_install
        assert len(state.owned_policies()) == 2

    def test_a_vanished_config_file_is_fine(self, tmp_path, cfg, fake_opencode):
        state = self.install(tmp_path, fake_opencode)
        cfg.unlink()
        fake_opencode()
        res = self.run_remove(tmp_path, state)
        assert res.changed is False and state.opencode_policies == []


class TestVerifyWaitsForTheService:
    """OpenCode 2.1.4's background service reloads a changed config asynchronously: the first
    `debug config` right after a write still shows the old file (observed: gone within
    0.5 s). The verify step must re-read before it concludes a statement is lost and rolls
    back; otherwise the very first live install is undone for nothing."""

    @pytest.fixture
    def pauses(self, monkeypatch: pytest.MonkeyPatch) -> list[float]:
        seen: list[float] = []
        monkeypatch.setattr(configwrite, "_sleep", seen.append)
        return seen

    @staticmethod
    def sequence(answers: list[dict | Exception]):
        calls: list[int] = []

        def read() -> dict:
            calls.append(1)
            answer = answers[min(len(calls), len(answers)) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        return read, calls

    @staticmethod
    def loaded(stmts: list[Statement]) -> dict:
        return json.loads(dbg(stmts))

    def test_a_stale_first_read_is_retried_and_the_write_stands(
        self, tmp_path: Path, cfg: Path, pauses: list[float]
    ) -> None:
        write_cfg(cfg, {"providers": PROVIDERS})
        stale, fresh = self.loaded([]), self.loaded([A, B])
        read, calls = self.sequence([stale, stale, stale, fresh])  # before, after, after, after
        state, result = run_apply(tmp_path, [A, B], reader=read)
        assert result.changed and len(calls) == 4
        assert pauses == [0.25, 0.5]
        assert [p["resource"] for p in json.loads(cfg.read_text())["policies"]] == [
            "shell:aaa *",
            "shell:bbb *",
        ]

    def test_a_read_that_fails_while_the_service_restarts_is_retried_too(
        self, tmp_path: Path, cfg: Path, pauses: list[float]
    ) -> None:
        write_cfg(cfg, {"providers": PROVIDERS})
        read, calls = self.sequence([self.loaded([]), harness_error(), self.loaded([A])])
        run_apply(tmp_path, [A], reader=read)
        assert len(calls) == 3 and pauses == [0.25]

    def test_statements_that_never_appear_still_roll_back_after_the_bounded_wait(
        self, tmp_path: Path, cfg: Path, pauses: list[float]
    ) -> None:
        write_cfg(cfg, {"providers": PROVIDERS})
        before = cfg.read_bytes()
        read, calls = self.sequence([self.loaded([])])
        with pytest.raises(IdentityError) as exc:
            run_apply(tmp_path, [A], reader=read)
        assert exc.value.code == E_POLICIES_MISSING
        assert cfg.read_bytes() == before
        assert len(calls) == 1 + configwrite.VERIFY_ATTEMPTS
        assert pauses == [0.25, 0.5, 1.0, 2.0]

    def test_a_lost_provider_is_rolled_back_after_the_same_wait(
        self, tmp_path: Path, cfg: Path, pauses: list[float]
    ) -> None:
        write_cfg(cfg, {"providers": PROVIDERS})
        before = cfg.read_bytes()
        broken = {"providers": {}, "policies": as_json([A])}
        read, _calls = self.sequence([self.loaded([A]), broken])
        with pytest.raises(IdentityError):
            run_apply(tmp_path, [A], reader=read)
        assert cfg.read_bytes() == before and len(pauses) == 4

    def test_a_first_good_read_does_not_wait(
        self, tmp_path: Path, cfg: Path, pauses: list[float]
    ) -> None:
        write_cfg(cfg, {"providers": PROVIDERS})
        read, calls = self.sequence([self.loaded([]), self.loaded([A])])
        run_apply(tmp_path, [A], reader=read)
        assert len(calls) == 2 and pauses == []

    def test_a_read_that_always_fails_after_the_write_rolls_back(
        self, tmp_path: Path, cfg: Path, pauses: list[float]
    ) -> None:
        write_cfg(cfg, {"providers": PROVIDERS})
        before = cfg.read_bytes()
        read, _calls = self.sequence([self.loaded([]), harness_error()])
        with pytest.raises(configwrite.PolicyWriteError, match="rolled back"):
            run_apply(tmp_path, [A], reader=read)
        assert cfg.read_bytes() == before and len(pauses) == 4


def harness_error() -> Exception:
    from carter.harness import DebugConfigError

    return DebugConfigError("`opencode debug config` exited 1")
