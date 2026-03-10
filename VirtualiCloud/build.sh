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

echo "Building $APP_NAME v$VERSION..."

# Build
set +o pipefail  # let xcodebuild exit code propagate through the tee
xcodebuild \
  -project "$SCRIPT_DIR/VirtualiCloud.xcodeproj" \
  -scheme "$SCHEME" \
  -configuration Release \
  -derivedDataPath "$BUILD_DIR" \
  build 2>&1 | tee /tmp/xcodebuild.log | grep -E "error:|BUILD SUCCEEDED|BUILD FAILED" | grep -v "DVTPlugin" || true
set -o pipefail

if ! grep -q "BUILD SUCCEEDED" /tmp/xcodebuild.log; then
  echo "Build failed. Full log:"
  cat /tmp/xcodebuild.log
  exit 1
fi
echo "Build succeeded."

# Sign
echo "Signing..."
codesign --force --deep --sign - "$APP"

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
