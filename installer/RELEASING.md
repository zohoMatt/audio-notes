# Releasing

Everything the workflows can do on their own is in `.github/workflows/`. These are the steps only
the repository owner can do. The workflows have **not** been run on GitHub yet; expect to fix small
things on the first tag (try a `v0.0.1rc1`-style tag first; TestPyPI/PyPI versions can never be reused).

## One-time setup

1. **Push the repository to GitHub** and replace the `OWNER` placeholders in `pyproject.toml`
   (`[project.urls]`). Decide on a LICENSE and add the `license` field to `pyproject.toml`.
2. **Create the projects and Trusted Publishers** (no API tokens are stored anywhere):
   - PyPI: https://pypi.org/manage/account/publishing/ -> "Add a pending publisher"
     - PyPI project name: `audio-notes`
     - Owner / repository: your GitHub owner and repo name
     - Workflow name: `release.yml`
     - Environment name: `pypi`
   - TestPyPI: https://test.pypi.org/manage/account/publishing/, the same, with environment name `testpypi`.
   - A pending publisher creates the project on the first successful publish. If the name
     `audio-notes` is taken, rename the project in `pyproject.toml` (and the publisher entries) first.
3. **Create GitHub environments** (Repository Settings -> Environments):
   - `testpypi`: no protection needed.
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
3. Watch the Actions run: `test` -> `build` -> `publish-testpypi` -> `publish-pypi` (**approve it**
   when it pauses). In parallel, `installer` builds `audio-notes-setup-<version>.exe` and attaches
   it to a GitHub Release.
4. Verify: `uv tool install audio-notes==0.1.0` in a clean shell; run the installer on a clean machine.

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
