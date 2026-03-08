"""
Local filesystem watcher using watchdog.
Queues local change events so the sync engine can pick them up.
"""
import fnmatch
import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class LocalChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        local_dir: Path,
        exclude_patterns: list[str],
        pending: set[str],
        moves: dict[str, str],
        suppressed: dict[str, float],
        lock: threading.Lock,
    ):
        super().__init__()
        self._base = local_dir
        self._exclude = exclude_patterns
        self._pending = pending
        self._moves = moves      # dest_rel → src_rel
        self._suppressed = suppressed
        self._lock = lock

    def _rel(self, abs_path: str) -> str:
        return str(Path(abs_path).relative_to(self._base))

    def _excluded(self, abs_path: str) -> bool:
        name = Path(abs_path).name
        return any(fnmatch.fnmatch(name, p) for p in self._exclude)

    def _queue(self, abs_path: str) -> None:
        if self._excluded(abs_path):
            return
        rel = self._rel(abs_path)
        with self._lock:
            if time.monotonic() < self._suppressed.get(rel, 0):
                logger.debug("Suppressed watcher event (daemon write): %s", rel)
                return
            self._pending.add(rel)
        logger.debug("Queued for upload: %s", rel)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._queue(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._queue(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        src_rel = self._rel(event.src_path)
        dest_rel = self._rel(event.dest_path)
        if self._excluded(event.dest_path):
            return
        with self._lock:
            # Record as a rename pair; remove any stale pending for the old path
            self._moves[dest_rel] = src_rel
            self._pending.discard(src_rel)
        logger.debug("Queued rename: %s → %s", src_rel, dest_rel)


class LocalWatcher:
    def __init__(self, local_dir: Path, exclude_patterns: list[str]):
        self._local_dir = local_dir
        self.pending: set[str] = set()
        self._moves: dict[str, str] = {}        # dest_rel → src_rel
        self._suppressed: dict[str, float] = {} # rel_path → expiry monotonic time
        self._lock = threading.Lock()
        self._handler = LocalChangeHandler(
            local_dir, exclude_patterns, self.pending, self._moves, self._suppressed, self._lock
        )
        self._observer = Observer()

    def start(self) -> None:
        self._observer.schedule(self._handler, str(self._local_dir), recursive=True)
        self._observer.start()
        logger.info("Watching local dir: %s", self._local_dir)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()

    def suppress(self, rel: str, ttl: float = 30.0) -> None:
        """Ignore watcher events for `rel` for the next `ttl` seconds.
        Call this before writing any file to disk to avoid re-uploading downloads.
        """
        with self._lock:
            self._suppressed[rel] = time.monotonic() + ttl
            self.pending.discard(rel)

    def drain(self) -> tuple[set[str], dict[str, str]]:
        """Return and clear pending uploads and rename pairs (dest → src)."""
        with self._lock:
            pending = set(self.pending)
            moves = dict(self._moves)
            self.pending.clear()
            self._moves.clear()
        return pending, moves
