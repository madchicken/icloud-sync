"""
macOS menu bar app for managing the iCloud sync daemon.

Provides start/stop, pair management, and log access from the system tray.
"""
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

import rumps

# ---------------------------------------------------------------------------
# Native macOS dialogs via osascript (always visible from menu bar apps)
# ---------------------------------------------------------------------------

def _ask_secure(prompt: str, title: str = "iCloud Sync") -> str | None:
    """Show a native password input dialog (characters are hidden)."""
    prompt = prompt.replace('"', '\\"')
    title = title.replace('"', '\\"')
    script = (
        f'display dialog "{prompt}" with title "{title}" '
        f'default answer "" with hidden answer '
        f'buttons {{"Cancel", "OK"}} default button "OK"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for part in result.stdout.strip().split(", "):
        if part.startswith("text returned:"):
            return part[len("text returned:"):]
    return None


def _ask(prompt: str, default: str = "", title: str = "iCloud Sync") -> str | None:
    """Show a native input dialog. Returns the entered text, or None if cancelled."""
    prompt = prompt.replace('"', '\\"')
    default = default.replace('"', '\\"')
    title = title.replace('"', '\\"')
    script = (
        f'display dialog "{prompt}" with title "{title}" '
        f'default answer "{default}" '
        f'buttons {{"Cancel", "OK"}} default button "OK"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for part in result.stdout.strip().split(", "):
        if part.startswith("text returned:"):
            return part[len("text returned:"):]
    return None


def _notify(title: str, message: str) -> None:
    """Post a macOS notification via osascript — works without a bundle."""
    title = title.replace('"', '\\"')
    message = message.replace('"', '\\"')
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _choose_local_folder(prompt: str = "Select the local folder to sync:") -> str | None:
    """Open the native macOS folder picker. Returns a POSIX path or None if cancelled."""
    prompt = prompt.replace('"', '\\"')
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _choose_from_list(
    items: list[str],
    prompt: str,
    title: str = "iCloud Sync",
) -> str | None:
    """Show a native pick-from-list dialog. Returns the selected string or None."""
    if not items:
        return None
    # Escape and build AppleScript list literal
    escaped = ", ".join('"' + i.replace('"', '\\"') + '"' for i in items)
    title = title.replace('"', '\\"')
    prompt = prompt.replace('"', '\\"')
    script = (
        f'choose from list {{{escaped}}} '
        f'with title "{title}" '
        f'with prompt "{prompt}" '
        f'OK button name "Select" cancel button name "Cancel"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    chosen = result.stdout.strip()
    if result.returncode != 0 or chosen == "false":
        return None
    return chosen


def _dialog(
    message: str,
    buttons: list[str],
    title: str = "iCloud Sync",
    default_button: str | None = None,
) -> str | None:
    """
    Show a dialog with arbitrary buttons.
    Returns the clicked button label, or None if the user pressed Escape / cancelled.
    """
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    btns = ", ".join(f'"{esc(b)}"' for b in buttons)
    default = esc(default_button or buttons[-1])
    script = (
        f'display dialog "{esc(message)}" with title "{esc(title)}" '
        f'buttons {{{btns}}} default button "{default}"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for part in result.stdout.strip().split(", "):
        if part.startswith("button returned:"):
            return part[len("button returned:"):]
    return None


def _confirm(message: str, ok_label: str = "OK", title: str = "iCloud Sync") -> bool:
    """Show a native confirmation dialog. Returns True if confirmed."""
    return _dialog(message, ["Cancel", ok_label], title=title, default_button=ok_label) == ok_label


from .config import (
    SyncPair, add_pair, get_pairs, is_daemon_running, load_prefs,
    load_saved_config, read_pid, remove_pair, save_prefs, update_poll_interval,
)

# ---------------------------------------------------------------------------
# Login item (LaunchAgent) helpers
# ---------------------------------------------------------------------------

_LAUNCH_AGENT_LABEL = "com.icloud-sync.tray"
_LAUNCH_AGENT_PLIST = (
    Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCH_AGENT_LABEL}.plist"
)
_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""


def _is_launch_at_login() -> bool:
    return _LAUNCH_AGENT_PLIST.exists()


def _set_launch_at_login(enabled: bool) -> None:
    if enabled:
        executable = shutil.which("icloud-sync-tray") or sys.executable
        _LAUNCH_AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
        _LAUNCH_AGENT_PLIST.write_text(
            _PLIST_TEMPLATE.format(label=_LAUNCH_AGENT_LABEL, executable=executable)
        )
    else:
        try:
            _LAUNCH_AGENT_PLIST.unlink()
        except FileNotFoundError:
            pass


def _is_autostart_daemon() -> bool:
    return load_prefs().get("autostart_daemon", False)

def _find_menubar_icon() -> Path | None:
    """
    Locate the menu bar template image.
    Works both when launched from the .app bundle (Resources/ dir) and
    when run directly from the source tree (assets/ dir).
    """
    from AppKit import NSBundle
    # When running as a .app the Resources path is set by macOS
    bundle_resources = Path(NSBundle.mainBundle().resourcePath())
    candidate = bundle_resources / "menubarTemplate.png"
    if candidate.exists():
        return candidate
    # Fallback: source tree layout
    src = Path(__file__).parent.parent / "assets" / "menubarTemplate.png"
    return src if src.exists() else None

_MENUBAR_ICON = _find_menubar_icon()


class ICloudSyncTray(rumps.App):
    def __init__(self):
        icon = str(_MENUBAR_ICON) if _MENUBAR_ICON is not None else None
        super().__init__("☁" if icon is None else "iCloud Sync",
                         icon=icon, quit_button=None)
        # Mark as template so macOS inverts it automatically in dark mode
        if icon is not None:
            try:
                self._status_item.button().image().setTemplate_(True)
            except Exception:
                pass
        self._proc: subprocess.Popen | None = None

        # Build fixed menu items — structure never changes, only titles/submenus
        self._status_item = rumps.MenuItem("○  Stopped", callback=None)
        self._toggle_item = rumps.MenuItem("▶  Start", callback=self._toggle)
        self._pairs_menu = rumps.MenuItem("Sync Pairs")
        self._pairs_menu.add(rumps.MenuItem("(loading…)"))  # forces NSMenu init
        self._pairings_item = rumps.MenuItem("Pairings…", callback=self._open_pairings)

        self._settings_item = rumps.MenuItem("Settings…", callback=self._open_settings)
        self._setup_item = rumps.MenuItem("Setup / Credentials…", callback=self._open_setup)
        self._log_item = rumps.MenuItem("Open Log", callback=self._open_log)
        self._uninstall_item = rumps.MenuItem("Uninstall…", callback=self._uninstall)
        self._quit_item = rumps.MenuItem("Quit", callback=self._quit)

        self.menu = [
            self._status_item,
            None,
            self._toggle_item,
            None,
            self._pairs_menu,
            self._pairings_item,
            None,
            self._settings_item,
            self._setup_item,
            self._log_item,
            None,
            self._uninstall_item,
            self._quit_item,
        ]

        self._sync_status()
        self._sync_pairs()
        rumps.Timer(self._tick, 5).start()

        # Auto-start daemon if the preference is set and it isn't already running
        if _is_autostart_daemon() and not self._is_running():
            self._start_daemon()

    # -------------------------------------------------------------------------
    # State sync helpers (safe to call from main thread at any time)
    # -------------------------------------------------------------------------

    def _is_running(self) -> bool:
        if self._proc is not None:
            return self._proc.poll() is None
        return is_daemon_running()

    def _sync_status(self):
        """Update only the status and toggle labels — no menu reconstruction."""
        running = self._is_running()
        self._status_item.title = "●  Running" if running else "○  Stopped"
        self._toggle_item.title = "■  Stop" if running else "▶  Start"

    def _sync_pairs(self):
        """Rebuild just the pairs submenu content."""
        self._pairs_menu.clear()
        pairs = get_pairs()
        if pairs:
            for p in pairs:
                label = f"{p.local_dir.name}  ↔  {p.remote_dir}"
                self._pairs_menu.add(rumps.MenuItem(label))
        else:
            self._pairs_menu.add(rumps.MenuItem("(none configured)"))

    # -------------------------------------------------------------------------
    # Timer
    # -------------------------------------------------------------------------

    def _tick(self, _sender):
        if self._proc is not None and self._proc.poll() is not None:
            _notify("iCloud Sync", "Daemon stopped unexpectedly — open the log for details.")
            self._proc = None
        self._sync_status()

    # -------------------------------------------------------------------------
    # Daemon lifecycle
    # -------------------------------------------------------------------------

    def _toggle(self, _sender):
        if self._is_running():
            # Run blocking wait in a background thread so the menu stays responsive
            threading.Thread(target=self._stop_daemon, daemon=True).start()
        else:
            self._start_daemon()
        self._sync_status()

    def _start_daemon(self):
        cmd = self._daemon_cmd()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _notify("iCloud Sync", "Daemon started — syncing in the background…")
        except Exception as e:
            _confirm(f"Failed to start daemon:\n{e}", ok_label="OK")

    def _stop_daemon(self):
        if self._proc is not None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        else:
            pid = read_pid()
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        _notify("iCloud Sync", "Daemon stopped.")
        self._sync_status()

    def _daemon_cmd(self) -> list[str]:
        script = shutil.which("icloud-sync")
        if script:
            return [script, "start"]
        return [sys.executable, "-m", "icloud_sync.sync_daemon"]

    # -------------------------------------------------------------------------
    # Pair management
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Pairings manager
    # -------------------------------------------------------------------------

    def _reload_daemon(self):
        """Send SIGHUP to the running daemon so it picks up config changes."""
        pid = read_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGHUP)
            except ProcessLookupError:
                pass

    def _open_pairings(self, _sender):
        """Loop-based pairings manager: show list → act → refresh until Done."""
        while True:
            pairs = get_pairs()
            if pairs:
                lines = "\n".join(
                    f"  {p.local_dir}  ↔  iCloud Drive / {p.remote_dir}"
                    for p in pairs
                )
                body = f"Configured sync pairs:\n\n{lines}"
                buttons = ["Done", "Remove…", "Add Pair…"]
            else:
                body = "No sync pairs configured yet."
                buttons = ["Done", "Add Pair…"]

            clicked = _dialog(body, buttons, title="Sync Pairings", default_button="Done")

            if clicked == "Add Pair…":
                self._do_add_pair()
                self._reload_daemon()
            elif clicked == "Remove…":
                self._do_remove_pair()
                self._reload_daemon()
            else:
                break  # "Done" or Escape

        self._sync_pairs()

    def _get_icloud_folders(self) -> list[str]:
        """Return top-level iCloud Drive folder names, or [] on any failure."""
        try:
            saved = load_saved_config()
            if not saved:
                return []
            username = saved.get("username")
            if not username:
                return []
            from .auth import get_password
            from pyicloud import PyiCloudService
            password = get_password(username)
            if not password:
                return []
            api = PyiCloudService(username, password)
            if api.requires_2fa or api.requires_2sa:
                return []
            return sorted(api.drive.dir())
        except Exception:
            return []

    def _do_add_pair(self):
        # Step 1 — pick the iCloud Drive folder
        folders = self._get_icloud_folders()
        _MANUAL = "Enter folder name manually…"
        choices = [_MANUAL] + folders

        chosen = _choose_from_list(
            choices,
            prompt="Select the iCloud Drive folder to sync with:",
            title="Add Sync Pair (1/2)",
        )
        if chosen is None:
            return

        if chosen == _MANUAL or not folders:
            remote_dir = _ask(
                "iCloud Drive folder name (will be created if it doesn't exist):",
                default="SyncFolder",
                title="Add Sync Pair (1/2)",
            )
            if not remote_dir or not remote_dir.strip():
                return
            remote_dir = remote_dir.strip()
        else:
            remote_dir = chosen

        # Step 2 — pick the local folder
        local_dir = _choose_local_folder(
            f"Select the local folder to sync with iCloud Drive / {remote_dir}:"
        )
        if not local_dir:
            return

        try:
            add_pair(local_dir, remote_dir)
            _notify("iCloud Sync", f"Pair added: {Path(local_dir).name}  ↔  {remote_dir}")
        except (ValueError, RuntimeError) as e:
            _dialog(f"Error: {e}", ["OK"], title="iCloud Sync")

    def _do_remove_pair(self):
        pairs = get_pairs()
        if not pairs:
            return

        labels = [f"{p.local_dir}  ↔  iCloud Drive / {p.remote_dir}" for p in pairs]
        chosen = _choose_from_list(
            labels,
            prompt="Select the pair to remove:",
            title="Remove Sync Pair",
        )
        if chosen is None:
            return

        try:
            idx = labels.index(chosen)
        except ValueError:
            return
        p = pairs[idx]

        if _confirm(
            f"Remove this sync pair?\n\n"
            f"Local:   {p.local_dir}\n"
            f"Remote:  iCloud Drive / {p.remote_dir}\n\n"
            f"Files will NOT be deleted.",
            ok_label="Remove",
            title="Confirm Removal",
        ):
            remove_pair(p.remote_dir)
            _notify("iCloud Sync", f"Removed: {p.local_dir.name}  ↔  {p.remote_dir}")

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def _open_settings(self, _sender):
        from AppKit import NSAlert, NSApp, NSButton, NSMakeRect, NSTextField, NSView

        saved = load_saved_config() or {}

        # ── Accessory view ──────────────────────────────────────────────────
        VIEW_W, VIEW_H = 310, 116
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, VIEW_W, VIEW_H))

        def _label(text, x, y, w=200):
            f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, 20))
            f.setStringValue_(text)
            f.setBezeled_(False)
            f.setDrawsBackground_(False)
            f.setEditable_(False)
            f.setSelectable_(False)
            return f

        def _checkbox(title, x, y, checked):
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, VIEW_W - x, 22))
            btn.setButtonType_(6)   # NSSwitchButton / NSButtonTypeSwitch
            btn.setTitle_(title)
            btn.setState_(1 if checked else 0)
            return btn

        login_cb = _checkbox("Start at Login", 0, VIEW_H - 26, _is_launch_at_login())
        view.addSubview_(login_cb)

        autostart_cb = _checkbox("Auto-start Daemon", 0, VIEW_H - 54, _is_autostart_daemon())
        view.addSubview_(autostart_cb)

        # Horizontal rule (visual separator via a thin box)
        sep = NSTextField.alloc().initWithFrame_(NSMakeRect(0, VIEW_H - 66, VIEW_W, 1))
        sep.setBezeled_(False)
        sep.setDrawsBackground_(True)
        sep.setEditable_(False)
        view.addSubview_(sep)

        view.addSubview_(_label("Polling interval:", 0, VIEW_H - 94))
        poll_field = NSTextField.alloc().initWithFrame_(NSMakeRect(120, VIEW_H - 96, 60, 24))
        poll_field.setStringValue_(str(saved.get("poll_interval", 60)))
        view.addSubview_(poll_field)
        view.addSubview_(_label("seconds", 188, VIEW_H - 94, 80))

        # ── Alert ────────────────────────────────────────────────────────────
        alert = NSAlert.alloc().init()
        alert.setMessageText_("iCloud Sync Settings")
        alert.addButtonWithTitle_("Save")
        alert.addButtonWithTitle_("Cancel")
        alert.setAccessoryView_(view)

        # LSUIElement apps can't become key without switching activation policy.
        # Temporarily go "regular" so the alert can receive focus, then revert.
        from AppKit import NSApplicationActivationPolicyRegular, NSApplicationActivationPolicyAccessory
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        NSApp.activateIgnoringOtherApps_(True)
        response = alert.runModal()
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        if response != 1000:   # 1000 = NSAlertFirstButtonReturn
            return

        # ── Persist ──────────────────────────────────────────────────────────
        _set_launch_at_login(login_cb.state() == 1)
        save_prefs(autostart_daemon=autostart_cb.state() == 1)

        try:
            new_poll = max(10, int(poll_field.stringValue()))
        except (ValueError, TypeError):
            new_poll = saved.get("poll_interval", 60)

        if new_poll != saved.get("poll_interval", 60):
            update_poll_interval(new_poll)
            self._reload_daemon()

    def _open_setup(self, _sender):
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _run_setup(self):
        from pyicloud import PyiCloudService
        from pyicloud.exceptions import PyiCloudFailedLoginException
        from .auth import store_password
        from .config import save_config, load_saved_config

        # Step 1: Apple ID
        saved = load_saved_config() or {}
        username = _ask(
            "Enter your Apple ID (iCloud email):",
            default=saved.get("username", ""),
            title="iCloud Setup (1/3)",
        )
        if not username or not username.strip():
            return
        username = username.strip()

        # Step 2: Password
        password = _ask_secure(
            f"Enter the password for {username}:",
            title="iCloud Setup (2/3)",
        )
        if not password:
            return

        # Step 3: Authenticate
        try:
            api = PyiCloudService(apple_id=username, password=password)
        except PyiCloudFailedLoginException as e:
            _dialog(f"Login failed:\n{e}", ["OK"], title="iCloud Setup")
            return
        except Exception as e:
            _dialog(f"Unexpected error:\n{e}", ["OK"], title="iCloud Setup")
            return

        # Step 4: 2FA / 2SA
        if api.requires_2fa:
            if not self._handle_2fa_dialog(api):
                return
        elif api.requires_2sa:
            if not self._handle_2sa_dialog(api):
                return

        # Trust the session so we don't have to re-auth every time
        if not api.is_trusted_session:
            try:
                api.trust_session()
            except Exception:
                pass

        # Persist credentials
        store_password(username, password)
        pairs = saved.get("pairs", [])
        poll_interval = saved.get("poll_interval", 60)
        save_config(username, pairs, poll_interval)

        _notify("iCloud Sync", f"Setup complete — signed in as {username}")

    def _handle_2fa_dialog(self, api) -> bool:
        """Show native 2FA code dialog. Returns True on success."""
        code = _ask(
            "Two-factor authentication required.\n\n"
            "Enter the 6-digit code shown on your trusted Apple device:",
            title="iCloud Setup (3/3)",
        )
        if not code or not code.strip():
            return False
        if not api.validate_2fa_code(code.strip()):
            _dialog("Invalid 2FA code. Please try setup again.", ["OK"], title="iCloud Setup")
            return False
        return True

    def _handle_2sa_dialog(self, api) -> bool:
        """Show native 2SA device picker and code dialog. Returns True on success."""
        devices = api.trusted_devices
        if not devices:
            _dialog("No trusted devices found for two-step authentication.", ["OK"], title="iCloud Setup")
            return False

        labels = [
            d.get("deviceName") or f"SMS to {d.get('phoneNumber', '?')}"
            for d in devices
        ]
        chosen = _choose_from_list(labels, prompt="Select a device to receive the verification code:", title="iCloud Setup (3/3)")
        if chosen is None:
            return False

        try:
            device = devices[labels.index(chosen)]
        except ValueError:
            return False

        if not api.send_verification_code(device):
            _dialog("Failed to send verification code.", ["OK"], title="iCloud Setup")
            return False

        code = _ask(
            f"Enter the verification code sent to {chosen}:",
            title="iCloud Setup (3/3)",
        )
        if not code or not code.strip():
            return False
        if not api.validate_verification_code(device, code.strip()):
            _dialog("Invalid verification code. Please try setup again.", ["OK"], title="iCloud Setup")
            return False
        return True

    def _open_log(self, _sender):
        log = Path.home() / "Library" / "Logs" / "icloud_sync.log"
        if log.exists():
            os.system(f'open "{log}"')
        else:
            _confirm(
                "No log file found yet.\nStart the daemon first.",
                ok_label="OK",
            )

    def _uninstall(self, _sender):
        if not _confirm(
            "This will remove iCloud Sync from your Mac:\n\n"
            "• Stop the sync daemon\n"
            "• Remove the login item\n"
            "• Delete config, preferences and log files\n"
            "• Remove saved credentials from the Keychain\n"
            "• Move the app to the Trash\n\n"
            "Your synced files will NOT be deleted.",
            ok_label="Uninstall",
            title="Uninstall iCloud Sync",
        ):
            return

        # 1 — Stop daemon
        if self._is_running():
            self._stop_daemon()

        # 2 — Remove & unload LaunchAgent
        if _LAUNCH_AGENT_PLIST.exists():
            subprocess.run(
                ["launchctl", "unload", str(_LAUNCH_AGENT_PLIST)],
                capture_output=True,
            )
            try:
                _LAUNCH_AGENT_PLIST.unlink()
            except FileNotFoundError:
                pass

        # 3 — Remove credentials from Keychain
        saved = load_saved_config() or {}
        username = saved.get("username")
        if username:
            try:
                from .auth import delete_password
                delete_password(username)
            except Exception:
                pass

        # 4 — Delete config directory and log
        import shutil as _shutil
        config_dir = Path.home() / ".config" / "icloud_sync"
        if config_dir.exists():
            _shutil.rmtree(config_dir, ignore_errors=True)

        log_file = Path.home() / "Library" / "Logs" / "icloud_sync.log"
        try:
            log_file.unlink()
        except FileNotFoundError:
            pass

        # 5 — Move the .app bundle to the Trash
        try:
            from AppKit import NSBundle
            bundle_path = NSBundle.mainBundle().bundlePath()
            if bundle_path and bundle_path.endswith(".app"):
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "Finder" to delete POSIX file "{bundle_path}"'],
                    capture_output=True,
                )
        except Exception:
            pass

        rumps.quit_application()

    def _quit(self, _sender):
        if self._is_running():
            self._stop_daemon()
        rumps.quit_application()


def main():
    ICloudSyncTray().run()
