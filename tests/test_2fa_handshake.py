"""
The daemon↔app handshake for verification codes.

The daemon has no UI. When iCloud demands a 2FA/2SA code it publishes a request
marker and blocks until a code appears. The menu bar app (TwoFactorWatcher)
watches for that marker, prompts, and writes the code back. These tests cover
the daemon half of the contract the Swift side depends on.
"""
import json
import os
import stat
import threading

import pytest

from icloud_sync import auth


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Redirect the marker/code files into a temp dir and silence notifications."""
    request = tmp_path / "request"
    code = tmp_path / "code"
    monkeypatch.setattr(auth, "_REQUEST_PATH", request)
    monkeypatch.setattr(auth, "_CODE_PATH", code)
    monkeypatch.setattr(auth, "notify", lambda *a, **k: None)
    return request, code


def _write_code_like_the_app(code_path, code):
    """Mirror TwoFactorWatcher.writeCode: 0600 temp file renamed into place."""
    tmp = code_path.with_name(code_path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(code)
    os.replace(tmp, code_path)


# --------------------------------------------------------------------------- #
# The request marker
# --------------------------------------------------------------------------- #

def test_request_marker_describes_the_waiting_daemon(paths):
    request, _ = paths
    auth._publish_code_request("2fa")

    payload = json.loads(request.read_text())
    assert payload["kind"] == "2fa"
    # The app uses pid + started to ignore markers from a dead/timed-out daemon.
    assert payload["pid"] == os.getpid()
    assert payload["started"] > 0
    assert payload["timeout"] == auth._CODE_WAIT_TIMEOUT


def test_request_marker_is_not_world_readable(paths):
    request, _ = paths
    auth._publish_code_request("2fa")
    assert stat.S_IMODE(request.stat().st_mode) == 0o600


def test_request_marker_kind_distinguishes_2sa(paths):
    request, _ = paths
    auth._publish_code_request("2sa")
    assert json.loads(request.read_text())["kind"] == "2sa"


# --------------------------------------------------------------------------- #
# Waiting for the code
# --------------------------------------------------------------------------- #

def test_wait_returns_code_written_by_the_app(paths, monkeypatch):
    request, code_path = paths
    monkeypatch.setattr(auth, "_CODE_POLL_INTERVAL", 0.01)

    result = {}

    def daemon_side():
        result["code"] = auth._wait_for_code_file("2fa")

    t = threading.Thread(target=daemon_side)
    t.start()

    # Stand in for the app: wait for the marker, then answer it.
    for _ in range(500):
        if request.exists():
            break
        threading.Event().wait(0.01)
    assert request.exists(), "daemon never published a request marker"

    _write_code_like_the_app(code_path, "123456")
    t.join(timeout=10)

    assert result["code"] == "123456"
    assert not code_path.exists(), "code file must be consumed, not left on disk"
    assert not request.exists(), "marker must be cleared once the code arrives"


def test_wait_ignores_an_empty_code_file(paths, monkeypatch):
    request, code_path = paths
    monkeypatch.setattr(auth, "_CODE_POLL_INTERVAL", 0.01)

    result = {}

    def daemon_side():
        result["code"] = auth._wait_for_code_file("2fa")

    t = threading.Thread(target=daemon_side)
    t.start()
    for _ in range(500):
        if request.exists():
            break
        threading.Event().wait(0.01)

    _write_code_like_the_app(code_path, "")
    threading.Event().wait(0.1)
    assert "code" not in result, "an empty file must not end the wait"

    _write_code_like_the_app(code_path, "654321")
    t.join(timeout=10)
    assert result["code"] == "654321"


def test_wait_clears_the_marker_on_timeout(paths, monkeypatch):
    """A marker left behind would make the app prompt for a long-dead code."""
    request, _ = paths
    monkeypatch.setattr(auth, "_CODE_WAIT_TIMEOUT", 0)
    monkeypatch.setattr(auth, "_CODE_POLL_INTERVAL", 0.01)

    with pytest.raises(SystemExit) as exc:
        auth._wait_for_code_file("2fa")

    assert exc.value.code == 1
    assert not request.exists()


def test_wait_starts_from_a_clean_slate(paths, monkeypatch):
    """A stale code left by an earlier run must not be accepted as an answer."""
    request, code_path = paths
    code_path.write_text("000000")
    monkeypatch.setattr(auth, "_CODE_WAIT_TIMEOUT", 0)
    monkeypatch.setattr(auth, "_CODE_POLL_INTERVAL", 0.01)

    with pytest.raises(SystemExit):
        auth._wait_for_code_file("2fa")

    assert not code_path.exists()


def test_wait_survives_an_unwritable_marker_path(paths, monkeypatch):
    """Publishing is best-effort: a hand-written code must still work."""
    request, code_path = paths
    monkeypatch.setattr(auth, "_REQUEST_PATH", request / "unwritable" / "request")
    monkeypatch.setattr(auth, "_CODE_WAIT_TIMEOUT", 0)
    monkeypatch.setattr(auth, "_CODE_POLL_INTERVAL", 0.01)

    # Reaches the wait loop and exits on timeout rather than crashing on OSError.
    with pytest.raises(SystemExit):
        auth._wait_for_code_file("2fa")
