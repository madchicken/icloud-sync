# virtualicloud

A lightweight background daemon that keeps a local folder in sync with an iCloud Drive folder on macOS, built on [pyicloud](https://github.com/timlaing/pyicloud).

## How it works

- **Local changes** are detected instantly via `watchdog` (filesystem events)
- **Remote changes** are detected by polling iCloud Drive every 60 seconds (iCloud has no push API)
- **Conflicts** are resolved by last-write-wins; the losing version is saved as `.conflict-TIMESTAMP.ext`

## Requirements

- macOS
- Python 3.11+
- [pyicloud](https://github.com/timlaing/pyicloud) cloned locally at `~/Projects/pyicloud`

## Setup

### 1. Install dependencies

```bash
cd ~/Projects/virtualicloud
python -m venv .venv
.venv/bin/pip install -e .
```

### 2. Store credentials in macOS Keychain

Run the built-in setup command. It will prompt for your password, verify the login (including 2FA if enabled), and store credentials in the macOS Keychain:

```bash
.venv/bin/icloud-sync setup --username you@icloud.com
```

To verify credentials are stored:

```bash
.venv/bin/icloud-sync status --username you@icloud.com
```

To remove stored credentials:

```bash
.venv/bin/icloud-sync setup --username you@icloud.com --delete
```

### 3. Test run

```bash
ICLOUD_USERNAME=you@icloud.com \
ICLOUD_LOCAL_DIR=~/Documents/iCloudSync \
ICLOUD_REMOTE_DIR=SyncFolder \
.venv/bin/icloud-sync start
```

The daemon will:
1. Create `~/Documents/iCloudSync` locally if it doesn't exist
2. Create `SyncFolder` in iCloud Drive if it doesn't exist
3. Perform an initial full sync
4. Watch for local changes and poll for remote changes every 60 seconds

Logs are written to `~/Library/Logs/icloud_sync.log` and to stdout.

### 4. Install as a launchd agent (runs at login, auto-restarts)

Edit `com.icloud.sync.plist` — replace `YOUR_USER` and the paths with your actual values:

```xml
<string>/Users/YOUR_USER/Projects/virtualicloud/.venv/bin/icloud-sync</string>
<string>start</string>
...
<key>ICLOUD_USERNAME</key>
<string>you@icloud.com</string>
<key>ICLOUD_LOCAL_DIR</key>
<string>/Users/YOUR_USER/Documents/iCloudSync</string>
```

Then install it:

```bash
cp com.icloud.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.icloud.sync.plist
```

To stop and uninstall:

```bash
launchctl unload ~/Library/LaunchAgents/com.icloud.sync.plist
rm ~/Library/LaunchAgents/com.icloud.sync.plist
```

## Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `ICLOUD_USERNAME` | yes | — | Apple ID email |
| `ICLOUD_LOCAL_DIR` | yes | — | Local folder to sync |
| `ICLOUD_REMOTE_DIR` | no | `SyncFolder` | iCloud Drive folder name |
| `ICLOUD_POLL_INTERVAL` | no | `60` | Seconds between remote polls |

## Two-factor authentication

During `icloud-sync setup`, 2FA is handled interactively in the terminal.

When the daemon is running and the session expires (Apple sessions last ~2 months), re-authentication is needed. The daemon will send a macOS notification and wait for you to supply the code:

```bash
echo 123456 > ~/.icloud_sync_2fa_code
```

To avoid this, re-run `icloud-sync setup` before the session expires, which refreshes the stored credentials.

## Sync behaviour

| Situation | Action |
|---|---|
| New file on remote | Download to local |
| New file on local | Upload to remote |
| Remote file newer than last sync | Download, overwrite local |
| Local file newer than last sync | Upload, overwrite remote |
| Both modified (conflict) | Last-write-wins; loser saved as `.conflict-TIMESTAMP.ext` |
| Deleted on remote | Delete local |
| Deleted on local | Delete remote |

### Excluded files

The following are never synced: `.DS_Store`, `*.tmp`, `*.part`, hidden files (`.`-prefixed), `desktop.ini`, `Thumbs.db`.

## Project structure

```
virtualicloud/
├── icloud_sync/
│   ├── cli.py          — icloud-sync entry point (setup / status / start)
│   ├── auth.py         — keychain helpers, authentication, 2FA handling
│   ├── config.py       — configuration dataclass
│   ├── state.py        — sync state persistence (JSON)
│   ├── engine.py       — reconciliation logic, remote/local walk
│   ├── watcher.py      — local filesystem watcher (watchdog)
│   └── sync_daemon.py  — daemon main loop
└── com.icloud.sync.plist  — launchd agent template
```
