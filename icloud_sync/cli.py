"""
icloud-sync CLI

Commands:
    setup        — store credentials in macOS Keychain and verify login
    add-pair     — add another local↔remote folder pair
    remove-pair  — remove a folder pair by remote dir name
    start        — start the sync daemon (foreground)
    status       — show current configuration and keychain status
"""
import sys

from .auth import (
    delete_password,
    get_password,
    interactive_authenticate,
    store_password,
)
from .config import add_pair, load_saved_config, remove_pair, save_config


def _prompt_password(username: str) -> str:
    import getpass
    return getpass.getpass(f"iCloud password for {username}: ")


def cmd_setup(args: list[str]) -> None:
    """
    Interactively configure icloud-sync:
      - Prompts for Apple ID, password, and the first folder pair
      - Verifies login (handles 2FA/2SA interactively)
      - Stores password in macOS Keychain
      - Saves settings to ~/.config/icloud_sync/config.json

    Usage: icloud-sync setup [--username EMAIL] [--delete]
    """
    import argparse
    parser = argparse.ArgumentParser(prog="icloud-sync setup")
    parser.add_argument("--username", required=False, help="Apple ID email")
    parser.add_argument(
        "--delete", action="store_true", help="Remove stored credentials and config"
    )
    ns = parser.parse_args(args)

    # --- Delete mode ---
    if ns.delete:
        username = ns.username or input("Apple ID (email): ").strip()
        delete_password(username)
        print(f"Credentials removed from keychain for {username}.")
        return

    # --- Prefill from existing saved config ---
    saved = load_saved_config() or {}
    existing_pairs = saved.get("pairs", [])
    # Migrate old single-pair format
    if not existing_pairs and saved.get("local_dir"):
        existing_pairs = [{"local_dir": saved["local_dir"], "remote_dir": saved.get("remote_dir", "SyncFolder")}]

    username = ns.username or saved.get("username") or input("Apple ID (email): ").strip()
    if not username:
        print("Username is required.", file=sys.stderr)
        sys.exit(1)

    if get_password(username):
        overwrite = input(
            f"Credentials already stored for {username}. Overwrite? [y/N] "
        ).strip().lower()
        if overwrite != "y":
            print("Aborted.")
            return

    password = _prompt_password(username)
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    default_local = existing_pairs[0]["local_dir"] if existing_pairs else ""
    prompt = f"Local folder to sync [{default_local}]: " if default_local else "Local folder to sync: "
    local_dir = input(prompt).strip() or default_local
    if not local_dir:
        print("Local folder is required.", file=sys.stderr)
        sys.exit(1)

    default_remote = existing_pairs[0]["remote_dir"] if existing_pairs else "SyncFolder"
    remote_dir = input(f"iCloud Drive folder name [{default_remote}]: ").strip() or default_remote

    default_interval = saved.get("poll_interval", 60)
    interval_str = input(f"Poll interval in seconds [{default_interval}]: ").strip()
    poll_interval = int(interval_str) if interval_str else default_interval

    print("\nVerifying credentials with iCloud...")
    api = interactive_authenticate(username, password)

    # Persist only after successful login
    store_password(username, password)
    pairs = [{"local_dir": local_dir, "remote_dir": remote_dir}]
    save_config(username, pairs, poll_interval)

    print(f"\nSetup complete.")
    print(f"  Apple ID:    {username}")
    print(f"  Local dir:   {local_dir}")
    print(f"  Remote dir:  iCloud Drive / {remote_dir}")
    print(f"  Poll every:  {poll_interval}s")
    print(f"\niCloud Drive folders: {api.drive.dir()}")
    print("\nRun `icloud-sync add-pair` to add more folder pairs.")
    print("Run `icloud-sync start` to begin syncing.")


def cmd_add_pair(args: list[str]) -> None:
    """
    Add another local↔remote folder pair to the sync config.

    Usage: icloud-sync add-pair [--local PATH] [--remote NAME]
    """
    import argparse
    parser = argparse.ArgumentParser(prog="icloud-sync add-pair")
    parser.add_argument("--local", dest="local_dir", help="Local folder path")
    parser.add_argument("--remote", dest="remote_dir", help="iCloud Drive folder name")
    ns = parser.parse_args(args)

    local_dir = ns.local_dir or input("Local folder to sync: ").strip()
    if not local_dir:
        print("Local folder is required.", file=sys.stderr)
        sys.exit(1)

    remote_dir = ns.remote_dir or input("iCloud Drive folder name: ").strip()
    if not remote_dir:
        print("Remote folder name is required.", file=sys.stderr)
        sys.exit(1)

    try:
        add_pair(local_dir, remote_dir)
        print(f"Added pair: {local_dir}  ↔  iCloud Drive / {remote_dir}")
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_remove_pair(args: list[str]) -> None:
    """
    Remove a sync pair by its iCloud Drive folder name.

    Usage: icloud-sync remove-pair [--remote NAME]
    """
    import argparse
    parser = argparse.ArgumentParser(prog="icloud-sync remove-pair")
    parser.add_argument("--remote", dest="remote_dir", help="iCloud Drive folder name to remove")
    ns = parser.parse_args(args)

    remote_dir = ns.remote_dir or input("iCloud Drive folder name to remove: ").strip()
    if not remote_dir:
        print("Remote folder name is required.", file=sys.stderr)
        sys.exit(1)

    if remove_pair(remote_dir):
        print(f"Removed pair: iCloud Drive / {remote_dir}")
    else:
        print(f"No pair found for remote dir: {remote_dir}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args: list[str]) -> None:
    """Show current configuration and whether credentials are stored."""
    saved = load_saved_config()
    if not saved:
        print("No configuration found. Run `icloud-sync setup` to get started.")
        sys.exit(1)

    username = saved.get("username")
    has_password = bool(username and get_password(username))

    # Normalize pairs (handle old single-pair format)
    pairs = saved.get("pairs", [])
    if not pairs and saved.get("local_dir"):
        pairs = [{"local_dir": saved["local_dir"], "remote_dir": saved.get("remote_dir", "SyncFolder")}]

    print("icloud-sync configuration:")
    print(f"  Apple ID:    {username}")
    print(f"  Password:    {'stored in keychain' if has_password else 'MISSING — run setup again'}")
    print(f"  Poll every:  {saved.get('poll_interval')}s")
    print(f"  Pairs ({len(pairs)}):")
    for p in pairs:
        print(f"    {p['local_dir']}  ↔  iCloud Drive / {p['remote_dir']}")

    if not has_password:
        sys.exit(1)


def cmd_start(args: list[str]) -> None:
    """Start the sync daemon (foreground). Reads config from environment variables."""
    from .sync_daemon import main
    main()


_COMMANDS = {
    "setup": cmd_setup,
    "add-pair": cmd_add_pair,
    "remove-pair": cmd_remove_pair,
    "status": cmd_status,
    "start": cmd_start,
}

_USAGE = """\
Usage: icloud-sync <command> [options]

Commands:
  setup        Store iCloud credentials and configure the first folder pair
  add-pair     Add another local↔remote folder pair
  remove-pair  Remove a folder pair by remote dir name
  status       Show current configuration and keychain status
  start        Start the sync daemon (foreground)

Run `icloud-sync <command> --help` for command-specific options.
"""


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(_USAGE)
        sys.exit(0)

    command = sys.argv[1]
    if command not in _COMMANDS:
        print(f"Unknown command: {command}\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        sys.exit(1)

    _COMMANDS[command](sys.argv[2:])
