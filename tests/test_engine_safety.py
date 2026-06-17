"""
Safety guards in the sync engine that prevent mass / irreversible data loss.

These cover two fixes:
  1. delete_local moves to the Trash (reversible) instead of unlink()ing.
  2. A failed or empty remote listing aborts the cycle instead of being
     interpreted as "everything on the server was deleted".
"""
import pytest

from icloud_sync import engine
from icloud_sync.engine import (
    FileSnapshot,
    RemoteListingError,
    delete_local,
    reconcile,
    walk_remote,
)
from icloud_sync.state import FileStatus, IndexEntry


# --------------------------------------------------------------------------- #
# Fixtures / fakes
# --------------------------------------------------------------------------- #

class FakeNode:
    """Minimal stand-in for a pyicloud DriveNode."""

    def __init__(self, name="root", type="folder", size=0, date_modified=None,
                 children=None, data=None, raise_on_children=False):
        self.name = name
        self.type = type
        self.size = size
        self.date_modified = date_modified
        self._children = children or []
        self.data = data if data is not None else {}
        self._raise = raise_on_children

    def get_children(self, force=False):
        if self._raise:
            raise RuntimeError("transient iCloud listing failure")
        return self._children


def _file_entry():
    return IndexEntry(
        synced_local_mtime=1.0, synced_local_size=10,
        synced_remote_mtime=1.0, synced_remote_size=10,
        status=FileStatus.SYNCED, is_dir=False,
    )


# --------------------------------------------------------------------------- #
# Fix 1 — delete_local routes through the Trash
# --------------------------------------------------------------------------- #

def test_delete_local_moves_to_trash(tmp_path, monkeypatch):
    f = tmp_path / "keep_me.pdf"
    f.write_text("important")
    called = {}

    def fake_send2trash(path):
        called["path"] = path

    monkeypatch.setattr(engine, "send2trash", fake_send2trash)

    assert delete_local(tmp_path, "keep_me.pdf") is True
    # Trashed via send2trash, NOT permanently unlinked from here.
    assert called["path"] == str(f)


def test_delete_local_does_not_permanently_unlink(tmp_path, monkeypatch):
    f = tmp_path / "keep_me.pdf"
    f.write_text("important")
    monkeypatch.setattr(engine, "send2trash", lambda path: None)  # no-op stub

    delete_local(tmp_path, "keep_me.pdf")
    # With send2trash stubbed out, the file must still be on disk —
    # proving delete_local no longer calls path.unlink() directly.
    assert f.exists()


def test_delete_local_returns_false_on_error(tmp_path, monkeypatch):
    def boom(path):
        raise OSError("trash unavailable")

    monkeypatch.setattr(engine, "send2trash", boom)
    assert delete_local(tmp_path, "missing.pdf") is False


# --------------------------------------------------------------------------- #
# Fix 2 — a failed remote listing raises instead of silently returning {}
# --------------------------------------------------------------------------- #

def test_walk_remote_raises_on_listing_failure():
    node = FakeNode(raise_on_children=True)
    with pytest.raises(RemoteListingError):
        walk_remote(node)


def test_walk_remote_success_lists_files():
    child = FakeNode(name="a.txt", type="file", size=42)
    root = FakeNode(children=[child])
    result = walk_remote(root)
    assert result == {"a.txt": FileSnapshot(mtime=0.0, size=42, is_dir=False)}


# --------------------------------------------------------------------------- #
# Fix 2 — reconcile aborts (no deletions) when the remote side is unreliable
# --------------------------------------------------------------------------- #

def _spy_no_deletes(monkeypatch):
    deletes = []
    monkeypatch.setattr(engine, "delete_local",
                        lambda *a, **k: deletes.append(("local", a)) or True)
    monkeypatch.setattr(engine, "delete_remote",
                        lambda *a, **k: deletes.append(("remote", a)) or True)
    return deletes


def test_reconcile_aborts_when_remote_listing_fails(tmp_path, monkeypatch):
    deletes = _spy_no_deletes(monkeypatch)
    monkeypatch.setattr(engine, "walk_local", lambda *a, **k: {})

    def fail(*a, **k):
        raise RemoteListingError("listing failed")

    monkeypatch.setattr(engine, "walk_remote", fail)

    index = {"Carta identita.pdf": _file_entry()}
    out = reconcile(
        drive_root=FakeNode(), local_dir=tmp_path, exclude_patterns=[],
        index=index, index_path=tmp_path / "index.json",
        pending_uploads=set(),
    )
    assert deletes == []          # nothing deleted
    assert out == index           # index returned unchanged
    assert "Carta identita.pdf" in out


def test_reconcile_aborts_when_remote_empty_but_index_has_files(tmp_path, monkeypatch):
    deletes = _spy_no_deletes(monkeypatch)
    # Local still has the file; remote scan came back empty (suspicious).
    monkeypatch.setattr(engine, "walk_local", lambda *a, **k: {
        "Passwords.csv": FileSnapshot(mtime=1.0, size=10, is_dir=False)})
    monkeypatch.setattr(engine, "walk_remote", lambda *a, **k: {})

    index = {"Passwords.csv": _file_entry()}
    out = reconcile(
        drive_root=FakeNode(), local_dir=tmp_path, exclude_patterns=[],
        index=index, index_path=tmp_path / "index.json",
        pending_uploads=set(),
    )
    assert deletes == []
    assert out == index
