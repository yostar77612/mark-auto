#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#include "..\dist\payload-inventory.iss"
[Setup]
AppId={{58788303-95B7-491B-A67A-B1EBA50DA420}
AppName=Mark Auto
AppVersion={#AppVersion}
AppPublisher=Mark Auto contributors
DefaultDirName={localappdata}\Programs\MarkAuto
DefaultGroupName=Mark Auto
DisableDirPage=yes
UsePreviousAppDir=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\dist\installers
OutputBaseFilename=MarkAuto-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={code:PayloadDir}\MarkAuto.exe
CloseApplications=no
AppMutex=Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420
RestartApplications=no
LicenseFile=..\LICENSE
[Files]
Source: "..\dist\MarkAuto\*"; DestDir: "{code:PayloadDir}"; Flags: ignoreversion recursesubdirs createallsubdirs; BeforeInstall: CheckDestination
; The final file verifies the entire payload before Inno processes any shortcuts.
Source: "..\dist\payload-inventory.txt"; DestDir: "{code:PayloadDir}"; Flags: ignoreversion; BeforeInstall: CheckDestination; AfterInstall: VerifyPayload
[Icons]
Name: "{userprograms}\Mark Auto\Mark Auto"; Filename: "{code:PayloadDir}\MarkAuto.exe"; WorkingDir: "{code:PayloadDir}"; BeforeInstall: RequireVerifiedActivation
Name: "{userdesktop}\Mark Auto"; Filename: "{code:PayloadDir}\MarkAuto.exe"; WorkingDir: "{code:PayloadDir}"; BeforeInstall: RequireVerifiedActivation
[Run]
Filename: "{code:PayloadDir}\MarkAuto.exe"; Description: "Launch Mark Auto"; Flags: nowait postinstall skipifsilent unchecked
; Deliberately no [UninstallDelete]: %LOCALAPPDATA%\MarkAuto is never removed.

[Code]
const
  MARKAUTO_REPARSE_ATTRIBUTE = $400; { FILE_ATTRIBUTE_REPARSE_POINT }
  MARKAUTO_INVALID_ATTRIBUTES = $FFFFFFFF;
var
  AttemptDir: String;
  PayloadVerified: Boolean;

function FileAttributes(Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function LastError(): Cardinal;
  external 'GetLastError@kernel32.dll stdcall';

procedure AssertSafePath(Path: String);
var
  Parent: String;
  Attr, Error: Cardinal;
begin
  if (Length(Path) < 3) or (Copy(Path, 2, 2) <> ':\') then
    RaiseException('Only an ordinary local drive path is supported.');
  repeat
    Attr := FileAttributes(Path);
    if Attr = MARKAUTO_INVALID_ATTRIBUTES then begin
      Error := LastError();
      if (Error <> 2) and (Error <> 3) then
        RaiseException('Cannot inspect installation path safely.');
    end else if (Attr and MARKAUTO_REPARSE_ATTRIBUTE) <> 0 then
      RaiseException('Reparse points are not supported in installation paths.');
    Parent := ExtractFileDir(Path);
    if Parent = Path then Break;
    Path := Parent;
  until Length(Path) < 3;
end;

procedure CheckDestination();
begin
  AssertSafePath(ExpandConstant(CurrentFilename));
end;

function PayloadDir(Param: String): String;
begin
  Result := AttemptDir;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Parent: String;
begin
  Result := '';
  try
    if CheckForMutexes('Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420') then
      RaiseException('Close Mark Auto yourself before installing.');
    if CompareText(ExpandConstant('{app}'), ExpandConstant('{localappdata}\Programs\MarkAuto')) <> 0 then
      RaiseException('Use the default per-user Mark Auto installation folder.');
    Parent := ExpandConstant('{app}\payloads\{#AppVersion}');
    AssertSafePath(Parent);
    if not ForceDirectories(Parent) then RaiseException('Cannot create payload parent.');
    AttemptDir := GenerateUniqueName(Parent, '');
    if (FileAttributes(AttemptDir) <> MARKAUTO_INVALID_ATTRIBUTES) or not CreateDir(AttemptDir) then
      RaiseException('Cannot reserve a fresh payload directory.');
    AssertSafePath(AttemptDir);
    Log('MARKAUTO_FRESH_PAYLOAD=' + AttemptDir);
  except
    Result := GetExceptionMessage;
  end;
end;

function CountPayloadFiles(Path: String): Integer;
var
  Item: TFindRec;
  Name: String;
begin
  Result := 0;
  AssertSafePath(Path);
  if FindFirst(Path + '\*', Item) then begin
    try
      repeat
        if (Item.Name <> '.') and (Item.Name <> '..') then begin
          Name := Path + '\' + Item.Name;
          if (Item.Attributes and MARKAUTO_REPARSE_ATTRIBUTE) <> 0 then
            RaiseException('Reparse point inside payload.');
          if (Item.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            Result := Result + CountPayloadFiles(Name)
          else
            Result := Result + 1;
        end;
      until not FindNext(Item);
    finally
      FindClose(Item);
    end;
  end;
end;

procedure VerifyPayload();
var
  Rows: TArrayOfString;
  I: Integer;
  Relative, Name: String;
begin
  AssertSafePath(AttemptDir);
  Name := AttemptDir + '\payload-inventory.txt';
  if CompareText(GetSHA256OfFile(Name), '{#PayloadInventorySHA256}') <> 0 then
    RaiseException('Payload inventory integrity check failed.');
  if not LoadStringsFromFile(Name, Rows) then RaiseException('Cannot read payload inventory.');
  for I := 0 to GetArrayLength(Rows) - 1 do begin
    Relative := Copy(Rows[I], 67, MaxInt);
    if (Length(Rows[I]) < 67) or (Pos('..', Relative) <> 0) or
       (Pos(':', Relative) <> 0) or (Copy(Relative, 1, 1) = '\') then
      RaiseException('Invalid payload inventory path.');
    Name := AttemptDir + '\' + Relative;
    AssertSafePath(Name);
    if CompareText(GetSHA256OfFile(Name), Copy(Rows[I], 1, 64)) <> 0 then
      RaiseException('Payload file integrity check failed: ' + Relative);
  end;
  if CountPayloadFiles(AttemptDir) <> GetArrayLength(Rows) + 1 then
    RaiseException('Unexpected file in fresh payload; activation refused.');
  PayloadVerified := True;
  Log('MARKAUTO_PAYLOAD_VERIFIED=' + AttemptDir);
end;

procedure RequireVerifiedActivation();
begin
  if not PayloadVerified then RaiseException('Incomplete payload cannot be activated.');
  AssertSafePath(AttemptDir);
end;

function RejectRunningApplication(): Boolean;
begin
  Result := not CheckForMutexes('Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420');
  if not Result then begin
    Log('Mark Auto is running; installation/uninstallation refused without closing it.');
    SuppressibleMsgBox('Close Mark Auto yourself before installing or uninstalling. No running work will be stopped automatically.', mbError, MB_OK, IDOK);
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := RejectRunningApplication();
end;

function InitializeUninstall(): Boolean;
var
  FileCount: Integer;
begin
  Result := False;
  try
    AssertSafePath(ExpandConstant('{app}'));
    FileCount := CountPayloadFiles(ExpandConstant('{app}'));
    Result := RejectRunningApplication();
  except
    Log('Uninstall refused: ' + GetExceptionMessage);
    SuppressibleMsgBox('Installation path is unsafe or inaccessible; uninstall refused. User data was not removed.', mbError, MB_OK, IDOK);
  end;
end;
