#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# iCloud Sync — Installer
# Double-click this file in Finder to install the app.
# ---------------------------------------------------------------------------
set -euo pipefail

APP_NAME="iCloud Sync"
APP="/Applications/$APP_NAME.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
MACOS="$CONTENTS/MacOS"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing $APP_NAME…"
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.11+ from https://python.org"
    exit 1
fi

PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
if [ "$PY_MINOR" -lt 11 ]; then
    echo "Error: Python 3.11+ is required (found 3.$PY_MINOR)"
    exit 1
fi

# ── Remove previous installation ──────────────────────────────────────────────
rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

# ── Bundled Python venv ───────────────────────────────────────────────────────
echo "  Setting up Python environment (may take a few minutes on first run)…"
python3 -m venv "$RESOURCES/venv"
"$RESOURCES/venv/bin/pip" install --quiet --upgrade pip

# Install from the wheel included in this DMG
WHEEL="$(find "$SCRIPT_DIR" -name "*.whl" | head -1)"
if [ -n "$WHEEL" ]; then
    "$RESOURCES/venv/bin/pip" install --quiet "$WHEEL"
else
    echo "  Wheel not found — installing from GitHub…"
    "$RESOURCES/venv/bin/pip" install --quiet \
        "git+https://github.com/madchicken/icloud-sync.git"
fi

# ── Launcher binary ───────────────────────────────────────────────────────────
cp "$SCRIPT_DIR/launcher" "$MACOS/$APP_NAME"
chmod +x "$MACOS/$APP_NAME"

# ── Resources ─────────────────────────────────────────────────────────────────
cp "$SCRIPT_DIR/AppIcon.icns"              "$RESOURCES/"
cp "$SCRIPT_DIR/menubarTemplate.png"       "$RESOURCES/"
cp "$SCRIPT_DIR/menubarTemplate@2x.png"    "$RESOURCES/"

# ── Info.plist ────────────────────────────────────────────────────────────────
VERSION="$(cat "$SCRIPT_DIR/version.txt" 2>/dev/null || echo "0.0.0")"
BUNDLE_ID="com.icloud-sync.tray"

/usr/libexec/PlistBuddy -c "Add :CFBundleName                 string '$APP_NAME'"   "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName          string '$APP_NAME'"   "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier           string '$BUNDLE_ID'"  "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion              string '$VERSION'"    "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString   string '$VERSION'"    "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable           string '$APP_NAME'"   "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIconFile             string 'AppIcon'"     "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundlePackageType          string 'APPL'"        "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleSignature            string '????'"        "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSUIElement                  bool   true"          "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Add :NSUserNotificationAlertStyle string 'alert'"       "$CONTENTS/Info.plist"

# ── Code sign ─────────────────────────────────────────────────────────────────
# The app is built locally so there is no quarantine flag — Gatekeeper does not
# apply. We still need ad-hoc signatures on Mach-O binaries for Apple Silicon.
echo "  Signing…"

while IFS= read -r f; do
    if file "$f" | grep -q "Mach-O"; then
        codesign --force --sign - "$f" 2>/dev/null || true
    fi
done < <(find "$RESOURCES/venv/bin" -type f)

find "$RESOURCES/venv" \( -name "*.so" -o -name "*.dylib" \) \
    -exec codesign --force --sign - {} \; 2>/dev/null || true

codesign --force --sign - "$APP"

echo ""
echo "✓ Installed: $APP"
echo ""
echo "Launching…"
open "$APP"
