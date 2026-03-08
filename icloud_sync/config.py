import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_CONFIG_FILE = Path.home() / ".config" / "icloud_sync" / "config.json"
_PID_FILE = Path.home() / ".config" / "icloud_sync" / "daemon.pid"


# ---------------------------------------------------------------------------
# PID file helpers (used by daemon and tray app)
# ---------------------------------------------------------------------------

def write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def read_pid() -> Optional[int]:
    try:
        return int(_PID_FILE.read_text().strip())
    except Exception:
        return None


def clear_pid() -> None:
    try:
        _PID_FILE.unlink()
    except FileNotFoundError:
        pass


def is_daemon_running() -> bool:
    """Return True if a daemon process recorded in the PID file is alive."""
    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)   # signal 0 = existence check, no actual signal sent
        return True
    except ProcessLookupError:
        clear_pid()
        return False
    except PermissionError:
        return True  # process exists but owned by another user


@dataclass
class SyncPair:
    local_dir: Path
    remote_dir: str

    @property
    def state_file(self) -> Path:
        safe = self.remote_dir.replace("/", "_").replace(" ", "_")
        return Path.home() / ".config" / "icloud_sync" / f"index_{safe}.json"


@dataclass
class Config:
    username: str
    pairs: list  # list[SyncPair]
    poll_interval: int = 60
    log_file: Path = field(default_factory=lambda: Path.home() / "Library/Logs/icloud_sync.log")
    exclude_patterns: list = field(default_factory=lambda: [
        ".DS_Store", "*.tmp", "*.part", ".*", "desktop.ini", "Thumbs.db",
        "*.conflict-*",  # conflict copies created by this daemon — never sync these
    ])
    session_refresh_interval: int = 300


_PREFS_FILE = Path.home() / ".config" / "icloud_sync" / "prefs.json"


def load_prefs() -> dict:
    try:
        return json.loads(_PREFS_FILE.read_text())
    except Exception:
        return {}


def save_prefs(**kwargs) -> None:
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    prefs = load_prefs()
    prefs.update(kwargs)
    _PREFS_FILE.write_text(json.dumps(prefs, indent=2))


def load_saved_config() -> Optional[dict]:
    """Load config saved by `icloud-sync setup`, if it exists."""
    if _CONFIG_FILE.exists():
        return json.loads(_CONFIG_FILE.read_text())
    return None


def _pairs_from_raw(saved: dict) -> list[SyncPair]:
    """Parse pairs from saved config, migrating old single-pair format if needed."""
    if "pairs" in saved:
        return [
            SyncPair(
                local_dir=Path(p["local_dir"]).expanduser().resolve(),
                remote_dir=p["remote_dir"],
            )
            for p in saved["pairs"]
        ]
    # Migrate old format
    local_dir = saved.get("local_dir")
    remote_dir = saved.get("remote_dir", "SyncFolder")
    if local_dir:
        return [SyncPair(
            local_dir=Path(local_dir).expanduser().resolve(),
            remote_dir=remote_dir,
        )]
    return []


def save_config(username: str, pairs: list, poll_interval: int) -> None:
    """Persist config. `pairs` is a list of SyncPair or dicts with local_dir/remote_dir."""
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    raw_pairs = []
    for p in pairs:
        if isinstance(p, SyncPair):
            raw_pairs.append({"local_dir": str(p.local_dir), "remote_dir": p.remote_dir})
        else:
            raw_pairs.append({"local_dir": str(p["local_dir"]), "remote_dir": p["remote_dir"]})
    data = {
        "username": username,
        "pairs": raw_pairs,
        "poll_interval": poll_interval,
    }
    _CONFIG_FILE.write_text(json.dumps(data, indent=2))


def add_pair(local_dir: str, remote_dir: str) -> None:
    """Append a new sync pair to the saved config."""
    saved = load_saved_config()
    if not saved:
        raise RuntimeError("No config found. Run `icloud-sync setup` first.")
    pairs = _pairs_from_raw(saved)
    new_pair = SyncPair(
        local_dir=Path(local_dir).expanduser().resolve(),
        remote_dir=remote_dir,
    )
    # Avoid duplicates
    for p in pairs:
        if p.local_dir == new_pair.local_dir and p.remote_dir == new_pair.remote_dir:
            raise ValueError(f"Pair already exists: {local_dir} ↔ {remote_dir}")
    pairs.append(new_pair)
    save_config(saved["username"], pairs, saved.get("poll_interval", 60))


def remove_pair(remote_dir: str) -> bool:
    """Remove the pair with the given remote_dir. Returns True if found and removed."""
    saved = load_saved_config()
    if not saved:
        return False
    pairs = _pairs_from_raw(saved)
    before = len(pairs)
    pairs = [p for p in pairs if p.remote_dir != remote_dir]
    if len(pairs) == before:
        return False
    save_config(saved["username"], pairs, saved.get("poll_interval", 60))
    return True


def update_poll_interval(interval: int) -> None:
    """Update only poll_interval in the saved config."""
    saved = load_saved_config()
    if not saved:
        return
    saved["poll_interval"] = interval
    _CONFIG_FILE.write_text(json.dumps(saved, indent=2))


def get_pairs() -> list[SyncPair]:
    """Return the configured sync pairs, or an empty list if no config exists."""
    saved = load_saved_config()
    if not saved:
        return []
    return _pairs_from_raw(saved)


def load_config() -> "Config":
    """
    Build Config by merging (in priority order):
      1. Environment variables
      2. Saved config file (~/.config/icloud_sync/config.json)

    Raises ValueError if required fields are still missing after both sources.
    """
    saved = load_saved_config() or {}

    username = os.environ.get("ICLOUD_USERNAME") or saved.get("username")
    poll_interval = int(os.environ.get("ICLOUD_POLL_INTERVAL") or saved.get("poll_interval", 60))

    # Allow a single pair from env vars (for scripted/CI use)
    env_local = os.environ.get("ICLOUD_LOCAL_DIR")
    env_remote = os.environ.get("ICLOUD_REMOTE_DIR", "SyncFolder")

    if env_local:
        pairs = [SyncPair(
            local_dir=Path(env_local).expanduser().resolve(),
            remote_dir=env_remote,
        )]
    else:
        pairs = _pairs_from_raw(saved)

    missing = []
    if not username:
        missing.append("username")
    if not pairs:
        missing.append("pairs (at least one local_dir/remote_dir)")
    if missing:
        raise ValueError(
            f"Missing required config: {', '.join(missing)}. "
            "Run `icloud-sync setup` or set the corresponding environment variables."
        )

    for pair in pairs:
        pair.local_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        username=username,
        pairs=pairs,
        poll_interval=poll_interval,
    )
