; The Windows installer.
;
; The main executable is self-contained so moving it cannot separate it from a
; Python runtime. The installer is still the supported human download: it puts
; the executable, updater and install manifest in one known directory so
; automatic updates can safely replace that directory.
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
#ifdef TryOut
; Installed and removed again by the build, to see that it works. Under another
; identity, so that doing so on a computer with the real one installed does not
; take over its shortcuts and its entry in Installed apps, and then remove them.
AppId={{1E6B0D4C-52F7-4B0A-9C55-3A7F0E91D2B8}
#else
; Stable, so an upgrade replaces the previous install instead of sitting
; beside it. Never change this.
AppId={{7C4F6A62-9C1B-4E2E-9E3B-8F5A2D6C1E44}
#endif
AppName=PiTrac Easy-Connect
AppVersion={#AppVersion}
AppPublisher=Tyler Pardun
AppSupportURL=https://github.com/TylerPardun/pitrac-easy-connect
DefaultDirName={localappdata}\Programs\PiTrac Easy-Connect
; The updater validates that the install root is a directory named for the
; application, so the last component of the path above is not cosmetic.
DisableDirPage=yes
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

#ifndef TryOut
[Icons]
Name: "{autoprograms}\PiTrac Easy-Connect"; Filename: "{app}\PiTrac Easy-Connect.exe"
Name: "{autodesktop}\PiTrac Easy-Connect"; Filename: "{app}\PiTrac Easy-Connect.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

#endif

[Run]
Filename: "{app}\PiTrac Easy-Connect.exe"; Description: "Open PiTrac Easy-Connect"; Flags: nowait postinstall skipifsilent
