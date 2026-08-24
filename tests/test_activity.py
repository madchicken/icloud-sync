"""
Activity signaling used to drive the menu bar icon's sync animation.

mark_active() writes a small heartbeat file the (separate) Swift app polls;
the app treats the signal as stale after a couple of seconds, so we only
need to prove the file is written with a fresh, readable timestamp.
"""
import json
import time

from icloud_sync import activity


def test_mark_active_writes_current_timestamp(tmp_path, monkeypatch):
    activity_file = tmp_path / "activity.json"
    monkeypatch.setattr(activity, "_ACTIVITY_FILE", activity_file)

    before = time.time()
    activity.mark_active()
    after = time.time()

    data = json.loads(activity_file.read_text())
    assert before <= data["last_active"] <= after


def test_mark_active_creates_parent_directory(tmp_path, monkeypatch):
    activity_file = tmp_path / "nested" / "activity.json"
    monkeypatch.setattr(activity, "_ACTIVITY_FILE", activity_file)

    activity.mark_active()

    assert activity_file.exists()
