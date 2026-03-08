#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build "iCloud Sync.app" — a fully self-contained macOS app bundle.
#
# The bundle includes its own Python venv so it works on any Mac regardless
# of which Python (if any) is installed on the target machine.
#
# Requirements:
#   - Python 3.11+ available as `python3` (or `python`)
#   - Xcode command-line tools (cc, codesign)
#
# Usage (from the project root):
#   bash scripts/build_app.sh
#
# Output: dist/iCloud Sync.app
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="iCloud Sync"
BUNDLE_ID="com.icloud-sync.tray"
VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('$ROOT/pyproject.toml','rb'))['project']['version'])")"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
MACOS="$CONTENTS/MacOS"

# Resolve a Python 3.11+ interpreter
PYTHON="$(command -v python3 || command -v python)"
PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

echo "▸ Python:  $PYTHON ($PY_VERSION)"
echo "▸ Output:  $APP"

# ── Clean ─────────────────────────────────────────────────────────────────────
rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

# ── Bundled Python venv ───────────────────────────────────────────────────────
# Install the package and all dependencies into a venv inside the bundle.
# The launcher binary finds this venv at runtime via the bundle path.
echo "▸ Creating bundled venv…"
"$PYTHON" -m venv "$RESOURCES/venv"

BUNDLE_PYTHON="$RESOURCES/venv/bin/python3"
echo "▸ Installing package into bundle (this may take a while on first run)…"
"$BUNDLE_PYTHON" -m pip install --quiet --upgrade pip
"$BUNDLE_PYTHON" -m pip install --quiet "$ROOT"

# Verify the entry-point script was created
TRAY_SCRIPT="$RESOURCES/venv/bin/icloud-sync-tray"
if [ ! -f "$TRAY_SCRIPT" ]; then
    echo "Error: icloud-sync-tray not found at $TRAY_SCRIPT"
    exit 1
fi

# ── Launcher binary ───────────────────────────────────────────────────────────
# A real Mach-O binary is required — Gatekeeper rejects shell scripts in
# unsigned .app bundles. The launcher discovers the bundled venv at runtime.
echo "▸ Compiling launcher binary…"
cc -Wall -o "$MACOS/$APP_NAME" "$SCRIPT_DIR/launcher.c"

# ── Resources ─────────────────────────────────────────────────────────────────
cp "$ROOT/AppIcon.icns"                      "$RESOURCES/AppIcon.icns"
cp "$ROOT/assets/menubarTemplate.png"        "$RESOURCES/menubarTemplate.png"
cp "$ROOT/assets/menubarTemplate@2x.png"     "$RESOURCES/menubarTemplate@2x.png"

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
/usr/libexec/PlistBuddy -c "Add :NSUserNotificationAlertStyle string 'alert'"       "$CONTENTS/Info.plist"

# ── Ad-hoc code sign ─────────────────────────────────────────────────────────
# Signing strategy for a venv-bundled app:
#   1. Sign every Mach-O binary in the venv (.so/.dylib + ELF executables).
#      Must be done before sealing the outer bundle.
#   2. Sign the launcher binary explicitly.
#   3. Sign the bundle WITHOUT --deep: --deep re-signs nested code in
#      an unpredictable order and corrupts the seal we built in step 1.
echo "▸ Signing venv Mach-O binaries…"
find "$RESOURCES/venv" \( -name "*.so" -o -name "*.dylib" \) \
    -exec codesign --force --sign - {} \;

# Sign any Mach-O executables in venv/bin (Python interpreter etc.)
while IFS= read -r f; do
    if file "$f" | grep -q "Mach-O"; then
        codesign --force --sign - "$f"
    fi
done < <(find "$RESOURCES/venv/bin" -type f)

echo "▸ Signing launcher…"
codesign --force --sign - "$MACOS/$APP_NAME"

echo "▸ Sealing app bundle…"
codesign --force --sign - "$APP"

echo "✓ Built: $APP"
echo ""
echo "To install:"
echo "  1. cp -r \"$APP\" /Applications/"
echo "  2. xattr -cr \"/Applications/$APP_NAME.app\"   # remove quarantine flag"
echo ""
echo "Or right-click → Open in Finder to approve it interactively."
