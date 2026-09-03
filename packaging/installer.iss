; Render Monitor Queue Inno Setup installer
; Build after PyInstaller: dist\RenderMonitorQueue\RenderMonitorQueue.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.2.0"
#endif

#define MyAppName "Render Monitor Queue"
#define MyAppExeName "RenderMonitorQueue.exe"
#define MyAppPublisher "Render Monitor Queue"
#define MyAppURL "https://github.com/HarrisWilde/render-monitor-app"

[Setup]
AppId={{6F7A5D6A-4C2A-4D1E-9E5B-0B6F2E1A1B2C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=RenderMonitorQueue-Setup-{#MyAppVersion}
SetupIconFile=..\icon\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\RenderMonitorQueue\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
