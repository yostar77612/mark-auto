#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif
[Setup]
AppId={{58788303-95B7-491B-A67A-B1EBA50DA420}
AppName=Mark Auto
AppVersion={#AppVersion}
AppPublisher=Mark Auto contributors
DefaultDirName={localappdata}\Programs\MarkAuto
DefaultGroupName=Mark Auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\dist\installers
OutputBaseFilename=MarkAuto-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MarkAuto.exe
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
[Files]
Source: "..\dist\MarkAuto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\Mark Auto\Mark Auto"; Filename: "{app}\MarkAuto.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Mark Auto"; Filename: "{app}\MarkAuto.exe"; WorkingDir: "{app}"
[Run]
Filename: "{app}\MarkAuto.exe"; Description: "Launch Mark Auto"; Flags: nowait postinstall skipifsilent
; Deliberately no [UninstallDelete]: %LOCALAPPDATA%\MarkAuto is never removed.
