#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build "iCloud Sync.app" — a self-contained macOS app bundle.
#
# Requirements: pip install -e . must have been run first.
#               Run:  bash scripts/build_app.sh
#               Output: dist/iCloud Sync.app
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="iCloud Sync"
BUNDLE_ID="com.icloud-sync.tray"
VERSION="0.1.0"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
MACOS="$CONTENTS/MacOS"

# Resolve the Python interpreter that has the package installed
PYTHON="$(python -c 'import sys; print(sys.executable)')"

echo "▸ Python:  $PYTHON"
echo "▸ Output:  $APP"

# ── Clean ─────────────────────────────────────────────────────────────────────
rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

# ── Launcher script ───────────────────────────────────────────────────────────
# The macOS executable is a tiny shell script that delegates to Python.
# It passes the bundle's Resources path so the tray app can find its assets.
# Resolve the installed icloud-sync-tray script
TRAY_SCRIPT="$(dirname "$PYTHON")/icloud-sync-tray"
if [ ! -f "$TRAY_SCRIPT" ]; then
    echo "Error: icloud-sync-tray not found at $TRAY_SCRIPT"
    echo "Run: pip install -e ."
    exit 1
fi

# Compile a real binary launcher — shell scripts are blocked by Gatekeeper
# in unsigned .app bundles launched from Finder.
echo "▸ Compiling launcher binary…"
cc -Wall -o "$MACOS/$APP_NAME" \
    -DPYTHON_BIN='"'"$PYTHON"'"' \
    -DTRAY_SCRIPT='"'"$TRAY_SCRIPT"'"' \
    "$SCRIPT_DIR/launcher.c"

# ── Resources ─────────────────────────────────────────────────────────────────
cp "$ROOT/AppIcon.icns"                          "$RESOURCES/AppIcon.icns"
cp "$ROOT/assets/menubarTemplate.png"            "$RESOURCES/menubarTemplate.png"
cp "$ROOT/assets/menubarTemplate@2x.png"         "$RESOURCES/menubarTemplate@2x.png"

# ── Info.plist ────────────────────────────────────────────────────────────────
/usr/libexec/PlistBuddy -c "Add :CFBundleName                 string '$APP_NAME'"   "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName          string '$APP_NAME'"   "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier           string '$BUNDLE_ID'"  "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion              string '$VERSION'"    "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString   string '$VERSION'"    "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable           string '$APP_NAME'"   "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile             string 'AppIcon'"     "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType          string 'APPL'"        "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleSignature            string '????'"        "$CONTENTS/Info.plist"
# LSUIElement = 1 → no Dock icon; pure menu bar app
/usr/libexec/PlistBuddy -c "Add :LSUIElement                  bool   true"          "$CONTENTS/Info.plist"
# Allow macOS notifications without a signed bundle
/usr/libexec/PlistBuddy -c "Add :NSUserNotificationAlertStyle string 'alert'"       "$CONTENTS/Info.plist"

# ── Ad-hoc code sign ─────────────────────────────────────────────────────────
# Required on macOS 10.15+ for Finder-launched apps. "-" = no certificate.
echo "▸ Signing…"
codesign --force --deep --sign - "$APP"

echo "✓ Built: $APP"
echo ""
echo "To install:"
echo "  1. cp -r \"$APP\" /Applications/"
echo "  2. sudo spctl --add \"/Applications/$APP_NAME.app\"   # allow in Gatekeeper"
echo ""
echo "Or right-click → Open in Finder to approve it interactively."
