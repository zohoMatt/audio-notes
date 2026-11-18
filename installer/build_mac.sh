#!/usr/bin/env bash
# Build dist/Audio Notes.app and dist/Audio-Notes-<version>-arm64.dmg (macOS 14.2+, Apple Silicon).
#
#   installer/build_mac.sh [--skip-dmg]        (from anywhere; works in the repo root)
#
# Steps: Swift capture helper -> PyInstaller BUNDLE -> sign inside-out -> DMG (dmgbuild)
#        -> sign + notarize + staple the DMG (Developer ID only) -> SHA256 file.
#
# Environment (all optional):
#   MACOS_SIGN_IDENTITY       codesign identity, e.g. "Developer ID Application: Name (TEAMID)".
#                             Default "-" = ad-hoc: no Hardened Runtime, no timestamp, no notarization.
#   NOTARY_KEY_PATH, NOTARY_KEY_ID, NOTARY_ISSUER
#                             App Store Connect API key (.p8 path, key id, issuer id). When all three
#                             are set and the identity is a real one, the DMG is notarized and stapled.
#   AUDIO_NOTES_VERSION       version string (default: from git via hatch-vcs)
#   AUDIO_NOTES_BUILD_NUMBER  CFBundleVersion (default: the numeric short version)
#   AUDIO_NOTES_BUILD_DIR     work folder: build venv + PyInstaller cache (default: build)
#   AUDIO_NOTES_DIST_DIR      output folder for the .app and the DMG (default: dist)
#                             With iCloud Drive "Desktop & Documents" on and the checkout under
#                             ~/Documents, point both outside ~/Documents: iCloud tags .app folders
#                             with Finder info (codesign then fails with "resource fork, Finder
#                             information, or similar detritus not allowed") and hides venvs.
#   DMGBUILD_SPEC             what `uvx --from` installs for dmgbuild (default: dmgbuild==2.0.0)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_DMG=0
for arg in "$@"; do
    case "$arg" in
        --skip-dmg) SKIP_DMG=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[[ "$(uname -s)" == Darwin ]] || { echo "build_mac.sh runs on macOS only" >&2; exit 1; }
[[ "$(uname -m)" == arm64 ]] || { echo "build_mac.sh builds the arm64 app; run it on Apple Silicon" >&2; exit 1; }

IDENTITY="${MACOS_SIGN_IDENTITY:--}"
ENTITLEMENTS="$ROOT/installer/entitlements.plist"
BUILD="${AUDIO_NOTES_BUILD_DIR:-$ROOT/build}"
DIST="${AUDIO_NOTES_DIST_DIR:-$ROOT/dist}"
APP="$DIST/Audio Notes.app"

export UV_PROJECT_ENVIRONMENT="$BUILD/venv-mac"
uv sync --locked --python 3.12 --group build --no-dev
# PYTHONPATH=src: import our package straight from the checkout, whether or not the editable
# install's .pth file is honoured (see AUDIO_NOTES_BUILD_DIR above).
export PYTHONPATH="$ROOT/src"

VERSION="${AUDIO_NOTES_VERSION:-$(uv run --no-sync python -c 'from audio_notes import __version__ as v; print(v)')}"
export AUDIO_NOTES_VERSION="$VERSION"
echo "==> Version: $VERSION"

echo "==> Swift capture helper"
swift build -c release --package-path macos/capture
AUDIO_NOTES_CAPTURE_BIN="$(swift build -c release --package-path macos/capture --show-bin-path)/audio-notes-capture"
export AUDIO_NOTES_CAPTURE_BIN

echo "==> PyInstaller"
rm -rf "$APP" "$DIST/audio-notes-mac" "$BUILD/pyi-mac"
uv run --no-sync pyinstaller installer/audio-notes-mac.spec --noconfirm \
    --distpath "$DIST" --workpath "$BUILD/pyi-mac"
rm -rf "$DIST/audio-notes-mac"  # the intermediate COLLECT folder; the .app is the product

# The project is installed into the build venv from this checkout, so its dist-info records the
# checkout path (direct_url.json) and uv's cache keys. Only the version is needed at run time.
find "$APP/Contents" -path '*audio_notes-*.dist-info/*' \
    \( -name direct_url.json -o -name uv_cache.json -o -name uv_build.json \) -delete

# Extended attributes (Finder info, quarantine, provenance) make codesign refuse the bundle.
xattr -cr "$APP"

echo "==> Signing ($([[ "$IDENTITY" == - ]] && echo ad-hoc || echo "$IDENTITY"))"
if [[ "$IDENTITY" == - ]]; then
    # Ad-hoc: the Hardened Runtime would enforce library validation, which ad-hoc signed dylibs
    # (no team id) cannot pass, and it is only needed for notarization anyway.
    SIGN=(codesign --force --sign -)
else
    SIGN=(codesign --force --sign "$IDENTITY" --options runtime --timestamp)
fi
# 1. Every Mach-O file except the three executables in Contents/MacOS, deepest paths first.
#    (PyInstaller puts dylibs and .so files in Contents/Frameworks; Contents/MacOS mostly holds
#    symlinks to them, which `-type f` skips.)
#    (Written for the stock bash 3.2 and BSD tools; no file names here contain newlines.)
find "$APP/Contents" -type f ! -path "$APP/Contents/MacOS/*" \
    | awk -F/ '{print NF "\t" $0}' | sort -t $'\t' -k1,1nr | cut -f2- \
    | while IFS= read -r f; do
        if file -b "$f" | grep -q '^Mach-O'; then
            "${SIGN[@]}" "$f"
        fi
    done
# 2. The capture helper and the two app executables, with the entitlements.
for exe in audio-notes-capture audio-notes "Audio Notes"; do
    "${SIGN[@]}" --entitlements "$ENTITLEMENTS" "$APP/Contents/MacOS/$exe"
done
# 3. The bundle itself (seals Resources, Info.plist and everything above).
"${SIGN[@]}" --entitlements "$ENTITLEMENTS" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

if [[ "$SKIP_DMG" == 1 ]]; then
    echo "==> App: $APP (DMG skipped)"
    exit 0
fi

echo "==> DMG"
DMG="$DIST/Audio-Notes-${VERSION//+/-}-arm64.dmg"
rm -f "$DMG" "$DMG.sha256"
uvx --from "${DMGBUILD_SPEC:-dmgbuild==2.0.0}" dmgbuild \
    -s installer/dmg_settings.py -D app="$APP" "Audio Notes" "$DMG"

if [[ "$IDENTITY" != - ]]; then
    codesign --force --sign "$IDENTITY" --timestamp "$DMG"
    if [[ -n "${NOTARY_KEY_PATH:-}" && -n "${NOTARY_KEY_ID:-}" && -n "${NOTARY_ISSUER:-}" ]]; then
        echo "==> Notarizing (this usually takes a few minutes)"
        xcrun notarytool submit "$DMG" --key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" \
            --issuer "$NOTARY_ISSUER" --wait
        xcrun stapler staple "$DMG"
        xcrun stapler validate "$DMG"
    else
        echo "NOTARY_KEY_PATH / NOTARY_KEY_ID / NOTARY_ISSUER not set: the DMG is signed but not notarized" >&2
    fi
fi

(cd "$(dirname "$DMG")" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")
echo "==> $(cat "$DMG.sha256")"
echo "==> App: $APP"
echo "==> DMG: $DMG"
