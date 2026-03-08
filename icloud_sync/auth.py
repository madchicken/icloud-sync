import getpass
import logging
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

    code = _wait_for_code_file()
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

    code = _wait_for_code_file()
    if not api.validate_verification_code(device, code):
        logger.error("2SA code validation failed")
        sys.exit(1)
    logger.info("2SA validated")


def _wait_for_code_file() -> str:
    """Wait for user to write a 2FA code to ~/.icloud_sync_2fa_code."""
    code_path = Path.home() / ".icloud_sync_2fa_code"
    code_path.unlink(missing_ok=True)

    notify("iCloud Sync", f"Enter your 2FA code: echo CODE > {code_path}")
    logger.info("Waiting for 2FA code at %s", code_path)

    for _ in range(150):  # 5 minutes
        if code_path.exists():
            code = code_path.read_text().strip()
            code_path.unlink(missing_ok=True)
            return code
        time.sleep(2)

    logger.error("Timed out waiting for 2FA code")
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
