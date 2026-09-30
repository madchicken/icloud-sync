"""
Daemon-mode two-factor handshake with the menu bar app.

The daemon has no window of its own, so when iCloud asks for a verification
code it publishes STATE_FILE ({"status": "waiting", ...}); the Swift app polls
that file, shows a native code dialog and writes the code to CODE_FILE. The
daemon consumes CODE_FILE and removes STATE_FILE. On give-up the daemon
leaves {"status": "failed", "message": ...} so the app can tell the user why.

CODE_FILE also works by hand:  echo CODE > ~/.icloud_sync_2fa_code
"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path.home() / ".config" / "icloud_sync" / "2fa_state.json"
CODE_FILE = Path.home() / ".icloud_sync_2fa_code"

# Set by the daemon's signal handler so a pending wait_for_code() returns
# promptly instead of sleeping out its timeout with SIGTERM already delivered.
_cancelled = threading.Event()


def cancel() -> None:
    _cancelled.set()


def _write_state(status: str, message: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"status": status, "message": message, "since": time.time()})
    )


def request_code(message: str = "") -> None:
    """Announce that a verification code is needed. Drops any stale code."""
    CODE_FILE.unlink(missing_ok=True)
    _write_state("waiting", message)


def fail(message: str) -> None:
    """Record why 2FA could not be completed (the app shows this to the user)."""
    _write_state("failed", message)


def clear() -> None:
    STATE_FILE.unlink(missing_ok=True)


def wait_for_code(timeout: float = 300, poll: float = 2) -> Optional[str]:
    """
    Block until CODE_FILE appears (returns its contents, stripped), `timeout`
    seconds pass (returns None, leaving a "failed" state behind), or cancel()
    is called (returns None, state cleared).
    """
    logger.info("Waiting for 2FA code at %s", CODE_FILE)
    deadline = time.monotonic() + timeout
    while True:
        if CODE_FILE.exists():
            code = CODE_FILE.read_text().strip()
            CODE_FILE.unlink(missing_ok=True)
            clear()
            return code
        if _cancelled.is_set():
            logger.info("2FA wait cancelled")
            clear()
            return None
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)

    logger.error("Timed out waiting for 2FA code")
    fail("Timed out waiting for the verification code. Start the daemon again to retry.")
    return None
