#ifndef AppVersion
  #define AppVersion "0.2.2"
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
SetupIconFile=markauto.ico
UninstallDisplayIcon={code:PayloadDir}\_internal\packaging\markauto.ico
CloseApplications=no
AppMutex=Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420
RestartApplications=no
LicenseFile=..\LICENSE
[Languages]
Name: "chinesetraditional"; MessagesFile: "languages\ChineseTraditional.isl"
[Files]
Source: "..\dist\MarkAuto\*"; DestDir: "{code:PayloadDir}"; Flags: ignoreversion recursesubdirs createallsubdirs; BeforeInstall: CheckDestination
; The final file verifies the entire payload before Inno processes any shortcuts.
Source: "..\dist\payload-inventory.txt"; DestDir: "{code:PayloadDir}"; Flags: ignoreversion; BeforeInstall: CheckDestination; AfterInstall: VerifyPayload
[Icons]
Name: "{userprograms}\Mark Auto\Mark Auto"; Filename: "{code:PayloadDir}\MarkAuto.exe"; WorkingDir: "{code:PayloadDir}"; BeforeInstall: RequireVerifiedActivation
Name: "{userdesktop}\Mark Auto"; Filename: "{code:PayloadDir}\MarkAuto.exe"; WorkingDir: "{code:PayloadDir}"; BeforeInstall: RequireVerifiedActivation
Name: "{userprograms}\Mark Auto\Mark Auto 多市場平台"; Filename: "{code:PayloadDir}\MarkAuto.exe"; Parameters: "--platform-v2"; WorkingDir: "{code:PayloadDir}"; BeforeInstall: RequireVerifiedActivation
[Run]
Filename: "{code:PayloadDir}\MarkAuto.exe"; Description: "啟動 Mark Auto"; Flags: nowait postinstall skipifsilent unchecked
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
    RaiseException('僅支援一般本機磁碟機路徑。');
  repeat
    Attr := FileAttributes(Path);
    if Attr = MARKAUTO_INVALID_ATTRIBUTES then begin
      Error := LastError();
      if (Error <> 2) and (Error <> 3) then
        RaiseException('無法安全檢查安裝路徑。');
    end else if (Attr and MARKAUTO_REPARSE_ATTRIBUTE) <> 0 then
      RaiseException('安裝路徑不支援重新解析點。');
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
      RaiseException('安裝前請先自行關閉 Mark Auto。');
    if CompareText(ExpandConstant('{app}'), ExpandConstant('{localappdata}\Programs\MarkAuto')) <> 0 then
      RaiseException('請使用 Mark Auto 預設的個別使用者安裝資料夾。');
    Parent := ExpandConstant('{app}\payloads\{#AppVersion}');
    AssertSafePath(Parent);
    if not ForceDirectories(Parent) then RaiseException('無法建立程式檔案的上層資料夾。');
    AttemptDir := GenerateUniqueName(Parent, '');
    if (FileAttributes(AttemptDir) <> MARKAUTO_INVALID_ATTRIBUTES) or not CreateDir(AttemptDir) then
      RaiseException('無法保留新的程式檔案資料夾。');
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
            RaiseException('程式檔案中含有重新解析點。');
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
    RaiseException('程式檔案清單完整性檢查失敗。');
  if not LoadStringsFromFile(Name, Rows) then RaiseException('無法讀取程式檔案清單。');
  for I := 0 to GetArrayLength(Rows) - 1 do begin
    Relative := Copy(Rows[I], 67, MaxInt);
    if (Length(Rows[I]) < 67) or (Pos('..', Relative) <> 0) or
       (Pos(':', Relative) <> 0) or (Copy(Relative, 1, 1) = '\') then
      RaiseException('程式檔案清單中的路徑無效。');
    Name := AttemptDir + '\' + Relative;
    AssertSafePath(Name);
    if CompareText(GetSHA256OfFile(Name), Copy(Rows[I], 1, 64)) <> 0 then
      RaiseException('程式檔案完整性檢查失敗：' + Relative);
  end;
  if CountPayloadFiles(AttemptDir) <> GetArrayLength(Rows) + 1 then
    RaiseException('新的程式資料夾中有非預期的檔案；已拒絕啟用。');
  PayloadVerified := True;
  Log('MARKAUTO_PAYLOAD_VERIFIED=' + AttemptDir);
end;

procedure RequireVerifiedActivation();
begin
  if not PayloadVerified then RaiseException('程式檔案不完整，無法啟用。');
  AssertSafePath(AttemptDir);
end;

function RejectRunningApplication(): Boolean;
begin
  Result := not CheckForMutexes('Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420');
  if not Result then begin
    Log('Mark Auto is running; installation/uninstallation refused without closing it.');
    SuppressibleMsgBox('安裝或解除安裝前請先自行關閉 Mark Auto。正在執行的工作不會自動停止。', mbError, MB_OK, IDOK);
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
    SuppressibleMsgBox('安裝路徑不安全或無法存取；已拒絕解除安裝。使用者資料未被移除。', mbError, MB_OK, IDOK);
  end;
end;
