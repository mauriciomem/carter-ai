"""``carter check --host``: the two network checks overlap, the output order does not change,
and the user is told before the wait. No real network: the checks are replaced by fakes."""

from __future__ import annotations

import sys
import threading

import pytest
from click.testing import CliRunner

from carter import hostcheck
from carter.checkitems import Item
from carter.cli import main


def _run() -> list[Item]:
    return hostcheck.run_host_checks(reader=lambda: {"providers": {}, "policies": []})


def _areas(items: list[Item]) -> list[str]:
    return [i.area for i in items]


def test_the_token_and_identity_checks_run_at_the_same_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each fake waits for the other: run one after the other, the barrier breaks and the
    # check reports "could not run" instead of its item.
    meet = threading.Barrier(2, timeout=10)

    def token(_base):
        meet.wait()
        return [Item("ok", "token", "checked")]

    def identity(*_args):
        meet.wait()
        return [Item("ok", "identity", "checked")]

    monkeypatch.setattr(hostcheck, "_token", token)
    monkeypatch.setattr(hostcheck, "_identity", identity)
    items = _run()
    assert [i.text for i in items if i.area in ("token", "identity")] == ["checked", "checked"]
    assert not [i for i in items if i.level == "red"]


def test_the_output_order_is_the_serial_one(monkeypatch: pytest.MonkeyPatch) -> None:
    release_token = threading.Event()

    def token(_base):  # slower than identity on purpose
        release_token.wait(timeout=10)
        return [Item("ok", "token", "t")]

    def identity(*_args):
        release_token.set()
        return [Item("ok", "identity", "i")]

    monkeypatch.setattr(hostcheck, "_token", token)
    monkeypatch.setattr(hostcheck, "_identity", identity)
    areas = _areas(_run())
    # as when they ran one after the other: local checks, identity, token, the server check
    assert areas.index("guard") < areas.index("identity") < areas.index("token")
    assert areas.index("token") < areas.index("server environment")


def test_one_failing_check_reports_its_own_row_and_hides_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def token(_base):
        raise TimeoutError("GitHub did not answer")

    monkeypatch.setattr(hostcheck, "_token", token)
    monkeypatch.setattr(hostcheck, "_identity", lambda *_a: [Item("ok", "identity", "fine")])
    items = _run()
    assert Item("red", "token", "check could not run (TimeoutError)") in items
    assert Item("ok", "identity", "fine") in items
    assert "server environment" in _areas(items)  # the checks after it still ran


def test_the_notice_is_on_stderr_before_the_checks_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed_by_then: list[bytes] = []

    def fake_checks(**_kwargs):
        sys.stderr.flush()
        printed_by_then.append(sys.stderr.buffer.getvalue())  # type: ignore[attr-defined]
        return [Item("ok", "versions", "fine")]

    monkeypatch.setattr(hostcheck, "live_readers", dict)
    monkeypatch.setattr(hostcheck, "run_host_checks", fake_checks)
    result = CliRunner().invoke(main, ["check", "--host"])
    assert printed_by_then == [b"checking GitHub...\n"]
    assert result.stdout == "\u2713 host\n"  # the report is unchanged and alone on stdout
