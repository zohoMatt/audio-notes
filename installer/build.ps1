<#
 Build the PyInstaller onedir bundle (and the Inno Setup installer if iscc is found).
 Usage (repo root):  pwsh installer/build.ps1 [-Version 1.2.3] [-SkipInstaller]
 Uses an isolated environment under build\ so the shared .venv is never touched.
#>
param(
    [string]$Version = "",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:UV_PROJECT_ENVIRONMENT = Join-Path $root "build\venv"
uv sync --locked --group build --no-dev
if ($LASTEXITCODE) { throw "uv sync failed" }

if (-not $Version) {
    $Version = (& uv run --no-sync python -c "from audio_notes import __version__ as v; print(v)").Trim()
}
# Inno wants a plain dotted version; drop local/dev suffixes (+g1234, .dev3).
$InnoVersion = ($Version -replace '[+].*$', '') -replace '\.dev\d+', ''
Write-Host "Version: $Version (installer: $InnoVersion)"

# When you run the bundle from dist\, your transcripts live in dist\audio-notes\data and
# PyInstaller replaces the whole output folder, so move that folder aside and put it back.
$keep = "$root\build\data-keep"
Remove-Item -Recurse -Force $keep -ErrorAction SilentlyContinue
if (Test-Path "$root\dist\audio-notes\data") { Move-Item "$root\dist\audio-notes\data" $keep }
Remove-Item -Recurse -Force "$root\dist\audio-notes", "$root\build\pyi" -ErrorAction SilentlyContinue
uv run --no-sync pyinstaller installer\audio-notes.spec --noconfirm --distpath dist --workpath build\pyi
$pyiExit = $LASTEXITCODE
if (Test-Path $keep) {
    New-Item -ItemType Directory -Force "$root\dist\audio-notes" | Out-Null
    Move-Item $keep "$root\dist\audio-notes\data"
}
if ($pyiExit) { throw "PyInstaller failed" }

# The project is installed into build\venv from this checkout, so its dist-info records the
# checkout path (direct_url.json) and uv's cache keys. Only the version metadata is needed at
# run time (`--version`); don't ship the build machine's paths.
Get-ChildItem "$root\dist\audio-notes\_internal\audio_notes-*.dist-info" -Directory | ForEach-Object {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $_.FullName "direct_url.json"),
        (Join-Path $_.FullName "uv_cache.json"), (Join-Path $_.FullName "uv_build.json")
}

$size = (Get-ChildItem "$root\dist\audio-notes" -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Bundle: dist\audio-notes ({0:N0} MB)" -f $size)

if ($SkipInstaller) { return }
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) { Write-Warning "Inno Setup (iscc) not found; skipping installer. Install: winget install JRSoftware.InnoSetup"; return }
& $iscc "/DAppVersion=$InnoVersion" installer\audio-notes.iss
if ($LASTEXITCODE) { throw "iscc failed" }
Write-Host "Installer: dist\Audio-Notes-$InnoVersion-windows-x64-setup.exe"
