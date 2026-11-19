# Remove everything a local Audio Notes test leaves on this Windows PC, so the next test starts
# like a first install: the installed app (silent uninstall), a `uv tool` install, the Claude
# Desktop / Claude Code entries and our config backups, and the transcripts folders.
#
# Usage (PowerShell, from the repository):
#   .\scripts\clean_dev_windows.ps1 -DryRun     # show what would be done
#   .\scripts\clean_dev_windows.ps1             # do it (asks once)
#
# Options:
#   -DryRun        only show what would be done
#   -Yes           do not ask for confirmation
#   -PurgeModels   also delete the downloaded speech models (re-downloaded on use)
#
# Kept: the repository, its virtualenv and build outputs (build\, dist\).
# Quit Claude Desktop first (also from the tray): it rewrites its config while running, and
# `audio-notes clean` skips that config when Claude Desktop is open.
# The macOS counterpart is scripts/clean_dev_mac.sh.

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$PurgeModels
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$hasUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)

Write-Host "Audio Notes cleanup (repository: $Repo)"
Write-Host "  1. Stop audio-notes-tray.exe / audio-notes.exe"
Write-Host "  2. audio-notes clean --uninstall --purge-data: silent uninstall of the installed app,"
Write-Host "     Claude Desktop / Claude Code entries, config backups, transcripts folders"
Write-Host "  3. uv tool uninstall audio-notes (if installed)"
if ($PurgeModels) { Write-Host "  4. Delete the downloaded speech models" }

if (-not $DryRun -and -not $Yes) {
    $answer = Read-Host "Continue? [y/N]"
    if ($answer -notmatch '^[yY]') { Write-Host "Nothing was changed."; exit 1 }
}

Write-Host "== 1. Stop running copies"
$procs = Get-Process -Name "audio-notes-tray", "audio-notes" -ErrorAction SilentlyContinue
foreach ($p in $procs) {
    Write-Host "+ Stop-Process $($p.Name) ($($p.Id))"
    if (-not $DryRun) { Stop-Process -Id $p.Id -Force }
}
if (-not $procs) { Write-Host "none running" }

Write-Host "== 2. Installed app, Claude configs and data"
if ($hasUv) {
    Push-Location $Repo
    try {
        if ($DryRun) {  # its own dry run is safe to execute and lists what it would remove
            Write-Host "+ uv run audio-notes clean --uninstall --purge-data --dry-run"
            uv run --quiet audio-notes clean --uninstall --purge-data --dry-run
        } else {
            Write-Host "+ uv run audio-notes clean --uninstall --purge-data -y"
            uv run --quiet audio-notes clean --uninstall --purge-data -y
        }
    } finally { Pop-Location }
} else {
    Write-Warning "uv not found: skipping ``audio-notes clean``. Install uv, or uninstall Audio Notes from Settings > Apps."
}

Write-Host "== 3. uv tool"
if ($hasUv -and (uv tool list 2>$null | Select-String -Pattern '^audio-notes ' -Quiet)) {
    Write-Host "+ uv tool uninstall audio-notes"
    if (-not $DryRun) { uv tool uninstall audio-notes }
} else {
    Write-Host "not installed as a uv tool"
}

if ($PurgeModels) {
    Write-Host "== 4. Speech models"
    $hub = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
    Get-ChildItem -Path $hub -Directory -Filter "models--Systran--faster-whisper-*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host "+ Remove-Item $($_.FullName)"
            if (-not $DryRun) { Remove-Item -Recurse -Force $_.FullName }
        }
}

if ($DryRun) { Write-Host "Dry run: nothing was changed." }
else { Write-Host "Done. Audio Notes will start like a first install (legal notice, Connect to Claude)." }
