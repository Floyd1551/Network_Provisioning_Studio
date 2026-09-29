#ifndef AppVersion
  #define AppVersion "1.0.0rc1"
#endif
#define AppName "Network Provisioning Studio"
#define AppExe "NetworkProvisioningStudio.exe"

[Setup]
AppId={{C8EBB684-93E1-4972-9F82-E76EA6881F36}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Floyd1551
AppPublisherURL=https://github.com/Floyd1551/Network_Provisioning_Studio
DefaultDirName={localappdata}\Programs\NetworkProvisioningStudio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=NetworkProvisioningStudio-{#AppVersion}-Setup-x64
SetupIconFile=..\src\switch_configurator\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
InfoBeforeFile=install-notes.txt

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\NetworkProvisioningStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; AppUserModelID: "Floyd1551.NetworkProvisioningStudio"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "Floyd1551.NetworkProvisioningStudio"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
