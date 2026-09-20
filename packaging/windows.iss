#ifndef AppVersion
  #error AppVersion must be supplied with /DAppVersion
#endif

[Setup]
AppId={{83438EC8-C8E5-4182-AC3A-420EF6EE497A}
AppName=Scientific Graph Studio
AppVersion={#AppVersion}
AppPublisher=Scientific Graph Studio
AppPublisherURL=https://github.com/acanalkoc/grafiktasarim
DefaultDirName={localappdata}\Programs\ScientificGraphStudio
DefaultGroupName=Scientific Graph Studio
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=ScientificGraphStudio-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ScientificGraphStudio.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "..\dist\ScientificGraphStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Scientific Graph Studio"; Filename: "{app}\ScientificGraphStudio.exe"
Name: "{autodesktop}\Scientific Graph Studio"; Filename: "{app}\ScientificGraphStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ScientificGraphStudio.exe"; Description: "Scientific Graph Studio"; Flags: nowait postinstall skipifsilent
