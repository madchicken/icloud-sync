# iCloud-Sync

<p align="center">
  <img src="iCloud-sync-icon.png" width="128" alt="iCloud-Sync icon" />
</p>

A lightweight macOS menu bar app and background daemon that keeps local folders in sync with iCloud Drive — built for people who **cannot use Apple's native iCloud Drive integration**.

## Why this exists

If your Mac is enrolled in a corporate Mobile Device Management (MDM) profile, your company may restrict or completely block the native iCloud Drive client. This is common in enterprise environments where IT policies prevent personal cloud storage from running as a system service.

iCloud-Sync works around this by talking directly to iCloud's API (via [pyicloud](https://github.com/timlaing/pyicloud)) from user space — no system extensions, no privileged daemons, no interaction with the macOS iCloud subsystem that MDM profiles lock down. It runs entirely as an unprivileged background process and communicates with iCloud over HTTPS, the same way a web browser would.

## Features

- **Native Swift menu bar app** — start/stop the daemon, manage sync pairs, and configure settings from the macOS status bar
- **Self-contained** — no Python installation required; the `.app` bundle includes its own Python runtime and daemon
- **Multi-folder sync** — sync as many iCloud Drive ↔ local folder pairs as you need
- **Native dialogs** — setup, authentication, and 2FA all use standard macOS dialogs
- **Automatic reload** — adding or removing a sync pair takes effect immediately without restarting the daemon
- **Start at login** — configurable from the Settings dialog
- **Conflict handling** — last-write-wins; the losing version is preserved as `.conflict-TIMESTAMP.ext`

## How it works

- **Menu bar app** is a native Swift/AppKit app (no Dock icon)
- **Sync daemon** is a Python background process bundled inside the app
- **Local changes** are detected instantly via `watchdog` (filesystem events)
- **Remote changes** are detected by polling iCloud Drive every 60 seconds (iCloud has no push API)
- **Session** is kept alive with periodic refresh; Apple sessions last ~2 months

## Requirements

**To run:** macOS 13+. No Python installation required — the `.app` bundle includes its own.

**To build from source:** macOS 13+, Python 3.11+, Xcode 15+.

## Installation

### Download (recommended)

Download the latest `iCloud Sync.dmg` from the [Releases](https://github.com/madchicken/icloud-sync/releases) page, open it, and drag **iCloud Sync.app** to your Applications folder.

Because the app is ad-hoc signed (no Apple Developer ID), remove the quarantine flag once after installing:

```bash
xattr -dr com.apple.quarantine "/Applications/iCloud Sync.app"
```

### Build from source

```bash
git clone https://github.com/madchicken/icloud-sync.git
cd icloud-sync/VirtualiCloud
bash build.sh
```

This produces `VirtualiCloud/dist/iCloud Sync.dmg`.

## First launch

1. Click the cloud icon in the menu bar → **Setup / Credentials…**
2. A Terminal window opens — enter your Apple ID, password, and 2FA code
3. Once setup is complete, go to **Pairings…** to add your first sync pair
4. Click **Start** to begin syncing

Credentials are stored securely in the macOS Keychain.

## Menu bar

| Item | Description |
|---|---|
| **● Running / ○ Stopped** | Current daemon status |
| **Start / Stop** | Start or stop the sync daemon |
| **Sync Pairs** | List of configured sync pairs |
| **Pairings…** | Add or remove iCloud Drive ↔ local folder pairs |
| **Setup / Credentials…** | Sign in or update your Apple ID credentials |
| **Settings…** | Start at login, auto-start daemon, polling interval |
| **Open Log** | Open the sync log |
| **Uninstall…** | Remove the app and all associated files |

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

Files never synced: `.DS_Store`, `*.tmp`, `*.part`, hidden files, `desktop.ini`, `Thumbs.db`.

## Two-factor authentication

During initial setup a Terminal window opens running `icloud-sync setup`, which handles 2FA interactively. When the session expires (~2 months), re-run **Setup / Credentials…** from the menu bar.

## Project structure

```
icloud-sync/
├── VirtualiCloud/              — native Swift menu bar app (Xcode project)
│   ├── project.yml             — xcodegen spec
│   ├── build.sh                — build + sign + package DMG
│   └── VirtualiCloud/
│       ├── App/                — entry point, AppDelegate
│       ├── MenuBar/            — NSStatusItem, menu construction
│       ├── Daemon/             — spawn/stop/monitor Python daemon
│       ├── Config/             — read shared config.json
│       ├── Keychain/           — Security framework (shared with Python)
│       └── UI/                 — Pairings, Settings, Setup, Uninstall dialogs
├── icloud_sync/                — Python sync daemon
│   ├── cli.py                  — icloud-sync CLI (setup, start, add-pair…)
│   ├── sync_daemon.py          — daemon main loop
│   ├── engine.py               — reconciliation logic
│   ├── watcher.py              — local filesystem watcher (watchdog)
│   ├── auth.py                 — Keychain helpers, authentication, 2FA
│   └── config.py               — config, sync pairs, PID file, preferences
├── scripts/
│   ├── make_icon.py            — generates AppIcon.icns from iCloud-sync-icon.png
│   └── make_menubar_icon.py    — generates menu bar template images
└── com.icloud.sync.plist       — launchd agent template (optional CLI use)
```

## Limitations

- iCloud Drive has no push API — remote changes are polled every 60 seconds
- Only top-level iCloud Drive folders can be selected as sync targets
- Does not sync shared folders or iCloud shared albums
- macOS 13+ only

## License

MIT
