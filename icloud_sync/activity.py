"""
Heartbeat signal consumed by the menu bar app to animate the tray icon
while a file is actually being copied to/from iCloud Drive.

The app polls this file and treats the signal as stale after a couple of
seconds, so there's no explicit "idle" call: silence is the idle state.
"""
import json
import time
from pathlib import Path

_ACTIVITY_FILE = Path.home() / ".config" / "icloud_sync" / "activity.json"


def mark_active() -> None:
    _ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVITY_FILE.write_text(json.dumps({"last_active": time.time()}))
