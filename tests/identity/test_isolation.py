"""The isolation block as data."""

from __future__ import annotations

import copy
import json
import os
import stat
from types import SimpleNamespace

import pytest

from carter.identity import isolation
from carter.identity.errors import IdentityError, registry
from carter.identity.isolation_apply import apply_isolation
from carter.identity.rules import load_rules
from identity import vectors

HOME = "/home/test"
V = vectors.load()


def doc(**kw):
    args = {
        "home": HOME,
        "python_path": "/opt/carter/bin/python",
        "carter_path": "/opt/carter/bin/carter",
        "false_path": "/usr/bin/false",
        **kw,
    }
    return isolation.render(**args)


class TestEnvRows:
    """One test per row of the isolation table."""

    def test_ssh_auth_sock_and_github_token_and_config_parameters_are_deleted(self) -> None:
        assert doc()["env"]["delete"] == ["SSH_AUTH_SOCK", "GITHUB_TOKEN", "GIT_CONFIG_PARAMETERS"]

    def test_git_ssh_command_has_no_identity(self) -> None:
        assert doc()["env"]["set"]["GIT_SSH_COMMAND"] == (
            "ssh -F /dev/null -o IdentityAgent=none -o IdentitiesOnly=yes "
            "-o IdentityFile=/dev/null -o BatchMode=yes"
        )

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("SSH_ASKPASS_REQUIRE", "never"),
            ("GH_CONFIG_DIR", f"{HOME}/.carter/run/gh-empty"),
            ("GH_NO_UPDATE_NOTIFIER", "1"),
            ("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent"),
            ("GIT_TERMINAL_PROMPT", "0"),
            ("GIT_ASKPASS", "/usr/bin/false"),
        ],
    )
    def test_fixed_values(self, name: str, value: str) -> None:
        assert doc()["env"]["set"][name] == value

    def test_gh_token_is_not_in_the_file(self) -> None:
        assert "GH_TOKEN" not in doc()["env"]["set"]
        assert "GH_TOKEN" not in doc()["env"]["delete"]

    def test_isolation_vars_of_the_data_file_are_exactly_what_the_block_touches(self) -> None:
        assert list(load_rules().isolation_vars) == isolation.isolation_vars()
        touched = {*doc()["env"]["set"], *doc()["env"]["delete"], "GH_TOKEN", "GIT_CONFIG_COUNT"}
        assert set(load_rules().isolation_vars) == touched


class TestGitConfig:
    def test_order_is_the_c2_order(self) -> None:
        keys = [k for k, _ in doc()["git_config"]]
        assert keys == [
            "credential.helper",
            "credential.https://github.com.helper",
            "url.https://github.com/.insteadOf",
            "url.https://github.com/.insteadOf",
            "url.no_push://.pushInsteadOf",
            "url.no_push://.pushInsteadOf",
            "url.no_push://.pushInsteadOf",
            "remote.origin.pushurl",
            "commit.gpgsign",
            "gpg.program",
            "gpg.openpgp.program",
            "gpg.x509.program",
            "gpg.ssh.program",
        ]

    def test_the_empty_reset_is_first(self) -> None:
        assert doc()["git_config"][0] == ["credential.helper", ""]

    def test_the_helper_prints_gh_token_and_holds_no_token(self) -> None:
        helper = dict(map(tuple, doc()["git_config"]))["credential.https://github.com.helper"]
        assert '"$GH_TOKEN"' in helper and "x-access-token" in helper
        assert helper.startswith("!f(){") and helper.endswith("; f")

    def test_insteadof_and_no_push_rewrites_for_the_github_forms(self) -> None:
        pairs = [tuple(p) for p in doc()["git_config"]]
        assert ("url.https://github.com/.insteadOf", "git@github.com:") in pairs
        assert ("url.https://github.com/.insteadOf", "ssh://git@github.com/") in pairs
        for form in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
            assert ("url.no_push://.pushInsteadOf", form) in pairs
        assert ("remote.origin.pushurl", "no_push") in pairs

    def test_d51_gpgsign_false_and_all_four_gpg_programs_are_the_resolved_false(self) -> None:
        pairs = dict(map(tuple, doc(false_path="/bin/false")["git_config"]))
        assert pairs["commit.gpgsign"] == "false"
        for key in ("gpg.program", "gpg.openpgp.program", "gpg.x509.program", "gpg.ssh.program"):
            assert pairs[key] == "/bin/false"

    def test_blocking_entries_are_commit_gpgsign_true_and_ssh_format_only(self) -> None:
        assert doc()["blocking_git_config"] == [["commit.gpgsign", "true"], ["gpg.format", "ssh"]]
        assert "gpg.ssh.program" not in [k for k, _ in doc()["blocking_git_config"]]  # stays false

    def test_no_secret_or_token_anywhere(self) -> None:
        text = isolation.canonical_bytes(
            doc(pat_file=f"{HOME}/.carter/secrets/gh-read.token")
        ).decode()
        assert "github_pat_" not in text.replace('"pat_prefix":"github_pat_"', "")
        assert "ghp_" not in text and "password=" not in text.replace("password=%s", "")


class TestPollutionMarkers:
    def test_signals_come_from_the_data_file(self) -> None:
        p = doc()["pollution"]
        assert p["agent_signals"] == list(load_rules().agent_signals)
        assert p["human_signals"] == list(load_rules().human_signals)

    def test_env_markers_are_carters_exact_values_with_the_home_rendered(self) -> None:
        env = {name: (match, value) for name, match, value in doc()["pollution"]["markers"]["env"]}
        assert env["GH_CONFIG_DIR"] == ("equals", f"{HOME}/.carter/run/gh-empty")
        assert env["GIT_SSH_COMMAND"] == ("contains", "IdentityAgent=none")
        assert env["DBUS_SESSION_BUS_ADDRESS"] == ("equals", "unix:path=/nonexistent")

    def test_pair_markers_skip_the_generic_entries(self) -> None:
        pairs = [tuple(p) for p in doc()["pollution"]["markers"]["git_config"]]
        assert ("remote.origin.pushurl", "no_push") in pairs
        assert ("credential.helper", "") not in pairs and ("commit.gpgsign", "false") not in pairs


class TestResolveFalse:
    @staticmethod
    def fake(table: dict[str, tuple[int, int, int]]):
        def stat_fn(path: str):
            if path not in table:
                raise FileNotFoundError(path)
            uid, mode, _ = table[path]
            return SimpleNamespace(st_uid=uid, st_mode=mode, st_dev=_)

        return stat_fn

    REG = stat.S_IFREG

    def test_first_root_owned_candidate(self) -> None:
        table = {"/usr/bin/false": (0, self.REG | 0o755, 0), "/bin/false": (0, self.REG | 0o755, 0)}
        assert isolation.resolve_false(self.fake(table)) == "/usr/bin/false"

    def test_a_macos_layout_without_usr_bin_false_falls_to_bin_false(self) -> None:
        assert (
            isolation.resolve_false(self.fake({"/bin/false": (0, self.REG | 0o755, 0)}))
            == "/bin/false"
        )

    @pytest.mark.parametrize(
        "entry",
        [
            (1000, stat.S_IFREG | 0o755, 0),  # owned by the user
            (0, stat.S_IFREG | 0o775, 0),  # group-writable
            (0, stat.S_IFREG | 0o757, 0),  # world-writable
            (0, stat.S_IFDIR | 0o755, 0),  # not a file
        ],
        ids=["user-owned", "group-writable", "world-writable", "directory"],
    )
    def test_unsuitable_candidates_are_refused_with_the_exact_sentence(self, entry) -> None:
        table = {"/usr/bin/false": entry, "/bin/false": entry}
        with pytest.raises(IdentityError) as exc:
            isolation.resolve_false(self.fake(table))
        assert exc.value.code == "E-FALSE-MISSING"
        assert str(exc.value) == (
            "no root-owned `false` found at /usr/bin/false or /bin/false; "
            "the guards cannot be installed"
        )

    def test_nothing_found_is_refused(self) -> None:
        with pytest.raises(IdentityError):
            isolation.resolve_false(self.fake({}))

    def test_the_real_host_has_one(self) -> None:
        if not any(os.path.exists(p) for p in isolation.FALSE_CANDIDATES):
            pytest.skip("no false on this host")
        assert isolation.resolve_false() in isolation.FALSE_CANDIDATES


class TestSchema:
    def test_the_rendered_document_validates(self) -> None:
        isolation.validate(doc())

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.pop("env"),
            lambda d: d.update(extra=1),
            lambda d: d.update(schema_version=1),  # an old file: plugin and file refuse each other
            lambda d: d.update(schema_version=3),
            lambda d: d["plugin"].update(b_enabled="yes"),
            lambda d: d["plugin"].update(b_git="git"),
            lambda d: d["plugin"].update(b_enabled=True, b_git=""),
            lambda d: d["plugin"].pop("b_caller"),
            lambda d: d.update(schema_version=True),
            lambda d: d["env"].pop("delete"),
            lambda d: d["env"]["set"].update(X=1),
            lambda d: d.update(git_config=[["only-key"]]),
            lambda d: d["pollution"]["markers"].pop("env"),
            lambda d: d["pollution"]["markers"]["env"].append(["a", "b"]),
            lambda d: d["plugin"].update(unknown=1),
            lambda d: d["plugin"].pop("status_dir"),
            lambda d: d["plugin"].update(python_path="python"),
            lambda d: d["plugin"].update(carter_path="relative/carter"),
            lambda d: d["plugin"].update(status_dir="run/plugin-status"),
            lambda d: d["plugin"].update(pat_file="relative"),
            lambda d: d["plugin"].update(declined_groups=["nonsense"]),
            lambda d: d["plugin"].update(self_test_ms=0),
            lambda d: d["plugin"].update(gate_timeout_ms="1000"),
            lambda d: d["plugin"].update(gate_args="-I"),
        ],
    )
    def test_invalid_documents_are_refused(self, mutate) -> None:
        bad = copy.deepcopy(doc())
        mutate(bad)
        with pytest.raises(IdentityError) as exc:
            isolation.validate(bad)
        assert exc.value.code == "E-ISOLATION-MISSING"

    def test_not_an_object_is_refused(self) -> None:
        for value in (None, [], "x", 3):
            with pytest.raises(IdentityError):
                isolation.validate(value)

    def test_declined_groups_are_known_group_names_and_sorted(self) -> None:
        assert doc(declined_groups=("sudo-docker", "config-edit"))["plugin"]["declined_groups"] == [
            "config-edit",
            "sudo-docker",
        ]

    def test_errors_name_keys_never_values(self) -> None:
        bad = doc()
        bad["plugin"]["python_path"] = "relative-secret-looking-value"
        with pytest.raises(IdentityError) as exc:
            isolation.validate(bad)
        assert "relative-secret-looking-value" not in exc.value.detail

    def test_the_message_is_the_registry_text(self) -> None:
        with pytest.raises(IdentityError) as exc:
            isolation.validate({})
        assert str(exc.value) == registry()["E-ISOLATION-MISSING"].message


class TestHash:
    def test_rendering_is_deterministic(self) -> None:
        assert isolation.canonical_bytes(doc()) == isolation.canonical_bytes(doc())

    def test_the_bytes_are_canonical(self) -> None:
        raw = isolation.canonical_bytes(doc())
        assert raw.endswith(b"\n") and b"\n" not in raw[:-1] and b": " not in raw
        assert json.loads(raw) == doc()
        assert list(json.loads(raw)) == sorted(json.loads(raw))

    def test_any_byte_change_changes_the_hash(self) -> None:
        raw = isolation.canonical_bytes(doc())
        base = isolation.sha256_hex(raw)
        assert len(base) == 64
        for i in (0, len(raw) // 2, len(raw) - 1):
            changed = bytearray(raw)
            changed[i] ^= 1
            assert isolation.sha256_hex(bytes(changed)) != base

    def test_golden_document_and_hash_are_the_renderers_output(self) -> None:
        golden = V["isolation"]
        rendered = isolation.render(
            home=HOME,
            python_path="/opt/carter/bin/python",
            carter_path="/opt/carter/bin/carter",
            false_path="/usr/bin/false",
            pat_file=f"{HOME}/.carter/secrets/gh-read.token",
            declined_groups=("sudo-docker",),
        )
        assert rendered == golden["doc"]
        assert isolation.sha256_hex(isolation.canonical_bytes(rendered)) == golden["sha256"]

    def test_the_golden_hash_changed_once_for_slice_b_schema_2(self) -> None:
        """schema 2 adds the plugin keys of the broker tools, so the hash moved from
        the old value exactly once; it is re-rendered with the plugin at install."""
        assert V["isolation"]["doc"]["schema_version"] == 2
        assert V["isolation"]["sha256"] != (
            "d5456e7d8b82dd91b901cc3ade43fb8dbeecd0bfcbe32556f754797782a40a6e"
        )

    def test_the_broker_keys_default_to_off(self) -> None:
        plugin = V["isolation"]["doc"]["plugin"]
        assert (plugin["b_enabled"], plugin["b_git"], plugin["b_gh"]) == (False, "", "")
        assert plugin["b_caller"] == "carter-devops"
        assert plugin["broker_args"] == ["-I", "-m", "carter.broker_cli"]


class TestApplyOracle:
    @pytest.mark.parametrize("case", V["isolation"]["apply"], ids=lambda c: c["name"])
    def test_golden_cases(self, case: dict) -> None:
        got = apply_isolation(
            case["env"], V["isolation"]["doc"], case["pat"], block_commits=case["block_commits"]
        )
        assert got.env == case["expect_env"]
        assert got.flags == case["expect_flags"]

    def test_the_input_is_not_modified(self) -> None:
        env = {"SSH_AUTH_SOCK": "/x", "GIT_CONFIG_COUNT": "abc"}
        before = dict(env)
        apply_isolation(env, V["isolation"]["doc"], None)
        assert env == before

    def test_the_token_never_lands_in_a_config_value(self) -> None:
        pat = "github_pat_TEST-SENTINEL"
        got = apply_isolation({}, V["isolation"]["doc"], pat)
        assert got.env["GH_TOKEN"] == pat
        assert not [k for k, v in got.env.items() if k.startswith("GIT_CONFIG_VALUE_") and pat in v]
        assert not [k for k, v in got.env.items() if k != "GH_TOKEN" and pat in v]
