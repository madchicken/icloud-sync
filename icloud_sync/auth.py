import logging
import subprocess
import sys
from typing import Optional

import keyring
from pyicloud import PyiCloudService
from pyicloud.exceptions import (
    PyiCloudAPIResponseException,
    PyiCloudFailedLoginException,
)

from . import twofa
from .config import SESSION_DIR

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
            cookie_directory=str(SESSION_DIR),
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
# Daemon-mode 2FA/2SA: ask the menu bar app for the code (see twofa.py)
# ---------------------------------------------------------------------------

_MAX_CODE_ATTEMPTS = 3


def _handle_2fa_daemon(api: PyiCloudService) -> None:
    notify("iCloud Sync", "Two-factor authentication required — check your device")
    logger.info("Two-factor authentication required")

    if api.security_key_names:
        msg = f"Security key required ({', '.join(api.security_key_names)}); not supported by the daemon."
        logger.error(msg)
        twofa.fail(msg)
        sys.exit(1)

    # pyicloud already requested a code while logging in. After a rejected code
    # its challenge state is cleared, so each retry asks Apple for a fresh one.
    def resend() -> None:
        try:
            api.request_2fa_code()
        except PyiCloudAPIResponseException as e:
            logger.warning("Could not request a new 2FA code: %s", e)

    _collect_and_validate(api.validate_2fa_code, _2fa_prompt(api), resend)
    logger.info("2FA validated")


def _2fa_prompt(api: PyiCloudService) -> str:
    method = getattr(api, "two_factor_delivery_method", "unknown")
    if method == "sms":
        return "Enter the verification code Apple sent you by SMS."
    return "Enter the verification code shown on your Apple devices."


def _handle_2sa_daemon(api: PyiCloudService) -> None:
    notify("iCloud Sync", "Two-step authentication required — check your devices")
    logger.info("Two-step authentication required")

    devices = api.trusted_devices
    if not devices:
        logger.error("No trusted devices available for 2SA")
        twofa.fail("No trusted devices available for two-step authentication.")
        sys.exit(1)

    device = devices[0]

    def resend() -> None:
        if not api.send_verification_code(device):
            logger.warning("Apple refused to resend the verification code")

    if not api.send_verification_code(device):
        logger.error("Failed to send verification code")
        twofa.fail("Apple refused to send a verification code to your trusted device.")
        sys.exit(1)

    _collect_and_validate(
        lambda code: api.validate_verification_code(device, code),
        "Enter the verification code sent to your trusted device.",
        resend,
    )
    logger.info("2SA validated")


def _collect_and_validate(validate, prompt: str, resend) -> None:
    """
    Ask the app for a code, up to _MAX_CODE_ATTEMPTS times; exit on give-up.
    `resend` is called before every retry so the user gets a fresh code.
    """
    message = prompt
    for attempt in range(1, _MAX_CODE_ATTEMPTS + 1):
        if attempt > 1:
            resend()
        twofa.request_code(message)
        notify("iCloud Sync", f"Enter your verification code (or: echo CODE > {twofa.CODE_FILE})")
        code = twofa.wait_for_code()
        if code is None:
            sys.exit(1)  # wait_for_code already recorded the failure
        try:
            accepted = validate(code)
        except PyiCloudAPIResponseException as e:
            logger.warning("Verification request failed: %s", e)
            accepted = False
        if accepted:
            return
        logger.warning("Verification code rejected (attempt %d/%d)", attempt, _MAX_CODE_ATTEMPTS)
        message = f"That code was not accepted (attempt {attempt}/{_MAX_CODE_ATTEMPTS}). A new one was requested. {prompt}"

    logger.error("2FA code validation failed")
    twofa.fail("The verification code was rejected too many times. Start the daemon again to retry.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Interactive setup helpers (used by cli.py)
# ---------------------------------------------------------------------------

def interactive_authenticate(username: str, password: str) -> PyiCloudService:
    """
    Authenticate interactively (used during setup). Handles 2FA/2SA via stdin.
    """
    try:
        api = PyiCloudService(
            apple_id=username, password=password, cookie_directory=str(SESSION_DIR)
        )
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
