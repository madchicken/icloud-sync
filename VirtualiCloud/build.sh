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

# Bundle a self-contained, relocatable Python (python-build-standalone via uv).
# Unlike a `python -m venv` off Homebrew/system Python, this interpreter links
# its libpython with an @executable_path-relative rpath, so it keeps working
# wherever the .app lands and survives `brew upgrade python@3.14`.
RESOURCES="$APP/Contents/Resources"
VENV="$RESOURCES/venv"
PYVER=3.14
echo "Bundling standalone Python $PYVER..."

command -v uv >/dev/null || { echo "uv is required to build (https://docs.astral.sh/uv/)"; exit 1; }
uv python install "$PYVER"
# Copy the whole standalone install into the bundle. Use the canonical prefix
# (sys.prefix, e.g. cpython-3.14.3-...) — NOT the `cpython-3.14-...` alias dir,
# which is a symlink whose copy resolves its prefix back to the original. The
# canonical copy resolves its prefix to itself relative to the executable, so it
# works on the build machine AND on the user's Mac (where ~/.local/share/uv is
# absent), surviving `brew upgrade`.
STD_PY="$(UV_PYTHON_PREFERENCE=only-managed uv python find "$PYVER")"
STANDALONE_PREFIX="$("$STD_PY" -c 'import sys; print(sys.prefix)')"

rm -rf "$VENV"
cp -R "$STANDALONE_PREFIX" "$VENV"

# Install the daemon INTO the copy. `--prefix "$VENV"` pins the install location
# to the bundle (deterministic regardless of prefix resolution). `--break-system-
# packages` lifts the PEP-668 guard uv stamps on managed interpreters — this is
# our private copy, so modifying it is intended. DaemonManager runs
# `python3 <script> start`, so the script's absolute shebang is never used —
# only the installed module on sys.path matters.
echo "Installing daemon into bundled Python..."
"$VENV/bin/python3" -m pip install --quiet --break-system-packages --prefix "$VENV" "$SCRIPT_DIR/.."
"$VENV/bin/python3" -c "import icloud_sync, pyicloud" \
  && [ -f "$VENV/bin/icloud-sync" ] \
  || { echo "Bundled Python is broken or daemon not installed"; exit 1; }
echo "Bundled: standalone Python $("$VENV/bin/python3" -c 'import sys; print(sys.version.split()[0])') + icloud-sync"

# Sign venv Mach-O binaries before sealing the bundle
echo "Pre-signing venv binaries..."
while IFS= read -r f; do
  if file "$f" | grep -q "Mach-O"; then
    codesign --force --sign - "$f" 2>/dev/null || true
  fi
done < <(find "$VENV/bin" -type f)
find "$VENV" \( -name "*.so" -o -name "*.dylib" \) \
  -exec codesign --force --sign - {} \; 2>/dev/null || true

# Sign the whole bundle. --deep is required: the bundle now contains a large
# nested Python tree (interpreter + hundreds of .so/.dylib). Without it the
# outer seal doesn't cover the nested code and `codesign -v` reports
# "a sealed resource is missing or invalid", which Gatekeeper rejects.
echo "Signing..."
codesign --force --deep --sign - "$APP"
codesign --verify --strict "$APP" || { echo "Code signature invalid"; exit 1; }

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
