; NSIS installer. Run from the packaging/ directory:
;   makensis -DVERSION=153.7.0 -DSTAGE=dist\stage\windows [-DDIRECT=1] installer.nsi
!include "MUI2.nsh"
Name "IUK Browser"
OutFile "..\dist\iuk-browser-${VERSION}-setup.exe"
InstallDir "$PROGRAMFILES64\IUK Browser"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define MUI_ICON "..\branding\generated\iuk-browser.ico"
!define MUI_UNICON "..\branding\generated\iuk-browser.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "..\branding\generated\installer-header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "..\branding\generated\installer-side.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "..\branding\generated\installer-side.bmp"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "..\${STAGE}\*.*"
  File "..\branding\generated\iuk-browser.ico"
  File "..\branding\generated\private.ico"
  File "..\branding\generated\newtab.ico"
  File "..\branding\generated\newwindow.ico"
  File "..\branding\generated\document.ico"
!ifdef DIRECT
  ; source build: firefox.exe already carries the IUK icon and uses its own per-install profile
  CreateShortCut "$SMPROGRAMS\IUK Browser.lnk" "$INSTDIR\firefox.exe" "" "$INSTDIR\iuk-browser.ico" 0
  CreateShortCut "$DESKTOP\IUK Browser.lnk" "$INSTDIR\firefox.exe" "" "$INSTDIR\iuk-browser.ico" 0
  CreateShortCut "$SMPROGRAMS\IUK Browser (Private).lnk" "$INSTDIR\firefox.exe" "-private-window" "$INSTDIR\private.ico" 0
!else
  ; bundle on official Firefox binaries: own profile, %APPDATA% expanded by cmd at launch, minimized so no console shows
  CreateShortCut "$SMPROGRAMS\IUK Browser.lnk" "$SYSDIR\cmd.exe" '/c start "" "$INSTDIR\firefox.exe" -no-remote -profile "%APPDATA%\IUK Browser\profile"' "$INSTDIR\iuk-browser.ico" 0 SW_SHOWMINNOACTIVE
  CreateShortCut "$DESKTOP\IUK Browser.lnk" "$SYSDIR\cmd.exe" '/c start "" "$INSTDIR\firefox.exe" -no-remote -profile "%APPDATA%\IUK Browser\profile"' "$INSTDIR\iuk-browser.ico" 0 SW_SHOWMINNOACTIVE
  CreateShortCut "$SMPROGRAMS\IUK Browser (Private).lnk" "$SYSDIR\cmd.exe" '/c start "" "$INSTDIR\firefox.exe" -no-remote -profile "%APPDATA%\IUK Browser\profile" -private-window' "$INSTDIR\private.ico" 0 SW_SHOWMINNOACTIVE
!endif
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "DisplayName" "IUK Browser"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "DisplayIcon" "$INSTDIR\iuk-browser.ico"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "UninstallString" '"$INSTDIR\Uninstall.exe"'
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\IUK Browser.lnk"
  Delete "$SMPROGRAMS\IUK Browser (Private).lnk"
  Delete "$DESKTOP\IUK Browser.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser"
SectionEnd
