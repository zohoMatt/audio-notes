#!/usr/bin/env bash
# Remove everything a local Audio Notes test leaves on this Mac, so the next test starts like a
# first install: the app, its registrations and permissions, a `uv tool` install, the Claude
# Desktop / Claude Code entries, and the data and log folders.
#
# Usage (from anywhere in the repository):
#   scripts/clean_dev_mac.sh --dry-run    # show what would be done
#   scripts/clean_dev_mac.sh              # do it (asks once)
#
# Options:
#   -n, --dry-run                 only print the commands
#   -y, --yes                     do not ask for confirmation
#   --keep-terminal-permissions   do not reset the Microphone / System Audio Recording permissions
#                                 of Terminal, iTerm and Claude Code (they also affect other tools)
#   --purge-models                also delete the downloaded speech models (re-downloaded on use)
#
# Kept: the repository, its virtualenv and build outputs (macos/capture/.build, dist/).
# Quit Claude Desktop first (Cmd+Q): it rewrites its config while running, and `audio-notes clean`
# skips that config when Claude Desktop is open.
# The Windows counterpart is scripts/clean_dev_windows.ps1.

set -uo pipefail

BUNDLE_ID="io.github.zohomatt.audionotes"
APP_NAME="Audio Notes"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
# Apps that started Audio Notes during development, and so hold its permissions (TCC credits the
# launching app): Terminal, iTerm, Claude Code.
DEV_HOST_BUNDLES=(com.apple.Terminal com.googlecode.iterm2 com.anthropic.claude-code)

DRY=0 YES=0 KEEP_TERMINAL=0 PURGE_MODELS=0
for arg in "$@"; do
    case "$arg" in
        -n|--dry-run) DRY=1 ;;
        -y|--yes) YES=1 ;;
        --keep-terminal-permissions) KEEP_TERMINAL=1 ;;
        --purge-models) PURGE_MODELS=1 ;;
        -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

[[ "$(uname)" == Darwin ]] || { echo "This script is for macOS; on Windows use scripts/clean_dev_windows.ps1." >&2; exit 2; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"

run() {  # print, then run unless --dry-run
    echo "+ $*"
    [[ $DRY == 1 ]] || "$@"
}

# Installed copies of the app: the usual places, plus whatever Spotlight knows by bundle id.
apps=()
for p in "/Applications/$APP_NAME.app" "$HOME/Applications/$APP_NAME.app"; do
    [[ -d "$p" ]] && apps+=("$p")
done
while IFS= read -r p; do
    [[ -n "$p" && -d "$p" ]] || continue
    [[ " ${apps[*]-} " == *" $p "* ]] || apps+=("$p")
done < <(mdfind "kMDItemCFBundleIdentifier == '$BUNDLE_ID'" 2>/dev/null)

echo "Audio Notes cleanup (repository: $REPO)"
echo "  1. Quit Audio Notes, its capture helpers, and eject a mounted Audio Notes disk image"
echo "  2. Reset Microphone / System Audio Recording permissions of $BUNDLE_ID"
[[ $KEEP_TERMINAL == 1 ]] || echo "     and of ${DEV_HOST_BUNDLES[*]}"
echo "  3. audio-notes clean --purge-data: Claude Desktop / Claude Code entries, config backups,"
echo "     ~/Library/Application Support/$APP_NAME and ~/Library/Logs/$APP_NAME"
if ((${#apps[@]})); then
    echo "  4. Unregister and delete: ${apps[*]}"
else
    echo "  4. No installed Audio Notes.app found"
fi
echo "  5. uv tool uninstall audio-notes (if installed)"
[[ $PURGE_MODELS == 1 ]] && echo "  6. Delete the downloaded speech models (~/.cache/huggingface/hub/models--Systran--faster-whisper-*)"

if [[ $DRY == 0 && $YES == 0 ]]; then
    read -r -p "Continue? [y/N] " answer
    [[ "$answer" == [yY]* ]] || { echo "Nothing was changed."; exit 1; }
fi

echo "== 1. Quit"
if pgrep -x "$APP_NAME" >/dev/null; then
    run osascript -e "quit app id \"$BUNDLE_ID\""
    [[ $DRY == 1 ]] || sleep 2
fi
# `audio-notes tray` / `record` started from a shell or the repository, then any helper left over.
for pattern in "audio-notes (tray|record)" "audio_notes (tray|record)"; do
    pgrep -f "$pattern" >/dev/null && run pkill -f "$pattern"
done
pgrep -x "$APP_NAME" >/dev/null && run pkill -x "$APP_NAME"
pgrep -x audio-notes-capture >/dev/null && run pkill -x audio-notes-capture
for vol in "/Volumes/$APP_NAME"*; do
    [[ -d "$vol" ]] && run hdiutil detach "$vol" -quiet
done

echo "== 2. Permissions"
# Before deleting the app: tccutil resolves the bundle id through LaunchServices.
hosts=("$BUNDLE_ID")
[[ $KEEP_TERMINAL == 1 ]] || hosts+=("${DEV_HOST_BUNDLES[@]}")
for bundle in "${hosts[@]}"; do
    for service in Microphone AudioCapture; do
        if [[ $DRY == 1 ]]; then
            echo "+ tccutil reset $service $bundle"
        else
            tccutil reset "$service" "$bundle" >/dev/null 2>&1 \
                && echo "reset $service for $bundle" \
                || echo "skipped $service for $bundle (not registered on this Mac)"
        fi
    done
done

echo "== 3. Claude configs and data"
if command -v uv >/dev/null; then
    if [[ $DRY == 1 ]]; then  # its own dry run is safe to execute and lists what it would remove
        echo "+ uv run audio-notes clean --purge-data --dry-run"
        (cd "$REPO" && uv run --quiet audio-notes clean --purge-data --dry-run)
    else
        (cd "$REPO" && run uv run --quiet audio-notes clean --purge-data -y)
    fi
else
    echo "uv not found: skipping \`audio-notes clean\`; removing the data folders only"
    run rm -rf "$HOME/Library/Application Support/$APP_NAME" "$HOME/Library/Logs/$APP_NAME"
fi

echo "== 4. App"
for app in ${apps[@]+"${apps[@]}"}; do
    run "$LSREGISTER" -u "$app"
    run rm -rf "$app"
done

echo "== 5. uv tool"
if command -v uv >/dev/null && uv tool list 2>/dev/null | grep -q '^audio-notes '; then
    run uv tool uninstall audio-notes
else
    echo "not installed as a uv tool"
fi

if [[ $PURGE_MODELS == 1 ]]; then
    echo "== 6. Speech models"
    for m in "$HOME"/.cache/huggingface/hub/models--Systran--faster-whisper-*; do
        [[ -e "$m" ]] && run rm -rf "$m"
    done
fi

if [[ $DRY == 1 ]]; then
    echo "Dry run: nothing was changed."
else
    echo "Done. Audio Notes will start like a first install (notice, permission prompts)."
fi
