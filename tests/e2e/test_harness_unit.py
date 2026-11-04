"""Unit tests for the e2e harness (plan 004, step 2). None of them starts OpenCode."""

from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from e2e import mock_llm
from e2e.harness import (
    MAX_BASE_LEN,
    RigError,
    assert_only_mock,
    check_base_dir,
    env_names,
    free_port,
    isolated_env,
    refuse_real_home,
    render_config,
    secret_in_logs,
)

# --- ports -------------------------------------------------------------------------------


def test_free_port_is_bindable_and_distinct() -> None:
    ports = {free_port() for _ in range(3)}
    assert all(1024 < p < 65536 for p in ports)
    with socket.socket() as s:
        s.bind(("127.0.0.1", next(iter(ports))))


# --- paths -------------------------------------------------------------------------------


def test_base_dir_must_be_short_and_absolute(tmp_path: Path) -> None:
    short = tmp_path / "x"
    short.mkdir()
    ok = Path("/tmp/c2e-abc")
    assert check_base_dir(ok) == ok
    with pytest.raises(RigError, match="relative"):
        check_base_dir(Path("rel/dir"))
    too_long = Path("/tmp/" + "a" * MAX_BASE_LEN)
    with pytest.raises(RigError, match="bytes"):
        check_base_dir(too_long)


def test_base_dir_limit_counts_bytes_not_characters() -> None:
    wide = Path("/tmp/" + "é" * (MAX_BASE_LEN // 2))  # 2 bytes each: short in characters only
    with pytest.raises(RigError, match="bytes"):
        check_base_dir(wide)


def test_refuses_the_real_home_and_anything_inside_it(tmp_path: Path) -> None:
    real = tmp_path / "realhome"
    real.mkdir()
    with pytest.raises(RigError, match="real home"):
        refuse_real_home(real, real)
    with pytest.raises(RigError, match="real home"):
        refuse_real_home(real / "rig" / "home", real)
    refuse_real_home(tmp_path / "elsewhere", real)  # fine
    # a symlink into the real home is the same place
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(RigError, match="real home"):
        refuse_real_home(link, real)


# --- config and env ----------------------------------------------------------------------


def test_config_names_only_the_mock_provider() -> None:
    cfg = render_config(18290)
    assert cfg["enabled_providers"] == ["mock"]
    assert cfg["model"] == "mock/mock-1"
    assert list(cfg["providers"]) == ["mock"]
    assert cfg["providers"]["mock"]["settings"]["baseURL"] == "http://127.0.0.1:18290/v1"
    json.dumps(cfg)  # serialisable


def test_config_extra_keys_cannot_add_a_provider() -> None:
    with pytest.raises(RigError, match="provider"):
        render_config(1, extra={"providers": {"real": {}}})
    with pytest.raises(RigError, match="provider"):
        render_config(1, extra={"enabled_providers": ["mock", "opencode"]})
    assert render_config(1, extra={"plugins": ["./p"]})["plugins"] == ["./p"]


def test_isolated_env_is_built_from_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "AGENT",
        "OPENCODE_SESSION_ID",
        "SSH_AUTH_SOCK",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "CARTER_AGENT_SHELL",
    ):
        monkeypatch.setenv(name, "inherited")
    env = isolated_env(tmp_path, bin_dir="/opt/oc/bin", password="pw-not-printed")
    assert env["HOME"] == str(tmp_path / "home")
    for xdg in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        assert env[xdg].startswith(str(tmp_path / "home"))
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["OPENCODE_SERVER_PASSWORD"] == "pw-not-printed"
    assert env["PATH"].startswith("/opt/oc/bin:")
    leaked = {
        "AGENT",
        "OPENCODE_SESSION_ID",
        "SSH_AUTH_SOCK",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "CARTER_AGENT_SHELL",
    }
    assert leaked.isdisjoint(env)
    assert not [k for k in env if k.startswith(("OPENCODE_CONFIG", "GIT_CONFIG_KEY"))]


def test_env_names_lists_names_never_values() -> None:
    names = env_names({"B": "secret-value", "A": "x"})
    assert names == ["A", "B"]
    assert "secret-value" not in " ".join(names)


# --- provider gate -----------------------------------------------------------------------


def test_provider_gate_accepts_exactly_mock() -> None:
    assert_only_mock(["mock"])
    for bad in ([], ["opencode"], ["mock", "opencode"], ["Mock"]):
        with pytest.raises(RigError, match="providers"):
            assert_only_mock(bad)


# --- log scan ----------------------------------------------------------------------------


def test_secret_in_logs_finds_a_leak_and_ignores_clean_logs(tmp_path: Path) -> None:
    (tmp_path / "a.log").write_text("nothing here\n")
    assert not secret_in_logs(tmp_path, "s3cr3t-value")
    (tmp_path / "b.log").write_text("password=s3cr3t-value\n")
    assert secret_in_logs(tmp_path, "s3cr3t-value")


# --- mock prompt grammar -----------------------------------------------------------------

TOOLS = ["shell", "subagent", "carter_push", "read"]


def test_run_emits_one_shell_call() -> None:
    (call,) = mock_llm.parse_directive("RUN echo ok", TOOLS)
    assert call.name == "shell"
    assert call.arguments["command"] == "echo ok"


def test_run_is_ignored_when_the_model_has_no_shell_tool() -> None:
    assert mock_llm.parse_directive("RUN echo ok", ["read"]) == []


def test_runpar_emits_several_shell_calls_in_one_message() -> None:
    calls = mock_llm.parse_directive("RUNPAR echo a ::: echo b ::: echo c", TOOLS)
    assert [c.arguments["command"] for c in calls] == ["echo a", "echo b", "echo c"]


def test_call_matches_the_tool_name_or_its_suffix() -> None:
    (call,) = mock_llm.parse_directive('CALL push {"ref": "x"}', TOOLS)
    assert (call.name, call.arguments) == ("carter_push", {"ref": "x"})
    assert mock_llm.parse_directive("CALL nosuchtool {}", TOOLS) == []


def test_force_calls_a_tool_that_is_not_in_the_tool_list() -> None:
    (call,) = mock_llm.parse_directive('FORCE carter_gone {"a": 1}', ["shell"])
    assert (call.name, call.arguments) == ("carter_gone", {"a": 1})


def test_task_wraps_the_rest_in_a_subagent_prompt() -> None:
    (call,) = mock_llm.parse_directive("TASK RUN echo child", TOOLS)
    assert call.name == "subagent"
    assert call.arguments["prompt"] == "RUN echo child"


def test_plain_text_and_first_matching_line_wins() -> None:
    assert mock_llm.parse_directive("hello there", TOOLS) == []
    (call,) = mock_llm.parse_directive("intro\nRUN echo first\nRUN echo second", TOOLS)
    assert call.arguments["command"] == "echo first"


def test_text_of_handles_parts_and_strings() -> None:
    assert mock_llm.text_of("a") == "a"
    assert mock_llm.text_of([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "ab"
    assert mock_llm.text_of(None) == ""


# --- the mock server itself (loopback only) ----------------------------------------------


@pytest.fixture
def mock_server(tmp_path: Path):
    logdir = tmp_path / "mocklogs"
    logdir.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock_llm.make_handler(mock_llm._State(logdir)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", logdir
    server.shutdown()
    server.server_close()


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, json.dumps(payload).encode(), {"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


_SHELL_TOOL = {"type": "function", "function": {"name": "shell", "parameters": {}}}


def test_mock_server_answers_a_run_prompt_with_a_tool_call_then_done(mock_server) -> None:
    base, logdir = mock_server
    first = _post(
        f"{base}/v1/chat/completions",
        {
            "model": "mock-1",
            "messages": [{"role": "user", "content": "RUN echo ok"}],
            "tools": [_SHELL_TOOL],
        },
    )
    call = first["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "shell"
    assert json.loads(call["function"]["arguments"])["command"] == "echo ok"
    second = _post(
        f"{base}/v1/chat/completions",
        {
            "model": "mock-1",
            "messages": [
                {"role": "user", "content": "RUN echo ok"},
                {"role": "assistant", "tool_calls": [call]},
                {"role": "tool", "tool_call_id": call["id"], "content": "ok\n"},
            ],
            "tools": [_SHELL_TOOL],
        },
    )
    assert second["choices"][0]["message"]["content"] == "done"
    results = [json.loads(line) for line in (logdir / "results.jsonl").read_text().splitlines()]
    assert results == [
        {
            "call": {"name": "shell", "args": {"command": "echo ok", "description": "e2e"}},
            "result": "ok\n",
        }
    ]
    requests = (logdir / "requests.jsonl").read_text().splitlines()
    assert len(requests) == 2
    assert (logdir / "tools.json").exists()


def test_mock_server_lists_exactly_one_model(mock_server) -> None:
    base, _ = mock_server
    with urllib.request.urlopen(f"{base}/v1/models", timeout=5) as resp:
        assert [m["id"] for m in json.loads(resp.read())["data"]] == ["mock-1"]


def test_taskas_names_the_subagent() -> None:
    (call,) = mock_llm.parse_directive(
        "TASKAS carter-devops FORCE carter_push {}", ["subagent", "shell"]
    )
    assert call.name == "subagent" and call.arguments["agent"] == "carter-devops"
    assert call.arguments["prompt"] == "FORCE carter_push {}"
