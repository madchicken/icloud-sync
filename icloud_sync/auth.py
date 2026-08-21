import getpass
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import keyring
from pyicloud import PyiCloudService
from pyicloud.exceptions import PyiCloudFailedLoginException

logger = logging.getLogger(__name__)

# Same service name as pyicloud so credentials are cross-compatible
_KEYRING_SERVICE = "pyicloud://icloud-password"

# The daemon has no UI. When it needs a 2FA/2SA code it publishes a request
# marker and blocks until the code appears in _CODE_PATH. The menu bar app
# watches for the marker (see UI/TwoFactorWatcher.swift), prompts the user, and
# writes the code back.
_REQUEST_PATH = Path.home() / ".icloud_sync_2fa_request"
_CODE_PATH = Path.home() / ".icloud_sync_2fa_code"
_CODE_WAIT_TIMEOUT = 600  # seconds — generous, the prompt is user-driven
_CODE_POLL_INTERVAL = 2


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------

def get_password(username: str) -> Optional[str]:
    return keyring.get_password(_KEYRING_SERVICE, username)


def store_password(username: str, password: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, username, password)


def delete_password(username: str) -> None:
    try:
        keyring.delete_password(_KEYRING_SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        pass


# ---------------------------------------------------------------------------
# macOS notification
# ---------------------------------------------------------------------------

def notify(title: str, message: str) -> None:
    script = f'display notification "{message}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    except Exception:
        logger.warning("Could not send macOS notification")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate(username: str, session_refresh_interval: int = 300) -> PyiCloudService:
    """
    Authenticate with iCloud using credentials stored in the macOS Keychain.
    Run `icloud-sync setup` once to store credentials before starting the daemon.
    """
    password = get_password(username)
    if not password:
        logger.error(
            "No password found in keychain for %s. Run `icloud-sync setup` first.", username
        )
        notify("iCloud Sync", "No credentials found — run: icloud-sync setup")
        sys.exit(1)

    logger.info("Authenticating with iCloud as %s", username)
    try:
        api = PyiCloudService(
            apple_id=username,
            password=password,
            refresh_interval=session_refresh_interval,
        )
    except PyiCloudFailedLoginException as e:
        logger.error("Login failed: %s", e)
        notify("iCloud Sync", "Login failed — run: icloud-sync setup")
        sys.exit(1)

    # pyicloud reports requires_2fa whenever the session is untrusted, including
    # when a stored session token still validates. On that path it never performs
    # a fresh login, so Apple issues no challenge and sends no code — prompting
    # would ask for a code that cannot exist. Trusting the session clears the
    # requirement outright; only a live challenge earns a prompt.
    if (api.requires_2fa or api.requires_2sa) and not _has_pending_challenge(api):
        logger.info("2FA flagged with no code in flight — trusting session instead")
        if api.trust_session():
            logger.info("Session trusted; no verification code needed")
        else:
            logger.info("Session could not be trusted — asking Apple for a code")
            try:
                api.authenticate(force_refresh=True)
            except PyiCloudFailedLoginException as e:
                logger.error("Re-authentication failed: %s", e)
                notify("iCloud Sync", "Login failed — run: icloud-sync setup")
                sys.exit(1)

    if api.requires_2fa:
        _handle_2fa_daemon(api)
    elif api.requires_2sa:
        _handle_2sa_daemon(api)

    if not api.is_trusted_session:
        logger.info("Trusting session...")
        if not api.trust_session():
            logger.warning("Could not trust session; may be prompted again soon")

    logger.info("Authentication successful")
    return api


def _has_pending_challenge(api: PyiCloudService) -> bool:
    """
    True when Apple has actually issued a verification challenge.

    pyicloud fills _auth_data only when a fresh password login is answered with
    "2FA required", and that same exchange is what makes Apple send the code. So
    an empty _auth_data means no code is in flight and there is nothing for the
    user to type. pyicloud exposes no public accessor for this.
    """
    return bool(getattr(api, "_auth_data", None))


# ---------------------------------------------------------------------------
# Daemon-mode 2FA/2SA: wait for code written to a file
# ---------------------------------------------------------------------------

def _handle_2fa_daemon(api: PyiCloudService) -> None:
    notify("iCloud Sync", "Two-factor authentication required — check your device")
    logger.info("Two-factor authentication required")

    if api.security_key_names:
        logger.error(
            "Security key required (%s). Cannot handle in daemon mode.",
            ", ".join(api.security_key_names),
        )
        sys.exit(1)

    code = _wait_for_code_file("2fa")
    if not api.validate_2fa_code(code):
        logger.error("2FA code validation failed")
        sys.exit(1)
    logger.info("2FA validated")


def _handle_2sa_daemon(api: PyiCloudService) -> None:
    notify("iCloud Sync", "Two-step authentication required — check your devices")
    logger.info("Two-step authentication required")

    devices = api.trusted_devices
    if not devices:
        logger.error("No trusted devices available for 2SA")
        sys.exit(1)

    device = devices[0]
    if not api.send_verification_code(device):
        logger.error("Failed to send verification code")
        sys.exit(1)

    code = _wait_for_code_file("2sa")
    if not api.validate_verification_code(device, code):
        logger.error("2SA code validation failed")
        sys.exit(1)
    logger.info("2SA validated")


def _publish_code_request(kind: str) -> None:
    """
    Announce that we are blocked waiting for a verification code.

    The menu bar app polls for this marker and prompts the user. The pid and
    start time let it ignore markers left behind by a daemon that has already
    died or timed out.
    """
    payload = json.dumps(
        {
            "kind": kind,
            "pid": os.getpid(),
            "started": time.time(),
            "timeout": _CODE_WAIT_TIMEOUT,
        }
    )
    tmp = _REQUEST_PATH.with_name(_REQUEST_PATH.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(payload)
    os.replace(tmp, _REQUEST_PATH)


def _wait_for_code_file(kind: str = "2fa") -> str:
    """
    Wait for a verification code to appear at ~/.icloud_sync_2fa_code.

    Normally the menu bar app writes it after prompting the user; it can also be
    supplied by hand with `echo CODE > ~/.icloud_sync_2fa_code`.
    """
    _CODE_PATH.unlink(missing_ok=True)

    try:
        _publish_code_request(kind)
    except OSError as e:
        # Without the marker the app cannot prompt, but a hand-written code
        # still works — carry on rather than failing the login outright.
        logger.warning("Could not publish %s code request: %s", kind, e)

    notify("iCloud Sync", "Verification code required — check your Apple devices")
    logger.info(
        "Waiting up to %d minutes for %s code at %s",
        _CODE_WAIT_TIMEOUT // 60,
        kind,
        _CODE_PATH,
    )

    deadline = time.monotonic() + _CODE_WAIT_TIMEOUT
    try:
        while time.monotonic() < deadline:
            if _CODE_PATH.exists():
                code = _CODE_PATH.read_text().strip()
                _CODE_PATH.unlink(missing_ok=True)
                if code:
                    return code
                logger.warning("Ignoring empty code file at %s", _CODE_PATH)
            time.sleep(_CODE_POLL_INTERVAL)
    finally:
        _REQUEST_PATH.unlink(missing_ok=True)

    logger.error("Timed out waiting for %s code", kind)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Interactive setup helpers (used by cli.py)
# ---------------------------------------------------------------------------

def interactive_authenticate(username: str, password: str) -> PyiCloudService:
    """
    Authenticate interactively (used during setup). Handles 2FA/2SA via stdin.
    """
    try:
        api = PyiCloudService(apple_id=username, password=password)
    except PyiCloudFailedLoginException as e:
        print(f"Login failed: {e}", file=sys.stderr)
        sys.exit(1)

    if api.requires_2fa:
        _handle_2fa_interactive(api)
    elif api.requires_2sa:
        _handle_2sa_interactive(api)

    if not api.is_trusted_session:
        print("Trusting session...")
        if not api.trust_session():
            print("Warning: could not trust session.")

    return api


def _handle_2fa_interactive(api: PyiCloudService) -> None:
    if api.security_key_names:
        print(f"Security key required: {', '.join(api.security_key_names)}")
        print("Security key 2FA is not supported in setup mode.")
        sys.exit(1)

    code = input("Two-factor authentication required. Enter the code from your device: ").strip()
    if not api.validate_2fa_code(code):
        print("Invalid code.", file=sys.stderr)
        sys.exit(1)
    print("2FA verified.")


def _handle_2sa_interactive(api: PyiCloudService) -> None:
    devices = api.trusted_devices
    print("Two-step authentication required. Your trusted devices:")
    for i, device in enumerate(devices):
        name = device.get("deviceName") or f"SMS to {device.get('phoneNumber')}"
        print(f"  {i}: {name}")

    idx = int(input("Select device number: ").strip())
    device = devices[idx]

    if not api.send_verification_code(device):
        print("Failed to send verification code.", file=sys.stderr)
        sys.exit(1)

    code = input("Enter the verification code: ").strip()
    if not api.validate_verification_code(device, code):
        print("Invalid code.", file=sys.stderr)
        sys.exit(1)
    print("2SA verified.")
