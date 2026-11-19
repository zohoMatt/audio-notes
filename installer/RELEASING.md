# Releasing

Everything the workflows can do on their own is in `.github/workflows/`. These are the steps only
the repository owner can do. The workflows have **not** been run on GitHub yet; expect to fix small
things on the first tag (try a `v0.0.1rc1`-style tag first; PyPI versions can never be reused).

## Installer only (no PyPI setup needed)

The installer jobs do not depend on PyPI. Pushing a tag builds the Windows installer and the
macOS DMG and attaches both to a GitHub Release, with their SHA256 in the notes:

```
git tag v0.1.0a1
git push origin v0.1.0a1
```

- Tags like `v0.1.0a1`, `v0.1.0rc1`, `v0.1.0.dev1` are marked as **pre-releases** automatically.
- The PyPI jobs are skipped until you set the repository variable `PUBLISH_TO_PYPI` to `true`
  (Settings > Secrets and variables > Actions > Variables), after the setup below.
- To try the build without publishing anything: Actions tab > Release > "Run workflow". The
  installers are then available as the `installer` and `installer-mac` workflow artifacts (kept
  for a limited time); no Release is created.
- A pushed tag creates a **public** Release; delete the release and tag on GitHub to retract it.

## One-time setup (for PyPI)

1. **Push the repository to GitHub** (`zohoMatt/audio-notes`). The project URLs and the MIT
   license (`LICENSE`, `license` field in `pyproject.toml`) are already set; they are frozen into
   each published version's metadata, so check them before the first upload.
2. **Create the projects and Trusted Publishers** (no API tokens are stored anywhere):
   - PyPI: https://pypi.org/manage/account/publishing/ -> "Add a pending publisher"
     - PyPI project name: `audio-notes`
     - Owner / repository: your GitHub owner and repo name
     - Workflow name: `release.yml`
     - Environment name: `pypi`
   - A pending publisher creates the project on the first successful publish. If the name
     `audio-notes` is taken, rename the project in `pyproject.toml` (and the publisher entries) first.
3. **Create GitHub environments** (Repository Settings -> Environments):
   - `pypi`: enable **Required reviewers** and add yourself. The PyPI publish job then waits
     for your manual approval in the Actions UI.
4. (Optional) Settings -> Actions -> General: restrict allowed actions to the ones the workflows use.

## Each release

1. Make sure `main` is green in CI.
2. Tag and push (the version comes from the tag via hatch-vcs):
   ```powershell
   git tag v0.1.0
   git push origin v0.1.0
   ```
3. Watch the Actions run: `test` -> `build` + `build-macos-wheel` -> `publish-pypi` (**approve it**
   when it pauses). In parallel, `installer` builds `Audio-Notes-<version>-windows-x64-setup.exe` and creates
   the GitHub Release; then `installer-mac` adds `Audio-Notes-<version>-macos-arm64.dmg` to it.
4. Verify: `uv tool install audio-notes==0.1.0` in a clean shell (on Windows and on a Mac; on the
   Mac, `pip download --no-deps audio-notes==0.1.0` should pick the `macosx_14_0_arm64` wheel);
   run the installer and the DMG on clean machines.

## SmartScreen and antivirus

The MVP installer ships **unsigned**; no developer registration or certificate is needed yet.

- **Channels.** `pip` / `uv tool install audio-notes` is the recommended channel and is not subject
  to SmartScreen's download reputation check. The installer is an additional channel for people
  without Python. Say so in release notes if users report warnings.
- **Build hygiene.** The spec sets `upx=False` (no executable compression, which raises AV
  heuristics). Only build release installers on GitHub Actions, never upload a locally built one.
  The workflow prints the installer SHA256 into the Release notes so users can verify it.
- **After each release, submit the installer for false-positive review.**
  - Microsoft Defender: the Microsoft Security Intelligence submission portal
    (https://www.microsoft.com/en-us/wdsi/filesubmission). Choose "Software developer", upload the
    installer, say it is a legitimate unsigned open-source audio tool and name the detection if any.
    I am fairly (not fully) sure of this URL; search "Microsoft security intelligence submit a file"
    if it has moved.
  - Other vendors only if they actually flag it (check the file on https://www.virustotal.com first):
    use each vendor's own "report a false positive" page found from its website. I have not verified
    individual vendor URLs, so none are listed here.
  - SmartScreen reputation builds up with downloads over time; an unsigned file may keep warning for a while.
- **If false positives are frequent:** rebuild PyInstaller's bootloader from source (clone PyInstaller,
  build in `bootloader/` with a C compiler, then `pip install` from that checkout) so the stub
  differs from the widely-flagged prebuilt one. Follow the PyInstaller docs ("Building the Bootloader").
- **When to consider code signing:** once you distribute to non-technical users, or when Smart App
  Control blocking becomes a real support burden (it blocks unsigned apps with no override).
  Candidates: Microsoft Trusted Signing (check its region and applicant eligibility restrictions),
  a traditional OV code-signing certificate from a CA, or publishing via the Microsoft Store (MSIX).
  Check prices and current policies on the official pages; none are stated here.

## Local installer build

```powershell
pwsh installer/build.ps1                 # bundle in dist\audio-notes; installer too if Inno Setup is installed
python installer/smoke_test.py           # optional: --version + one MCP handshake against the bundle
```

Inno Setup: `winget install JRSoftware.InnoSetup`.

## Dropping the bundle smoke test

It is optional and isolated: delete `installer/smoke_test.py` and the `Smoke test` step in the
`installer` job of `release.yml`.

## macOS: wheel, app and DMG

**PyPI.** `build-macos-wheel` (macos-15, Apple Silicon) runs `uv build --wheel`; `hatch_build.py`
compiles `macos/capture` and puts the helper at `audio_notes/capture/bin/audio-notes-capture`, so
the wheel is tagged `py3-none-macosx_14_0_arm64`. `publish-pypi` uploads it together with the
sdist and the pure-Python wheel from `build`. pip / uv on a Mac pick the macOS wheel; Intel Macs
get the pure wheel and cannot record (not supported).

**App and DMG.** `installer/build_mac.sh` does everything, locally and in CI:

1. `swift build -c release --package-path macos/capture`
2. PyInstaller `installer/audio-notes-mac.spec` -> `dist/Audio Notes.app` with three executables in
   `Contents/MacOS`: `Audio Notes` (menu bar; with arguments it acts as the CLI), `audio-notes`
   (CLI, `mcp` for Claude) and `audio-notes-capture`. Dependency collection is shared with the
   Windows spec in `installer/spec_common.py`.
3. Signing, inside-out: every Mach-O in the bundle, then the three executables with
   `installer/entitlements.plist`, then the bundle.
4. `dmgbuild` with `installer/dmg_settings.py` -> `dist/Audio-Notes-<version>-macos-arm64.dmg` + `.sha256`.
5. With a Developer ID: sign the DMG, `notarytool submit --wait`, `stapler staple`.

```bash
installer/build_mac.sh               # needs uv and the Command Line Tools (Xcode not required)
installer/build_mac.sh --skip-dmg    # only the .app
python3 installer/smoke_test.py "dist/Audio Notes.app/Contents/MacOS/audio-notes"
```

If the checkout is under `~/Documents` with iCloud Drive "Desktop & Documents" on, build outside
it, otherwise codesign fails ("resource fork, Finder information, or similar detritus"):
`AUDIO_NOTES_BUILD_DIR=/tmp/an/build AUDIO_NOTES_DIST_DIR=/tmp/an/dist installer/build_mac.sh`.

The app icon is `installer/AudioNotes.icns`; regenerate it with
`uv run python installer/make_icon.py --icns` (macOS only, uses `iconutil`).

### Without a Developer ID (now)

`MACOS_SIGN_IDENTITY` is unset, so the app is **ad-hoc signed** (no Hardened Runtime, nothing
notarized). The `installer-mac` job still builds the DMG and adds it to the Release with a note
explaining how to open it (System Settings > Privacy & Security > Open Anyway, or
`xattr -dr com.apple.quarantine "/Applications/Audio Notes.app"`). The ad-hoc signature changes
with every build, so macOS asks for microphone / system audio permission again after an update.

### Turning on signing and notarization (later)

1. Join the Apple Developer Program, create a **Developer ID Application** certificate, export it
   with its private key as `.p12`.
2. App Store Connect > Users and Access > Integrations > App Store Connect API: create a key
  ; download the `.p8`, note its key id and issuer id.
3. Add repository secrets: `MACOS_CERTIFICATE_P12` (`base64 -i cert.p12`),
   `MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGN_IDENTITY` (e.g.
   `Developer ID Application: Your Name (TEAMID)`), `NOTARY_API_KEY_P8` (`base64 -i AuthKey_X.p8`),
   `NOTARY_KEY_ID`, `NOTARY_ISSUER`.
4. Push a pre-release tag. The job then signs with the Hardened Runtime and a timestamp, and
   notarizes and staples the DMG. If the notarized app crashes on start, add
   `com.apple.security.cs.allow-unsigned-executable-memory` to `installer/entitlements.plist`
   (see the comment there). Locally, the same works with `MACOS_SIGN_IDENTITY` and
   `NOTARY_KEY_PATH` / `NOTARY_KEY_ID` / `NOTARY_ISSUER` in the environment.
