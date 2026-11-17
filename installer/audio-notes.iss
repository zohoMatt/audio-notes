; Inno Setup script. Compile with:  iscc /DAppVersion=1.2.3 installer\audio-notes.iss
; Expects the PyInstaller onedir output in dist\audio-notes\ (see installer\build.ps1).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0F7A52-3B1D-4C55-9A4E-0A0D10A07E51}
AppName=Audio Notes
AppVersion={#AppVersion}
AppPublisher=audio-notes
DefaultDirName={autopf}\Audio Notes
DefaultGroupName=Audio Notes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=audio-notes-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Audio Notes
UninstallDisplayIcon={app}\audio-notes-tray.exe
SetupIconFile=audio-notes.ico
ChangesEnvironment=yes

[Tasks]
; No "start when I sign in" option on purpose: Audio Notes only runs when the user starts it.
Name: "addtopath"; Description: "Add the audio-notes command to PATH"; Flags: unchecked
Name: "connectclaude"; Description: "Connect to Claude Desktop (adds the audio-notes MCP server to its config)"

[Dirs]
; Transcripts live in {app}\data (see audio_notes/paths.py). Make it writable for normal users
; even when an admin install put the program under Program Files. The uninstaller leaves it
; alone while it still contains transcripts.
Name: "{app}\data"; Permissions: users-modify

[Files]
Source: "..\dist\audio-notes\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs; Excludes: "data\*"

[Icons]
Name: "{group}\Audio Notes"; Filename: "{app}\audio-notes-tray.exe"; IconFilename: "{app}\audio-notes-tray.exe"
Name: "{group}\Uninstall Audio Notes"; Filename: "{uninstallexe}"

[Registry]
; PATH is edited per-user (HKCU); admin installs still only touch the installing user's PATH.
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}')); Tasks: addtopath

[Run]
Filename: "{app}\audio-notes-tray.exe"; Description: "Launch Audio Notes"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM audio-notes-tray.exe"; Flags: runhidden; RunOnceId: "KillTray"

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure RemoveFromPath();
var
  OrigPath, App: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', OrigPath) then exit;
  App := ExpandConstant('{app}');
  P := Pos(';' + Uppercase(App), Uppercase(OrigPath));
  if P > 0 then
  begin
    Delete(OrigPath, P, Length(App) + 1);
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', OrigPath);
  end;
end;

// Register the MCP server with Claude Desktop as the user who started the installer (an elevated
// install must not write into another account's %APPDATA%). Runs for silent installs too; opt out
// with /TASKS="!connectclaude". The exit code is ignored on purpose: exit 3 means Claude Desktop is
// not installed, and any failure here must never fail the install (the tray menu can retry later).
// Earlier builds offered a sign-in autostart entry; drop it on upgrade and uninstall.
procedure RemoveLegacyAutostart();
begin
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AudioNotes');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then RemoveLegacyAutostart();
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('connectclaude') then
    ExecAsOriginalUser(ExpandConstant('{app}\audio-notes.exe'), 'setup claude --write --yes', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveFromPath();
    RemoveLegacyAutostart();
  end;
end;
