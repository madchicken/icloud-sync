#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="iCloud Sync"
SCHEME="VirtualiCloud"
BUILD_DIR="$SCRIPT_DIR/build"
DIST_DIR="$SCRIPT_DIR/dist"
APP="$BUILD_DIR/Build/Products/Release/$APP_NAME.app"
DMG="$DIST_DIR/$APP_NAME.dmg"
STAGING="/tmp/icloud-sync-dmg-$$"

VERSION=$(python3 -c \
  "import tomllib; print(tomllib.load(open('$SCRIPT_DIR/../pyproject.toml','rb'))['project']['version'])" \
  2>/dev/null || echo "0.0.0")

# Monotonic build number from git commit count (Sparkle uses this to compare versions)
BUILD_NUMBER=$(git -C "$SCRIPT_DIR/.." rev-list --count HEAD 2>/dev/null || echo "1")

echo "Building $APP_NAME v$VERSION (build $BUILD_NUMBER)..."

# Build
set +o pipefail  # let xcodebuild exit code propagate through the tee
xcodebuild \
  -project "$SCRIPT_DIR/VirtualiCloud.xcodeproj" \
  -scheme "$SCHEME" \
  -configuration Release \
  -derivedDataPath "$BUILD_DIR" \
  CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  build 2>&1 | tee /tmp/xcodebuild.log | grep -E "error:|BUILD SUCCEEDED|BUILD FAILED" | grep -v "DVTPlugin" || true
set -o pipefail

if ! grep -q "BUILD SUCCEEDED" /tmp/xcodebuild.log; then
  echo "Build failed. Full log:"
  cat /tmp/xcodebuild.log
  exit 1
fi
echo "Build succeeded."

# Bundle Python venv
# Install the Python daemon inside the .app so it works on any Mac
# without requiring a separate pip install.
RESOURCES="$APP/Contents/Resources"
VENV="$RESOURCES/venv"
echo "Bundling Python venv..."
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$SCRIPT_DIR/.."
echo "Bundled: $("$VENV/bin/icloud-sync" --help 2>&1 | head -1 || echo 'installed')"

# Make venv portable: replace absolute symlinks with real binaries
echo "Making venv portable..."
REAL_PYTHON="$(readlink -f "$VENV/bin/python3")"
rm -f "$VENV/bin/python3"
cp "$REAL_PYTHON" "$VENV/bin/python3"
# Point python → python3 as a relative symlink
rm -f "$VENV/bin/python"
ln -s python3 "$VENV/bin/python"
# Remove version-specific and novelty symlinks that point outside the venv
find "$VENV/bin" -name 'python3.*' -type l -delete
find "$VENV/bin" -type l ! -exec test -e {} \; -delete

# Sign venv Mach-O binaries before sealing the bundle
echo "Pre-signing venv binaries..."
while IFS= read -r f; do
  if file "$f" | grep -q "Mach-O"; then
    codesign --force --sign - "$f" 2>/dev/null || true
  fi
done < <(find "$VENV/bin" -type f)
find "$VENV" \( -name "*.so" -o -name "*.dylib" \) \
  -exec codesign --force --sign - {} \; 2>/dev/null || true

# Sign the whole bundle
echo "Signing..."
codesign --force --sign - "$APP"

# DMG
echo "Creating DMG..."
mkdir -p "$DIST_DIR"
rm -rf "$STAGING"
mkdir "$STAGING"
cp -r "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

rm -f "$DMG"
hdiutil create \
  -volname "$APP_NAME $VERSION" \
  -srcfolder "$STAGING" \
  -ov -format UDZO \
  "$DMG"

rm -rf "$STAGING"

echo ""
echo "Done: $DMG"
echo ""
echo "Install:"
echo "  1. Open the DMG and drag iCloud Sync.app to Applications"
echo "  2. xattr -dr com.apple.quarantine \"/Applications/$APP_NAME.app\""
