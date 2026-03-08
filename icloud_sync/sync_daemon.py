"""
iCloud Drive sync daemon.

First run: bootstraps the index from the server state, then enters the
regular poll loop. On subsequent runs the persisted index is loaded and
used as the sync anchor.

Supports multiple sync pairs simultaneously — each pair has its own
LocalWatcher, index, and drive_root.

Send SIGHUP to reload the config file and pick up added/removed pairs
without restarting the daemon.
"""
import logging
import signal
import sys
import time
from pathlib import Path

from .auth import authenticate, notify
from .config import SyncPair, clear_pid, load_config, write_pid
from .engine import bootstrap, reconcile
from .state import load as load_index
from .watcher import LocalWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

_running = True
_reload = False


def _handle_signal(signum, frame):
    global _running, _reload
    if signum == signal.SIGHUP:
        logger.info("SIGHUP received — reloading config")
        _reload = True
    else:
        logger.info("Signal %d received — shutting down", signum)
        _running = False


def _get_drive_root(api, remote_dir: str):
    top_level = api.drive.dir()
    if remote_dir not in top_level:
        logger.info("Creating remote folder: %s", remote_dir)
        api.drive.mkdir(remote_dir)
    return api.drive[remote_dir]


def _pair_key(pair: SyncPair) -> tuple:
    return (str(pair.local_dir), pair.remote_dir)


def _apply_reload(api, new_config, old_pairs, watchers, indexes, drive_roots):
    """
    Diff old vs new pair list.
    - Removed pairs: stop their watcher.
    - Added pairs: bootstrap/load index, start watcher, fetch drive_root.
    - Unchanged pairs: keep existing state.
    Returns updated (pairs, watchers, indexes, drive_roots).
    """
    old_by_key = {_pair_key(p): i for i, p in enumerate(old_pairs)}
    new_pairs = new_config.pairs

    new_watchers, new_indexes, new_drive_roots = [], [], []

    for pair in new_pairs:
        key = _pair_key(pair)
        if key in old_by_key:
            # Existing pair — carry over state unchanged
            i = old_by_key[key]
            new_watchers.append(watchers[i])
            new_indexes.append(indexes[i])
            new_drive_roots.append(drive_roots[i])
        else:
            # New pair — set it up
            logger.info("New pair added: %s ↔ iCloud Drive / %s", pair.local_dir, pair.remote_dir)
            drive_root = _get_drive_root(api, pair.remote_dir)
            index = load_index(pair.state_file)
            if index is None:
                notify("iCloud Sync", f"Bootstrapping new pair: {pair.remote_dir}")
                index = bootstrap(
                    drive_root, pair.local_dir, new_config.exclude_patterns, pair.state_file
                )
            watcher = LocalWatcher(pair.local_dir, new_config.exclude_patterns)
            watcher.start()
            new_watchers.append(watcher)
            new_indexes.append(index)
            new_drive_roots.append(drive_root)

    # Stop watchers for removed pairs
    new_keys = {_pair_key(p) for p in new_pairs}
    for i, pair in enumerate(old_pairs):
        if _pair_key(pair) not in new_keys:
            logger.info("Pair removed: %s ↔ iCloud Drive / %s", pair.local_dir, pair.remote_dir)
            watchers[i].stop()

    return new_pairs, new_watchers, new_indexes, new_drive_roots


def main() -> None:
    global _reload

    config = load_config()

    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(config.log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)

    logger.info("Starting iCloud sync daemon")
    logger.info("  Poll: every %ds", config.poll_interval)
    for pair in config.pairs:
        logger.info("  Pair: %s  ↔  iCloud Drive / %s", pair.local_dir, pair.remote_dir)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGHUP, _handle_signal)

    write_pid()

    api = authenticate(config.username, config.session_refresh_interval)

    # Per-pair state (parallel lists, indexed same as config.pairs)
    watchers: list[LocalWatcher] = []
    indexes = []
    drive_roots = []

    for pair in config.pairs:
        drive_root = _get_drive_root(api, pair.remote_dir)
        drive_roots.append(drive_root)

        index = load_index(pair.state_file)
        if index is None:
            notify("iCloud Sync", f"First run — bootstrapping from server ({pair.remote_dir})")
            index = bootstrap(drive_root, pair.local_dir, config.exclude_patterns, pair.state_file)
        indexes.append(index)

        watcher = LocalWatcher(pair.local_dir, config.exclude_patterns)
        watcher.start()
        watchers.append(watcher)

    notify("iCloud Sync", f"Sync started — {len(config.pairs)} pair(s)")

    last_poll = 0.0

    try:
        while _running:
            # --- Config reload (SIGHUP) ---
            if _reload:
                _reload = False
                try:
                    new_config = load_config()
                    config.pairs, watchers, indexes, drive_roots = _apply_reload(
                        api, new_config, config.pairs, watchers, indexes, drive_roots
                    )
                    config = new_config
                    logger.info("Config reloaded — %d pair(s) active", len(config.pairs))
                    notify("iCloud Sync", f"Config reloaded — {len(config.pairs)} pair(s) active")
                except Exception as e:
                    logger.error("Config reload failed: %s", e, exc_info=True)

            now = time.monotonic()
            should_poll = (now - last_poll) >= config.poll_interval

            pair_changes = [w.drain() for w in watchers]
            any_pending = any(p or m for p, m in pair_changes)

            if any_pending or should_poll:
                try:
                    api.drive.refresh_root()

                    for i, pair in enumerate(config.pairs):
                        pending, moves = pair_changes[i]

                        if moves:
                            logger.info("[%s] Local renames detected (%d) — syncing",
                                        pair.remote_dir, len(moves))
                        elif pending:
                            logger.info("[%s] Local changes detected (%d files) — syncing",
                                        pair.remote_dir, len(pending))
                        elif should_poll:
                            logger.info("[%s] Polling iCloud Drive...", pair.remote_dir)
                        else:
                            continue

                        drive_roots[i] = _get_drive_root(api, pair.remote_dir)
                        indexes[i] = reconcile(
                            drive_roots[i],
                            pair.local_dir,
                            config.exclude_patterns,
                            indexes[i],
                            pair.state_file,
                            pending,
                            moves=moves,
                            suppress_fn=watchers[i].suppress,
                        )

                    last_poll = now
                except Exception as e:
                    logger.error("Sync cycle error: %s", e, exc_info=True)
                    time.sleep(min(config.poll_interval, 30))

            time.sleep(2)

    finally:
        for w in watchers:
            w.stop()
        clear_pid()
        notify("iCloud Sync", "Sync daemon stopped")
        logger.info("Daemon stopped")


if __name__ == "__main__":
    main()
