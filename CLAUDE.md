# virtualicloud

## Project
iCloud Drive sync daemon for macOS using pyicloud.

## Structure
- `icloud_sync/` — sync daemon package (config, auth, engine, watcher, state, daemon)
- `com.icloud.sync.plist` — launchd agent template (edit paths before installing)
- `pyproject.toml` — depends on local `~/Projects/pyicloud` via `file://` path

## Dependencies
- pyicloud: local install at `~/Projects/pyicloud` (not on PyPI — use the local fork)
- watchdog>=4.0: local FS change detection
- Credentials stored in macOS Keychain via `icloud --username=...` (pyicloud CLI)

## Running
```
ICLOUD_USERNAME=you@icloud.com ICLOUD_LOCAL_DIR=~/Documents/iCloudSync .venv/bin/python -m icloud_sync.sync_daemon
```

## Key gotchas
- iCloud Drive has no push API — sync is poll-based (default 60s interval)
- `drive_file.date_modified` is UTC naive datetime; convert with `replace(tzinfo=timezone.utc)`
- 2FA in daemon mode: daemon waits for `echo CODE > ~/.icloud_sync_2fa_code`
- Apple session expires ~2 months; `refresh_interval=300` keeps it alive between expirations
- Do not poll more aggressively than 60s — iCloud rate-limits
