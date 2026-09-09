; 공문 정리함 설치 프로그램
; 관리자 권한 없이 사용자 폴더에 설치한다. 학교 컴퓨터에서 권한 없이도 깔린다.
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

#define AppName "공문 정리함"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
; exe 파일명은 영문이어야 한다. GitHub 릴리스가 한글 첨부 파일명을
; 바꿔 버려 자동 업데이트가 깨지기 때문(build.spec 주석 참고).
#define AppExe "gongmun.exe"
#define OldAppExe "공문정리함.exe"

[Setup]
AppId={{7C3F1E2A-9B41-4D6E-8A25-5F0C7D9E1B33}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\공문정리함
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=gongmun-setup
SetupIconFile=icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 아이콘 만들기"; GroupDescription: "추가 설정:"

; 예전 한글 이름 exe 와 업데이트 찌꺼기를 지운다. 바로가기는 [Icons]가
; 어차피 새 exe 를 가리키도록 다시 만든다.
[InstallDelete]
Type: files; Name: "{app}\{#OldAppExe}"
Type: files; Name: "{app}\{#OldAppExe}.old"
Type: files; Name: "{app}\{#AppExe}.old"
; "컴퓨터를 켤 때 자동으로 띄우기" 는 없앴다. 시작프로그램은 사람마다
; 사정이 다른데(느린 컴퓨터, 공용 컴퓨터) 설치할 때 무심코 체크했다가
; 나중에 끄는 길을 못 찾는 일이 있었다. 켜고 싶으면 사용설명서 11절대로
; 바로가기를 직접 넣으면 된다 — 그쪽이 끄기도 쉽다.
; 예전 판이 만들어 둔 바로가기는 여기서 치운다.
Type: files; Name: "{userstartup}\{#AppName}.lnk"
Type: files; Name: "{userstartup}\공문정리함.lnk"
Type: files; Name: "{userstartup}\공문정리함.bat"

[Files]
Source: "dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "사용설명서.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme
; 라이선스 고지는 설치 폴더에서 바로 보이게 둔다. exe 안에도 들어 있지만
; 그것만으로는 이용자가 열어 볼 수 없다.
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\Pretendard-OFL.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} 지우기"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행하기"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userstartup}\{#AppName}.lnk"
; 1.7.1 이하에는 프로그램 안에 "컴퓨터 켤 때 자동 실행" 토글이 있었고, 그때
; 만든 바로가기는 이름에 띄어쓰기가 없다. 그 토글은 1.7.2 에서 없앴지만 이미
; 만들어진 바로가기는 남아 있으므로 지울 때 함께 치운다.
Type: files; Name: "{userstartup}\공문정리함.lnk"
Type: files; Name: "{userstartup}\공문정리함.bat"

[Code]
procedure CurUninstallStepChanged(CurStep: TUninstallStep);
var
  DataDir: String;
begin
  { 설정과 처리 기록은 .gongmun 폴더에 있다(app.py 의 HOME_DIR). 프로그램만
    지우고 기록은 남기고 싶은 분이 많으므로, 지울지 물어보고 기본은 "아니오".
    조용히 지우는 중(/SILENT)이면 묻지 않고 그대로 둔다. }
  if CurStep = usPostUninstall then
  begin
    if UninstallSilent then
      Exit;
    DataDir := ExpandConstant('{%USERPROFILE%}\.gongmun');
    if DirExists(DataDir) then
      if MsgBox('공문 정리함이 저장한 설정과 처리 기록도 지울까요?' + #13#10 + #13#10 +
                '지우면 폴더 위치, 그동안의 처리 상태와 메모가 사라집니다.' + #13#10 +
                '프로그램만 지우려면 "아니오" 를 누르세요.' + #13#10 + #13#10 +
                DataDir,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
