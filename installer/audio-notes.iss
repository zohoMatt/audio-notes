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
ChangesEnvironment=yes

[Tasks]
Name: "autostart"; Description: "Start Audio Notes when I sign in to Windows"; Flags: unchecked
Name: "addtopath"; Description: "Add the audio-notes command to PATH"; Flags: unchecked

[Dirs]
; Transcripts live in {app}\data (see audio_notes/paths.py). Make it writable for normal users
; even when an admin install put the program under Program Files. The uninstaller leaves it
; alone while it still contains transcripts.
Name: "{app}\data"; Permissions: users-modify

[Files]
Source: "..\dist\audio-notes\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs; Excludes: "data\*"

[Icons]
Name: "{group}\Audio Notes"; Filename: "{app}\audio-notes-tray.exe"
Name: "{group}\Uninstall Audio Notes"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AudioNotes"; ValueData: """{app}\audio-notes-tray.exe"""; Flags: uninsdeletevalue; Tasks: autostart
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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then RemoveFromPath();
end;
