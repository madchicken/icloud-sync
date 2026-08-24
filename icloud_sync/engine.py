"""
Sync engine.

All decisions are made by comparing the CURRENT local and remote state
against the INDEX (the anchor of what was last synced). We never compare
local directly against remote except during bootstrap when no index exists.

Conflict rule: if we cannot CLEARLY determine which side is newer, the
server always wins.
"""

import fnmatch
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfileobj
from typing import Optional

from pyicloud.exceptions import PyiCloudAPIResponseException
from send2trash import send2trash

from . import activity
from .state import FileStatus, Index, IndexEntry, save

logger = logging.getLogger(__name__)

# Remote mtimes can drift from local by a few seconds due to upload latency
# and server-side rounding. Changes smaller than this are ignored.
_MTIME_TOLERANCE = 5.0


class RemoteListingError(Exception):
    """Raised when the remote drive cannot be listed.

    Reconcile MUST treat this as "unknown remote state" and abort the cycle —
    never as "the server is empty", which would delete every local file.
    """


# ---------------------------------------------------------------------------
# Lightweight scan results (not the index — just current filesystem state)
# ---------------------------------------------------------------------------


@dataclass
class FileSnapshot:
    mtime: float
    size: int
    is_dir: bool = False


def _dt_to_ts(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _excluded(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _log_remote_listing(remote: dict[str, FileSnapshot]) -> None:
    files = sorted(k for k, v in remote.items() if not v.is_dir)
    dirs = sorted(k for k, v in remote.items() if v.is_dir)
    logger.info("Server listing: %d file(s), %d folder(s)", len(files), len(dirs))
    for d in dirs:
        logger.info("  [dir]  %s", d)
    for f in files:
        snap = remote[f]
        from datetime import datetime, timezone

        mtime_str = (
            datetime.fromtimestamp(snap.mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            if snap.mtime
            else "unknown"
        )
        logger.info("  [file] %-50s  %10d bytes  %s", f, snap.size, mtime_str)


def _is_active(child) -> bool:
    """Return False for trashed or invalid nodes that still appear in folder listings."""
    data = child.data
    if data.get("status") == "ID_INVALID":
        return False
    if data.get("restorePath"):  # moved to Recently Deleted / Trash
        return False
    if data.get("isDeleted"):
        return False
    return True


def walk_remote(
    node, prefix: str = "", patterns: list[str] = []
) -> dict[str, FileSnapshot]:
    patterns = patterns or []
    result: dict[str, FileSnapshot] = {}
    try:
        children = node.get_children(force=True)
    except Exception as e:
        # Do NOT swallow this. A partial/empty listing would make reconcile
        # think every indexed file was deleted on the server and wipe the
        # local copies. Propagate so the caller can abort the whole cycle.
        raise RemoteListingError(f"could not list remote dir '{prefix or '/'}': {e}") from e

    for child in children:
        if not _is_active(child):
            logger.debug(
                "Skipping inactive remote node: %s (status=%s, restorePath=%s)",
                child.name,
                child.data.get("status"),
                child.data.get("restorePath"),
            )
            continue
        name = child.name
        if _excluded(name, patterns):
            continue
        rel = f"{prefix}/{name}" if prefix else name
        if child.type == "folder":
            result[rel] = FileSnapshot(mtime=0.0, size=0, is_dir=True)
            result.update(walk_remote(child, rel, patterns))
        else:
            mtime = _dt_to_ts(child.date_modified) if child.date_modified else 0.0
            result[rel] = FileSnapshot(mtime=mtime, size=child.size or 0)
    return result


def walk_local(base: Path, patterns: list[str] = None) -> dict[str, FileSnapshot]:
    patterns = patterns or []
    result: dict[str, FileSnapshot] = {}
    for p in base.rglob("*"):
        if _excluded(p.name, patterns):
            continue
        rel = str(p.relative_to(base))
        stat = p.stat()
        result[rel] = FileSnapshot(
            mtime=stat.st_mtime, size=stat.st_size, is_dir=p.is_dir()
        )
    return result


# ---------------------------------------------------------------------------
# Remote changed since last sync?
# ---------------------------------------------------------------------------


def _remote_changed(r: FileSnapshot, idx: IndexEntry) -> bool:
    if idx.synced_remote_mtime == 0:
        # Server mtime not yet known (just uploaded) — compare by size only
        return r.size != idx.synced_remote_size
    return (
        abs(r.mtime - idx.synced_remote_mtime) > _MTIME_TOLERANCE
        or r.size != idx.synced_remote_size
    )


def _local_changed(l: FileSnapshot, idx: IndexEntry) -> bool:
    return (
        abs(l.mtime - idx.synced_local_mtime) > 1.0 or l.size != idx.synced_local_size
    )


# ---------------------------------------------------------------------------
# Transfer helpers
# ---------------------------------------------------------------------------


def _get_node(drive_root, rel: str):
    node = drive_root
    for part in rel.split("/"):
        node = node[part]
    return node


def _get_parent_node(drive_root, rel: str):
    parts = rel.split("/")
    node = drive_root
    for part in parts[:-1]:
        node = node[part]
    return node, parts[-1]


def _ensure_remote_dirs(drive_root, rel: str) -> None:
    parts = rel.split("/")
    node = drive_root
    try:
        existing = set(node.dir())
    except Exception:
        existing = set()
    for part in parts:
        if part not in existing:
            try:
                node.mkdir(part)
                logger.info("Created remote dir: %s", part)
            except Exception as e:
                logger.warning("Could not create remote dir '%s': %s", part, e)
        node = node[part]
        try:
            existing = set(node.dir())
        except Exception:
            existing = set()


def _is_document_deleted(exc: PyiCloudAPIResponseException) -> bool:
    """Return True if the exception signals that the document content has been deleted."""
    if exc.code != 409:
        return False
    try:
        body = exc.response.json() if exc.response else {}
        return body.get("error_code") == "DocumentDeletedException"
    except Exception:
        return False


def download(
    drive_root, rel: str, local_base: Path, suppress_fn=None
) -> Optional[IndexEntry]:
    """Download file and return an updated IndexEntry, or None on failure."""
    activity.mark_active()
    local_path = local_base / rel
    local_path.parent.mkdir(parents=True, exist_ok=True)
    # Suppress watcher events BEFORE writing so the daemon doesn't re-upload
    # the file it just downloaded.
    if suppress_fn:
        suppress_fn(rel)
    try:
        node = _get_node(drive_root, rel)
        remote_mtime = _dt_to_ts(node.date_modified) if node.date_modified else 0.0
        remote_size = node.size or 0
        with node.open(stream=True) as resp:
            with open(local_path, "wb") as f:
                copyfileobj(resp.raw, f)
        stat = local_path.stat()
        logger.info("Downloaded: %s", rel)
        return IndexEntry(
            synced_local_mtime=stat.st_mtime,
            synced_local_size=stat.st_size,
            synced_remote_mtime=remote_mtime,
            synced_remote_size=remote_size,
            status=FileStatus.SYNCED,
        )
    except PyiCloudAPIResponseException as e:
        if _is_document_deleted(e):
            # File appeared in the listing but its content is already gone on the
            # server (race condition / eventual consistency). Skip quietly — it will
            # disappear from walk_remote on the next poll.
            logger.info("Skipping deleted server file (content gone): %s", rel)
        else:
            logger.error("Download failed for %s: %s", rel, e)
        return None
    except Exception as e:
        logger.error("Download failed for %s: %s", rel, e)
        return None


def upload(drive_root, rel: str, local_base: Path) -> Optional[IndexEntry]:
    """Upload file and return an updated IndexEntry, or None on failure."""
    activity.mark_active()
    local_path = local_base / rel
    try:
        parent_rel = "/".join(rel.split("/")[:-1])
        if parent_rel:
            _ensure_remote_dirs(drive_root, parent_rel)
        parent_node, _ = _get_parent_node(drive_root, rel)
        with open(local_path, "rb") as f:
            parent_node.upload(f)
        stat = local_path.stat()
        logger.info("Uploaded: %s", rel)
        # Store synced_remote_mtime=0 to signal "server mtime not yet known".
        # On the next poll _remote_changed will use size-only comparison until
        # the index is corrected with the real server mtime.
        return IndexEntry(
            synced_local_mtime=stat.st_mtime,
            synced_local_size=stat.st_size,
            synced_remote_mtime=0.0,
            synced_remote_size=stat.st_size,
            status=FileStatus.SYNCED,
        )
    except Exception as e:
        logger.error("Upload failed for %s: %s", rel, e)
        return None


def delete_remote(drive_root, rel: str) -> bool:
    try:
        _get_node(drive_root, rel).delete()
        logger.info("Deleted remote: %s", rel)
        return True
    except Exception as e:
        logger.error("Delete remote failed for %s: %s", rel, e)
        return False


def delete_local(local_base: Path, rel: str) -> bool:
    # Route through the Trash rather than unlink()/rmtree() so a wrong
    # deletion decision is recoverable. Never permanently destroy user data.
    path = local_base / rel
    try:
        send2trash(str(path))
        logger.info("Moved local to Trash: %s", rel)
        return True
    except Exception as e:
        logger.error("Delete local failed for %s: %s", rel, e)
        return False


def conflict_copy(local_base: Path, rel: str) -> None:
    from datetime import datetime, timezone

    path = local_base / rel
    if not path.exists():
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.stem}.conflict-{ts}{path.suffix}")
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)
    logger.info("Conflict copy: %s", dest.name)


# ---------------------------------------------------------------------------
# Bootstrap (no index exists)
# ---------------------------------------------------------------------------


def bootstrap(drive_root, local_dir: Path, exclude_patterns: list, index_path) -> Index:
    """
    Build an index from scratch.

    - Files only on server   → download
    - Files only on local    → upload
    - Files on both sides:
        - Same size          → assume synced, just index them
        - Different size     → server wins; conflict copy of local, then download
    """
    logger.info("No index found — bootstrapping from server state")
    remote = walk_remote(drive_root, patterns=exclude_patterns)
    _log_remote_listing(remote)
    local = walk_local(local_dir, patterns=exclude_patterns)
    index: Index = {}

    # Dirs first
    for rel, snap in sorted(remote.items()):
        if snap.is_dir:
            (local_dir / rel).mkdir(parents=True, exist_ok=True)
            index[rel] = IndexEntry(0.0, 0, 0.0, 0, FileStatus.SYNCED, is_dir=True)

    for rel, r in sorted(remote.items()):
        if r.is_dir:
            continue
        l = local.get(rel)

        if l is None:
            # Only on server → download
            entry = download(drive_root, rel, local_dir)
            if entry:
                index[rel] = entry

        elif l.size == r.size:
            # Same size on both sides — assume already in sync
            logger.info("Already in sync (size match): %s", rel)
            local_path = local_dir / rel
            stat = local_path.stat()
            index[rel] = IndexEntry(
                synced_local_mtime=stat.st_mtime,
                synced_local_size=stat.st_size,
                synced_remote_mtime=r.mtime,
                synced_remote_size=r.size,
                status=FileStatus.SYNCED,
            )

        else:
            # Both exist, different sizes — cannot determine which is newer → server wins
            logger.info("Bootstrap conflict (size mismatch) on %s — server wins", rel)
            conflict_copy(local_dir, rel)
            entry = download(drive_root, rel, local_dir)
            if entry:
                index[rel] = entry

    # Upload local files not present on server
    for rel, l in sorted(local.items()):
        if l.is_dir or rel in remote:
            continue
        entry = upload(drive_root, rel, local_dir)
        if entry:
            index[rel] = entry

    save(index, index_path)
    logger.info("Bootstrap complete — %d files indexed", len(index))
    return index


# ---------------------------------------------------------------------------
# Regular reconciliation cycle
# ---------------------------------------------------------------------------


def _apply_renames(
    drive_root,
    index: Index,
    moves: dict[str, str],
    pending_uploads: set[str],
) -> set[str]:
    """
    Process watcher-detected renames before the regular reconcile loop.

    For same-directory renames where the source is indexed:
      - Calls the iCloud Drive rename API (no re-upload needed)
      - Updates all affected index entries in place
      - Returns the set of rel-paths fully handled (to skip in regular loop)

    For cross-directory moves, or when the source is not indexed, the move
    is left to the regular loop which will delete the old name and upload
    the new one.
    """
    handled: set[str] = set()

    for dest_rel, src_rel in moves.items():
        src_entry = index.get(src_rel)
        if not src_entry:
            # Source not yet indexed — regular loop will upload dest as new file
            continue

        src_parent = "/".join(src_rel.split("/")[:-1])
        dest_parent = "/".join(dest_rel.split("/")[:-1])
        new_name = dest_rel.split("/")[-1]

        if src_parent != dest_parent:
            # Cross-directory move — fall back to delete + upload
            logger.debug(
                "Cross-directory move %s → %s: falling back to delete+upload",
                src_rel,
                dest_rel,
            )
            continue

        try:
            node = _get_node(drive_root, src_rel)
            node.rename(new_name)
            logger.info("Renamed on server: %s → %s", src_rel, dest_rel)
        except Exception as e:
            logger.warning(
                "Server rename failed for %s → %s: %s — falling back to delete+upload",
                src_rel,
                dest_rel,
                e,
            )
            continue

        # Update index: rename all keys under src_rel (handles directory renames too)
        prefix = src_rel + "/"
        keys_to_rename = [
            (k, dest_rel + k[len(src_rel) :])
            for k in list(index.keys())
            if k == src_rel or k.startswith(prefix)
        ]
        for old_key, new_key in keys_to_rename:
            index[new_key] = index.pop(old_key)

        handled.update(old for old, _ in keys_to_rename)
        handled.update(new for _, new in keys_to_rename)
        pending_uploads.discard(dest_rel)

    return handled


def reconcile(
    drive_root,
    local_dir: Path,
    exclude_patterns: list,
    index: Index,
    index_path,
    pending_uploads: set[str],
    moves: dict[str, str] = None,
    suppress_fn=None,
) -> Index:
    """
    One sync cycle. Mutates and returns the updated index.

    Decision table (idx = index entry, r = remote snapshot, l = local snapshot):

    idx   r     l     idx.status   Action
    ────  ────  ────  ───────────  ──────────────────────────────────────────
    None  yes   no    -            Download (new on server)
    None  yes   yes   -            Server wins; conflict copy if sizes differ
    None  no    yes   -            Upload (new local file not yet indexed)
    yes   yes   yes   SYNCED       Remote changed? → download. Else nothing.
    yes   yes   yes   MODIFIED     Remote changed? → server wins + conflict copy.
                                   Else → upload.
    yes   no    yes   SYNCED       Server deleted → delete local
    yes   no    yes   MODIFIED     Local changed after server deleted → upload (re-create)
    yes   yes   no    any          Local deleted → delete remote
    yes   no    no    -            Both gone → remove from index
    """
    # 0. Handle renames detected by the watcher before anything else
    rename_handled = _apply_renames(drive_root, index, moves or {}, pending_uploads)

    # 1. Mark watcher-reported changes as MODIFIED in the index
    for rel in pending_uploads:
        if rel in index:
            if index[rel].status != FileStatus.MODIFIED:
                index[rel].status = FileStatus.MODIFIED
                logger.debug("Marked MODIFIED (watcher): %s", rel)
        else:
            # New file not yet in index — create a placeholder
            local_path = local_dir / rel
            if local_path.exists() and not local_path.is_dir():
                index[rel] = IndexEntry(
                    synced_local_mtime=0.0,
                    synced_local_size=0,
                    synced_remote_mtime=0.0,
                    synced_remote_size=0,
                    status=FileStatus.MODIFIED,
                )

    # 2. Scan current state
    local_now = walk_local(local_dir, exclude_patterns)
    try:
        remote_now = walk_remote(drive_root, patterns=exclude_patterns)
    except RemoteListingError as e:
        # Unknown remote state — refuse to infer deletions. Leave the index
        # untouched and retry on the next poll.
        logger.error("Aborting cycle: %s — refusing to infer deletions", e)
        return index
    _log_remote_listing(remote_now)

    # Safety guard: an empty remote listing while the index still tracks files
    # almost always means a transient failure or a wrong remote folder — not
    # that the user emptied iCloud. Propagating it would delete every local
    # file. Abort and require an explicit resync (delete the index) instead.
    remote_file_count = sum(1 for s in remote_now.values() if not s.is_dir)
    indexed_file_count = sum(1 for e in index.values() if not e.is_dir)
    if remote_file_count == 0 and indexed_file_count > 0:
        logger.error(
            "Aborting cycle: remote listing is empty but the index tracks %d "
            "file(s). Refusing to delete local files. If you really emptied the "
            "remote folder, delete %s to force a resync.",
            indexed_file_count, index_path,
        )
        return index

    # 3. Detect local modifications that the watcher may have missed
    #    (e.g. files changed while the daemon was stopped)
    for rel, idx in index.items():
        if idx.status == FileStatus.SYNCED and not idx.is_dir:
            l = local_now.get(rel)
            if l and _local_changed(l, idx):
                logger.info("Detected offline local change: %s", rel)
                index[rel].status = FileStatus.MODIFIED

    # 4. Process every known path
    all_keys = set(local_now) | set(remote_now) | set(index)

    for key in sorted(all_keys):
        if key in rename_handled:
            continue  # already processed as a rename
        r = remote_now.get(key)
        l = local_now.get(key)
        idx = index.get(key)

        # Dirs are created implicitly during file downloads/uploads
        if (r and r.is_dir) or (l and l.is_dir) or (idx and idx.is_dir):
            if l and l.is_dir:
                pass  # already exists locally
            elif r and r.is_dir:
                (local_dir / key).mkdir(parents=True, exist_ok=True)
            if not idx or idx.is_dir:
                index[key] = IndexEntry(0.0, 0, 0.0, 0, FileStatus.SYNCED, is_dir=True)
            continue

        # ── No index entry (first time we see this file) ──────────────────

        if idx is None:
            if r and not l:
                # New on server
                entry = download(drive_root, key, local_dir, suppress_fn)
                if entry:
                    index[key] = entry

            elif r and l:
                # Both sides, no index → can't tell which is newer → server wins
                if r.size != l.size:
                    conflict_copy(local_dir, key)
                    entry = download(drive_root, key, local_dir, suppress_fn)
                else:
                    # Same size → assume synced
                    stat = (local_dir / key).stat()
                    entry = IndexEntry(
                        stat.st_mtime, stat.st_size, r.mtime, r.size, FileStatus.SYNCED
                    )
                if entry:
                    index[key] = entry

            elif not r and l:
                # Only local, never indexed → upload
                entry = upload(drive_root, key, local_dir)
                if entry:
                    index[key] = entry
            continue

        # ── Both gone ─────────────────────────────────────────────────────

        if not r and not l:
            del index[key]
            continue

        # ── Local deleted ──────────────────────────────────────────────────

        if not l and r:
            if delete_remote(drive_root, key):
                del index[key]
            continue

        # ── Server deleted ─────────────────────────────────────────────────

        if not r and l:
            if idx.status == FileStatus.MODIFIED:
                # Local was modified after server deleted it → re-upload
                logger.info(
                    "Re-uploading locally modified file after server delete: %s", key
                )
                entry = upload(drive_root, key, local_dir)
                if entry:
                    index[key] = entry
            else:
                if delete_local(local_dir, key):
                    del index[key]
            continue

        # ── Both sides exist, index entry exists ───────────────────────────

        r_changed = _remote_changed(r, idx)

        if idx.status == FileStatus.MODIFIED:
            if r_changed:
                # Both sides changed → server wins
                logger.info("Conflict on %s (both changed) — server wins", key)
                conflict_copy(local_dir, key)
                entry = download(drive_root, key, local_dir, suppress_fn)
            else:
                # Only local changed → upload
                entry = upload(drive_root, key, local_dir)
            if entry:
                index[key] = entry

        elif r_changed:
            if r.size == idx.synced_remote_size:
                # Size unchanged — only mtime differs. This is the server assigning
                # its own timestamp after our upload. Correct the index, don't download.
                logger.debug("Correcting remote mtime for %s (size unchanged)", key)
                index[key].synced_remote_mtime = r.mtime
            else:
                # Content actually changed on server → download
                entry = download(drive_root, key, local_dir, suppress_fn)
                if entry:
                    index[key] = entry
        # else: nothing changed — index already correct

    save(index, index_path)
    return index
