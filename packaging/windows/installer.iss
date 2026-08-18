; Inno Setup script for the Privacy Firewall desktop app.
;
; Expects the PyInstaller onedir bundle to already exist at dist\PrivacyFirewall\.
; Build from the repository root:
;
;   pyinstaller --clean --noconfirm packaging\privacy_firewall.spec
;   iscc /DAppVersion=0.1.0 packaging\windows\installer.iss
;
; Output lands in dist\installer\PrivacyFirewall-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define AppName "Privacy Firewall"
#define AppPublisher "Privacy Firewall"
#define AppURL "https://github.com/SurajSongara/privacy-firewall-starter-kit"
#define AppExeName "PrivacyFirewall.exe"

[Setup]
; Stable AppId so upgrades replace the previous install instead of stacking.
AppId={{7F3C1B84-5D2A-4E96-9C41-0B8E2A6D5F17}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\PrivacyFirewall
DefaultGroupName={#AppName}
; "lowest" lets a user without local admin rights install into their own
; profile -- the common case for practitioners on managed office machines.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=PrivacyFirewall-Setup-{#AppVersion}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
; AGPL: the binary bundles AGPL-licensed PyMuPDF, so the licence is shown at
; install time and installed alongside the app together with the source offer.
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\..\dist\PrivacyFirewall\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\packaging\SOURCE_OFFER.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
