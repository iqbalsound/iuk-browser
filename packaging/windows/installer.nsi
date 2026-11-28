; IUK Browser per-user installer (no administrator rights needed, so silent auto-updates never show a UAC prompt).
;   makensis -DVERSION=2.1.0 -DSRC=..\..\dist\iuk-browser -DOUT=..\..\dist\iuk-browser-2.1.0-setup.exe packaging\windows\installer.nsi
; Silent: setup.exe /S        Update (used by the in-app updater): setup.exe /S /UPDATE
!include "MUI2.nsh"
!include "FileFunc.nsh"
Unicode true
Name "IUK Browser"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\IUK Browser"
InstallDirRegKey HKCU "Software\IUK Browser" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "IUK Browser"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "IUK Browser installer"
VIAddVersionKey "LegalCopyright" "MIT License"

!define MUI_ICON "..\..\branding\generated\iuk-browser.ico"
!define MUI_UNICON "..\..\branding\generated\iuk-browser.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "..\..\branding\generated\installer-header.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "..\..\branding\generated\installer-side.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "..\..\branding\generated\installer-side.bmp"
!define MUI_FINISHPAGE_RUN "$INSTDIR\iuk-browser.exe"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var IsUpdate

Function .onInit
  StrCpy $IsUpdate "0"
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/UPDATE" $R1
  IfErrors +2 0
    StrCpy $IsUpdate "1"
  ClearErrors
  StrCmp $IsUpdate "1" 0 +2
    Sleep 2500   ; the app exits right before starting us: give it a moment to release its files
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "${SRC}\*.*"
  File "..\..\branding\generated\iuk-browser.ico"
  File "..\..\branding\generated\private.ico"
  CreateShortCut "$SMPROGRAMS\IUK Browser.lnk" "$INSTDIR\iuk-browser.exe" "" "$INSTDIR\iuk-browser.ico" 0
  CreateShortCut "$SMPROGRAMS\IUK Browser (Private).lnk" "$INSTDIR\iuk-browser.exe" "--private" "$INSTDIR\private.ico" 0
  CreateShortCut "$DESKTOP\IUK Browser.lnk" "$INSTDIR\iuk-browser.exe" "" "$INSTDIR\iuk-browser.ico" 0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\IUK Browser" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "DisplayName" "IUK Browser"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "DisplayIcon" "$INSTDIR\iuk-browser.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "Publisher" "IUK"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  ; ---- selectable in Windows Settings > Apps > Default apps (Windows asks the user to confirm; it never switches silently)
  WriteRegStr HKCU "Software\Classes\IUKBrowserHTML" "" "IUK Browser HTML Document"
  WriteRegStr HKCU "Software\Classes\IUKBrowserHTML\DefaultIcon" "" "$INSTDIR\iuk-browser.ico"
  WriteRegStr HKCU "Software\Classes\IUKBrowserHTML\shell\open\command" "" '"$INSTDIR\iuk-browser.exe" "%1"'
  WriteRegStr HKCU "Software\Classes\IUKBrowserURL" "" "IUK Browser URL"
  WriteRegStr HKCU "Software\Classes\IUKBrowserURL" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\IUKBrowserURL\DefaultIcon" "" "$INSTDIR\iuk-browser.ico"
  WriteRegStr HKCU "Software\Classes\IUKBrowserURL\shell\open\command" "" '"$INSTDIR\iuk-browser.exe" "%1"'
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser" "" "IUK Browser"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\DefaultIcon" "" "$INSTDIR\iuk-browser.ico"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\shell\open\command" "" '"$INSTDIR\iuk-browser.exe"'
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities" "ApplicationName" "IUK Browser"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities" "ApplicationDescription" "Browser with end-to-end encrypted bookmark and password sync"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities\URLAssociations" "http" "IUKBrowserURL"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities\URLAssociations" "https" "IUKBrowserURL"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities\FileAssociations" ".htm" "IUKBrowserHTML"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities\FileAssociations" ".html" "IUKBrowserHTML"
  WriteRegStr HKCU "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities\FileAssociations" ".xhtml" "IUKBrowserHTML"
  WriteRegStr HKCU "Software\RegisteredApplications" "IUK Browser" "Software\Clients\StartMenuInternet\IUKBrowser\Capabilities"
  StrCmp $IsUpdate "1" 0 +2
    Exec '"$INSTDIR\iuk-browser.exe"'   ; after an automatic update, reopen the browser
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\IUK Browser.lnk"
  Delete "$SMPROGRAMS\IUK Browser (Private).lnk"
  Delete "$DESKTOP\IUK Browser.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\IUK Browser"
  DeleteRegKey HKCU "Software\IUK Browser"
  DeleteRegKey HKCU "Software\Classes\IUKBrowserHTML"
  DeleteRegKey HKCU "Software\Classes\IUKBrowserURL"
  DeleteRegKey HKCU "Software\Clients\StartMenuInternet\IUKBrowser"
  DeleteRegValue HKCU "Software\RegisteredApplications" "IUK Browser"
SectionEnd
