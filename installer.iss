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
Name: "startupicon"; Description: "컴퓨터를 켤 때 자동으로 띄우기"; GroupDescription: "추가 설정:"

; 예전 한글 이름 exe 와 업데이트 찌꺼기를 지운다. 바로가기는 [Icons]가
; 어차피 새 exe 를 가리키도록 다시 만든다.
[InstallDelete]
Type: files; Name: "{app}\{#OldAppExe}"
Type: files; Name: "{app}\{#OldAppExe}.old"
Type: files; Name: "{app}\{#AppExe}.old"

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
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행하기"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userstartup}\{#AppName}.lnk"
