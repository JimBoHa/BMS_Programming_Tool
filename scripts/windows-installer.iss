#ifndef Payload
  #error Payload directory is required
#endif
#ifndef Destination
  #error Destination directory is required
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif

[Setup]
AppId={{F9E98FC4-C85D-40DD-BFC3-3B065895A7CD}
AppName=BMS Studio
AppVersion={#AppVersion}
AppPublisher=BMS Studio contributors
DefaultDirName={localappdata}\Programs\BMS Studio
DefaultGroupName=BMS Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Destination}
OutputBaseFilename=BMS-Studio-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\BMS Studio.exe

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BMS Studio"; Filename: "{app}\BMS Studio.exe"
Name: "{group}\Uninstall BMS Studio"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\BMS Studio.exe"; Description: "Open BMS Studio"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  Existing: String;
  ExitCode: Integer;
begin
  Result := True;
  Existing := ExpandConstant('{localappdata}\Programs\BMS Studio\BMS Studio.exe');
  if FileExists(Existing) then begin
    if not Exec(Existing, '--check-not-running', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := False
    else
      Result := ExitCode = 0;
    if not Result then
      MsgBox('Quit BMS Studio before installing an update. Your data will be preserved.', mbInformation, MB_OK);
  end;
end;

function InitializeUninstall(): Boolean;
var
  ExitCode: Integer;
begin
  Result := Exec(ExpandConstant('{app}\BMS Studio.exe'), '--check-not-running', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
  if not Result then
    MsgBox('Quit BMS Studio before uninstalling. Your data will be preserved.', mbInformation, MB_OK);
end;

// No user-data path is listed in UninstallDelete. Upgrades and uninstall leave
// controller captures, recovery journals, projects and logs in LOCALAPPDATA.
