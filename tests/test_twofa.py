"""
Daemon-mode 2FA handshake with the menu bar app.

The daemon cannot show a window, so it publishes a small state file the
Swift app polls; the app shows a native code dialog and writes the code to
the code file; the daemon picks it up. The state file must be gone once the
code has been consumed, and must say "failed" (with a reason) on give-up so
the app can tell the user instead of silently stopping.
"""
import json

import pytest

from icloud_sync import twofa


@pytest.fixture
def paths(tmp_path, monkeypatch):
    state = tmp_path / "cfg" / "2fa_state.json"
    code = tmp_path / "code"
    monkeypatch.setattr(twofa, "STATE_FILE", state)
    monkeypatch.setattr(twofa, "CODE_FILE", code)
    twofa._cancelled.clear()
    return state, code


def test_wait_for_code_stops_on_cancel_without_failed_state(paths, monkeypatch):
    """SIGTERM during the wait must not leave a zombie sleeping out the timeout."""
    state, _ = paths
    twofa.request_code()
    monkeypatch.setattr(twofa.time, "sleep", lambda _: twofa.cancel())

    assert twofa.wait_for_code(timeout=300, poll=2) is None
    assert not state.exists(), "a cancelled wait is not a failure to report"


def test_request_code_publishes_waiting_state(paths):
    state, code = paths
    code.write_text("stale")

    twofa.request_code(message="Enter the code")

    data = json.loads(state.read_text())
    assert data["status"] == "waiting"
    assert data["message"] == "Enter the code"
    assert isinstance(data["since"], float)
    assert not code.exists(), "a stale code must never be consumed"


def test_wait_for_code_returns_code_and_clears_state(paths, monkeypatch):
    state, code = paths
    twofa.request_code()

    def fake_sleep(_):
        code.write_text(" 123456 \n")

    monkeypatch.setattr(twofa.time, "sleep", fake_sleep)

    assert twofa.wait_for_code(timeout=10, poll=1) == "123456"
    assert not code.exists()
    assert not state.exists()


def test_wait_for_code_times_out_with_failed_state(paths, monkeypatch):
    state, code = paths
    twofa.request_code()
    monkeypatch.setattr(twofa.time, "sleep", lambda _: None)

    assert twofa.wait_for_code(timeout=4, poll=2) is None

    data = json.loads(state.read_text())
    assert data["status"] == "failed"
    assert "timed out" in data["message"].lower()


def test_fail_records_reason(paths):
    state, _ = paths
    twofa.fail("Invalid code")
    data = json.loads(state.read_text())
    assert data == {"status": "failed", "message": "Invalid code"} | {"since": data["since"]}


def test_clear_removes_state(paths):
    state, _ = paths
    twofa.request_code()
    twofa.clear()
    assert not state.exists()
    twofa.clear()  # idempotent
