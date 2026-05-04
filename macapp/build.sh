#!/usr/bin/env bash
# build.sh — build Reading Tracker.app from sources without Xcode (CLT only).
#
# Outputs: macapp/build/Reading Tracker.app
# Requires: macOS 13+, Xcode Command Line Tools (`xcode-select --install`).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Reading Tracker"
BUILD_DIR="$ROOT/build"
APP_BUNDLE="$BUILD_DIR/${APP_NAME}.app"
SOURCES_DIR="$ROOT/Sources"
RESOURCES_DIR="$ROOT/Resources"
INFO_PLIST_SRC="$ROOT/Info.plist"
ENT="$ROOT/ReadingTracker.entitlements"

DEPLOY_TARGET="13.0"
ARCH_HOST="$(uname -m)"   # arm64 | x86_64

mkdir -p "$BUILD_DIR"

# ---------- 1) Icon (regenerate if missing or stale) ----------
ICONSET="$BUILD_DIR/AppIcon.iconset"
ICNS="$RESOURCES_DIR/AppIcon.icns"
if [[ ! -f "$ICNS" ]] || [[ "$RESOURCES_DIR/make_icon.swift" -nt "$ICNS" ]]; then
    echo "==> Rendering app icon"
    rm -rf "$ICONSET"
    swift "$RESOURCES_DIR/make_icon.swift" "$ICONSET"
    iconutil -c icns "$ICONSET" -o "$ICNS"
fi

# ---------- 2) Compile binary ----------
echo "==> Compiling Swift sources for $ARCH_HOST (deploy target macOS $DEPLOY_TARGET)"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Build for both architectures when both SDK slices are available; otherwise host only.
SWIFT_FLAGS=(
    -O
    -parse-as-library
    -framework AppKit
    -framework SwiftUI
    -framework Combine
)

build_one_arch() {
    local arch="$1" out="$2"
    swiftc "${SWIFT_FLAGS[@]}" \
        -target "${arch}-apple-macos${DEPLOY_TARGET}" \
        -o "$out" \
        "$SOURCES_DIR"/*.swift
}

# Try universal; fall back to host-only if cross-compile fails.
ARM_BIN="$BUILD_DIR/.bin-arm64"
X64_BIN="$BUILD_DIR/.bin-x86_64"
if build_one_arch arm64 "$ARM_BIN" 2>/dev/null && build_one_arch x86_64 "$X64_BIN" 2>/dev/null; then
    echo "==> Linking universal binary (arm64 + x86_64)"
    lipo -create -output "$APP_BUNDLE/Contents/MacOS/$APP_NAME" "$ARM_BIN" "$X64_BIN"
    rm -f "$ARM_BIN" "$X64_BIN"
else
    echo "==> Cross-compile unavailable, building $ARCH_HOST only"
    build_one_arch "$ARCH_HOST" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
fi
chmod +x "$APP_BUNDLE/Contents/MacOS/$APP_NAME"

# ---------- 3) Assemble bundle ----------
echo "==> Assembling bundle"
cp "$INFO_PLIST_SRC" "$APP_BUNDLE/Contents/Info.plist"
cp "$ICNS" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"

PB=/usr/libexec/PlistBuddy
plist="$APP_BUNDLE/Contents/Info.plist"
$PB -c "Add :CFBundleExecutable string ${APP_NAME}" "$plist" 2>/dev/null \
    || $PB -c "Set :CFBundleExecutable ${APP_NAME}" "$plist"
$PB -c "Add :CFBundleIconFile string AppIcon" "$plist" 2>/dev/null \
    || $PB -c "Set :CFBundleIconFile AppIcon" "$plist"

# ---------- 4) Ad-hoc sign with entitlements ----------
echo "==> Ad-hoc signing"
# Strip extended attributes (resource forks/Finder info) that codesign rejects.
xattr -cr "$APP_BUNDLE"
codesign --sign - --force --options runtime \
    --entitlements "$ENT" \
    --timestamp=none \
    "$APP_BUNDLE"
codesign --verify --verbose=2 "$APP_BUNDLE" 2>&1 | sed 's/^/    /'

echo
echo "Built: $APP_BUNDLE"
echo "Run:   open \"$APP_BUNDLE\""
