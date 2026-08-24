"""
download() and upload() are the only two places a real file actually moves
to/from iCloud Drive, so they're where the tray icon's activity heartbeat
must be triggered from.
"""
import io

from icloud_sync import activity, engine
from icloud_sync.engine import download, upload


class _FakeResponse:
    def __init__(self, content: bytes):
        self.raw = io.BytesIO(content)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeDownloadNode:
    """Stands in for the remote file node download() fetches."""

    def __init__(self, content=b"hello", size=5, date_modified=None):
        self.size = size
        self.date_modified = date_modified
        self._content = content

    def open(self, stream=True):
        return _FakeResponse(self._content)

    def __getitem__(self, key):
        return self


class FakeUploadNode:
    """Stands in for the parent node upload() writes into."""

    def upload(self, file_obj):
        pass

    def __getitem__(self, key):
        return self


def test_download_marks_activity(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(activity, "mark_active", lambda: calls.append(True))

    download(FakeDownloadNode(), "file.txt", tmp_path)

    assert calls == [True]


def test_upload_marks_activity(tmp_path, monkeypatch):
    (tmp_path / "file.txt").write_text("hello")
    calls = []
    monkeypatch.setattr(activity, "mark_active", lambda: calls.append(True))

    upload(FakeUploadNode(), "file.txt", tmp_path)

    assert calls == [True]
