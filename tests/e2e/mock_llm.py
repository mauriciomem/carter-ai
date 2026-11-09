#!/usr/bin/env python3
"""Scripted OpenAI-compatible mock model for the e2e suite. Loopback only, no credentials.

The log directory and the port are arguments, and the prompt grammar is a pure function
(``parse_directive``) so it has unit tests that need no OpenCode.

Usage: ``mock_llm.py <port> <logdir>``

Prompt grammar (the first matching line of the last user message wins):

    RUN <command>                -> one ``shell`` tool call
    RUNPAR <cmd1> ::: <cmd2>     -> several ``shell`` calls in ONE assistant message
    CALL <tool> <json>           -> a call to the tool named <tool> (or ending with it)
    FORCE <tool> <json>          -> a call to <tool> even when it is NOT in the tool list (a model
                                    that remembers a tool OpenCode did not offer it)
    TASK <rest>                  -> a ``subagent`` call (agent=general) whose prompt is <rest>
    TASKAS <agent> <rest>        -> the same with a named agent devops as a subagent)
    anything else                -> the text "ok"

When the last message is a tool result the mock answers with the text "done".

Logs written to ``<logdir>`` (names and tool output only, never a credential):
``requests.jsonl`` (proof that the mock, and nothing else, served the model),
``results.jsonl`` (every tool result the model got back), ``tools.json`` (the tool schema
list of the first request that carried tools).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SHELL_TOOL = "shell"
SUBAGENT_TOOL = "subagent"
PAR_SEPARATOR = " ::: "


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


def text_of(content: Any) -> str:
    """Plain text of an OpenAI message ``content`` (string or list of parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _shell_call(command: str) -> ToolCall:
    return ToolCall(SHELL_TOOL, {"command": command, "description": "e2e"})


def parse_directive(prompt: str, tool_names: list[str]) -> list[ToolCall]:
    """Turn the user prompt into the tool calls the mock should emit (empty = just text)."""
    for raw in prompt.split("\n"):
        line = raw.strip().strip('"')
        if line.startswith("RUNPAR ") and SHELL_TOOL in tool_names:
            return [_shell_call(c.strip()) for c in line[7:].split(PAR_SEPARATOR)]
        if line.startswith("RUN ") and SHELL_TOOL in tool_names:
            return [_shell_call(line[4:])]
        if line.startswith("CALL "):
            name, _, payload = line[5:].partition(" ")
            real = next((t for t in tool_names if t == name or t.endswith(name)), None)
            if real:
                return [ToolCall(real, json.loads((payload or "{}").replace('\\"', '"')))]
        if line.startswith("FORCE "):
            name, _, payload = line[6:].partition(" ")
            return [ToolCall(name, json.loads((payload or "{}").replace('\\"', '"')))]
        if line.startswith("TASKAS ") and SUBAGENT_TOOL in tool_names:
            agent, _, rest = line[7:].partition(" ")
            return [ToolCall(SUBAGENT_TOOL, {"agent": agent, "description": "e2e", "prompt": rest})]
        if line.startswith("TASK ") and SUBAGENT_TOOL in tool_names:
            return [
                ToolCall(
                    SUBAGENT_TOOL, {"agent": "general", "description": "e2e", "prompt": line[5:]}
                )
            ]
    return []


class _State:
    def __init__(self, logdir: Path) -> None:
        self.logdir = logdir
        self.lock = threading.Lock()
        self.tools_saved = False
        self.calls: dict[str, dict[str, Any]] = {}
        self.counter = 0

    def log(self, name: str, obj: Any) -> None:
        with self.lock, open(self.logdir / name, "a") as f:
            f.write(json.dumps(obj) + "\n")

    def next_id(self) -> str:
        with self.lock:
            self.counter += 1
            return f"call_{int(time.time() * 1000)}_{self.counter}"


def make_handler(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # silence the default stderr logging
            pass

        def _json(self, code: int, obj: Any) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.rstrip("/").endswith("/models"):
                self._json(200, {"object": "list", "data": [{"id": "mock-1", "object": "model"}]})
            else:
                self._json(404, {})

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            msgs = body.get("messages", [])
            tools = body.get("tools") or []
            names = sorted({t.get("function", {}).get("name") for t in tools})
            state.log(
                "requests.jsonl",
                {
                    "t": time.time(),
                    "path": self.path,
                    "model": body.get("model"),
                    "n_msgs": len(msgs),
                    "tools": names,
                },
            )
            if tools and not state.tools_saved:
                state.tools_saved = True
                (state.logdir / "tools.json").write_text(json.dumps(tools, indent=1))
            calls: list[ToolCall] = []
            reply = "ok"
            if msgs and msgs[-1].get("role") == "tool":
                trailing = []
                for m in reversed(msgs):  # every tool message after the last non-tool one
                    if m.get("role") != "tool":
                        break
                    trailing.append(m)
                for m in reversed(trailing):  # oldest first
                    state.log(
                        "results.jsonl",
                        {
                            "call": state.calls.get(m.get("tool_call_id")),
                            "result": text_of(m.get("content"))[:2500],
                        },
                    )
                reply = "done"
            else:
                user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
                prompt = text_of(user.get("content")).strip() if user else ""
                calls = parse_directive(prompt, [n for n in names if n])
            ids = [state.next_id() for _ in calls]
            for cid, call in zip(ids, calls, strict=True):
                state.calls[cid] = {"name": call.name, "args": call.arguments}
            self._respond(bool(body.get("stream")), list(zip(ids, calls, strict=True)), reply)

        def _respond(self, stream: bool, calls: list[tuple[str, ToolCall]], reply: str) -> None:
            usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
            wire = [
                {
                    "id": cid,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for cid, c in calls
            ]
            if not stream:
                msg: dict[str, Any] = {"role": "assistant", "content": None if wire else reply}
                if wire:
                    msg["tool_calls"] = wire
                return self._json(
                    200,
                    {
                        "id": "chatcmpl-mock",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "mock-1",
                        "choices": [
                            {
                                "index": 0,
                                "message": msg,
                                "finish_reason": "tool_calls" if wire else "stop",
                            }
                        ],
                        "usage": usage,
                    },
                )
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()

            def send(obj: Any) -> None:
                data = (
                    "data: " + (obj if isinstance(obj, str) else json.dumps(obj)) + "\n\n"
                ).encode()
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

            def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
                return {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "mock-1",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }

            if wire:
                streamed = [dict(w, index=i) for i, w in enumerate(wire)]
                send(chunk({"role": "assistant", "content": None, "tool_calls": streamed}))
                send(chunk({}, "tool_calls"))
            else:
                send(chunk({"role": "assistant", "content": reply}))
                send(chunk({}, "stop"))
            send(
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "mock-1",
                    "choices": [],
                    "usage": usage,
                }
            )
            send("[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    return Handler


def serve(port: int, logdir: Path) -> None:
    logdir.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(_State(logdir))).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]), Path(sys.argv[2]))
