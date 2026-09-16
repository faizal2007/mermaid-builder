; Inno Setup recipe for the Diagram Maker installer.
;
; scripts/build_installer.py compiles this for you, passing the version and the
; paths of the frozen application and the icon in through the defines below.
; To compile it by hand after a build:
;
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\diagram-maker.iss
;
; A per-user install into %LOCALAPPDATA%\Programs needs no administrator; the
; "install for all users" option on the first page elevates and switches to
; Program Files.  {autopf} and {autoprograms} follow whichever was chosen.

#define DefinesFile AddBackslash(SourcePath) + "..\build\windows\installer_defines.iss"
#if FileExists(DefinesFile)
  #include DefinesFile
#endif

; fallbacks, for when the script is compiled without a build in front of it
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\dist\Diagram Maker"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "icon.ico"
#endif

#define AppName "Diagram Maker"
#define AppPublisher "Faizal Sadri"
#define AppExeName "Diagram Maker.exe"
; must match APP_ID in src/diagram_maker/__init__.py, which sets the same ID on
; the running process; without a matching pair Windows drops the app icon from
; the taskbar button and falls back to the host executable's
#define AppUserModelId "FaizalSadri.DiagramMaker"

[Setup]
; the AppId identifies the application across versions - never change it, or
; upgrades will install side by side instead of replacing
AppId={{7C4E2A3B-1F6D-4E58-9B0A-2D7A5E6C4F21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; bundle everything the app needs is already in BundleDir, so no admin rights
; are required unless the user asks to install for all users
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
OutputDir={#OutDir}
OutputBaseFilename=DiagramMaker-{#AppVersion}-setup
SetupIconFile={#IconFile}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "association"; Description: "Open .diagram.json documents with {#AppName}"; GroupDescription: "File types:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Build diagrams visually and export them as mermaid"; AppUserModelID: "{#AppUserModelId}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; AppUserModelID: "{#AppUserModelId}"

[Registry]
; HKA is HKCU for a per-user install and HKLM when the user elevated
Root: HKA; Subkey: "Software\Classes\.diagram.json"; ValueType: string; ValueName: ""; ValueData: "DiagramMaker.Document"; Flags: uninsdeletevalue; Tasks: association
Root: HKA; Subkey: "Software\Classes\DiagramMaker.Document"; ValueType: string; ValueName: ""; ValueData: "{#AppName} document"; Flags: uninsdeletekey; Tasks: association
Root: HKA; Subkey: "Software\Classes\DiagramMaker.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Tasks: association
Root: HKA; Subkey: "Software\Classes\DiagramMaker.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: association

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
