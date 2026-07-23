; BolFlow Windows installer (Inno Setup 6)
; Build:  ISCC.exe installer.iss   (after: pyinstaller bolflow.spec)
; Output: installer-out\BolFlow-Setup.exe (version-less name on purpose:
; the website's download button uses the stable releases/latest/download
; URL, which only works if every release uploads the same filename)

[Setup]
AppId={{7B1F0B6E-9C2A-4D5B-B7E1-B0LF10W00001}
AppName=BolFlow
AppVersion=1.0
AppPublisher=devkrishna23
AppPublisherURL=https://github.com/devkrishna23/BolFlow
DefaultDirName={autopf}\BolFlow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer-out
OutputBaseFilename=BolFlow-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\BolFlow.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"
Name: "startup"; Description: "Start BolFlow when Windows starts"

[Files]
Source: "dist\BolFlow\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{autoprograms}\BolFlow"; Filename: "{app}\BolFlow.exe"
Name: "{autoprograms}\BolFlow Settings"; Filename: "{app}\BolFlow-Settings.exe"
Name: "{autodesktop}\BolFlow"; Filename: "{app}\BolFlow.exe"; Tasks: desktopicon
Name: "{userstartup}\BolFlow"; Filename: "{app}\BolFlow.exe"; Tasks: startup

[Run]
Filename: "{app}\BolFlow.exe"; Description: "Launch BolFlow now"; \
  Flags: nowait postinstall skipifsilent
