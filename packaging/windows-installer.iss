; The Windows installer.
;
; Why there is one at all: the application is a directory -- an executable
; beside the runtime it needs -- because that is the shape the updater can
; replace in place. A zip invites someone to drag the executable out of that
; directory, which used to work when it was a single self-contained file. Now
; it fails with "Failed to load Python DLL", which is true and useless.
;
; An installer removes the choice. There is nothing loose to move, the
; application lands in one known directory, and updating replaces that
; directory exactly as it does on macOS.
;
; Per-user, deliberately: {localappdata}\Programs needs no administrator, so
; there is no elevation prompt on install, and -- the part that matters -- the
; running application can replace its own directory later without one either.
; A machine-wide install into Program Files would need elevation for every
; update, which is precisely the friction this exists to remove.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\payload\PiTrac Easy-Connect"
#endif

[Setup]
; Stable, so an upgrade replaces the previous install instead of sitting
; beside it. Never change this.
AppId={{7C4F6A62-9C1B-4E2E-9E3B-8F5A2D6C1E44}
AppName=PiTrac Easy-Connect
AppVersion={#AppVersion}
AppPublisher=Tyler Pardun
AppSupportURL=https://github.com/TylerPardun/pitrac-easy-connect
DefaultDirName={localappdata}\Programs\PiTrac Easy-Connect
; The updater validates that the install root is a directory named for the
; application, so the last component of the path above is not cosmetic.
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=PiTrac-Easy-Connect-windows-setup
OutputDir=..\dist
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=PiTrac Easy-Connect
UninstallDisplayIcon={app}\PiTrac Easy-Connect.exe
LicenseFile=..\LICENSE

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PiTrac Easy-Connect"; Filename: "{app}\PiTrac Easy-Connect.exe"
Name: "{autodesktop}\PiTrac Easy-Connect"; Filename: "{app}\PiTrac Easy-Connect.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\PiTrac Easy-Connect.exe"; Description: "Open PiTrac Easy-Connect"; Flags: nowait postinstall skipifsilent
