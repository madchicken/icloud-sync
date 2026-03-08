"""
Index: the source of truth for what was last successfully synced.

Each entry records the local and remote state at the time of the last
successful sync, plus a status flag. Comparisons are always made against
this anchor — never directly between local and remote — so the daemon
can correctly detect one-sided or two-sided changes even across restarts.
"""
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class FileStatus:
    SYNCED = "synced"       # local and remote match the index anchor
    MODIFIED = "modified"   # local change detected, upload pending


@dataclass
class IndexEntry:
    synced_local_mtime: float   # local mtime at last successful sync
    synced_local_size: int      # local size at last successful sync
    synced_remote_mtime: float  # remote mtime at last successful sync
    synced_remote_size: int     # remote size at last successful sync
    status: str = FileStatus.SYNCED
    is_dir: bool = False


# relative path → IndexEntry
Index = dict[str, IndexEntry]


def load(path: Path) -> Optional[Index]:
    """Return None if no index exists (first run — bootstrap required)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return {k: IndexEntry(**v) for k, v in data.items()}
    except Exception as e:
        logger.warning("Could not load index %s: %s — will bootstrap", path, e)
        return None


def save(index: Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: asdict(v) for k, v in index.items()}, indent=2))
    tmp.replace(path)  # atomic on POSIX
