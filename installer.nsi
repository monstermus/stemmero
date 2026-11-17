; Stemmero. installer (NSIS)
; Byg: makensis installer.nsi   (kræver dist\Stemmero.exe)

Unicode true
!define APPNAME "Stemmero"
!define VERSION "1.1.0"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Name "${APPNAME}"
OutFile "Stemmero-Setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\${APPNAME}"
SetCompressor /SOLID lzma
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

!include "MUI2.nsh"
!define MUI_WELCOMEPAGE_TEXT "Stemmero advarer dig, når du taler for højt i headsettet.$\r$\n$\r$\nProgrammet starter automatisk, når du logger ind på Windows, og genstartes, hvis det bliver lukket."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "Stemmero er installeret.$\r$\n$\r$\nÅbn indstillingerne fra Start-menuen."
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Danish"

Section "Install"
  SetShellVarContext current
  ; stop en evt. tidligere udgave
  nsExec::Exec 'taskkill /F /IM Stemmero.exe'
  Sleep 800

  SetOutPath "$INSTDIR"
  File "dist\Stemmero.exe"
  File "task.ps1"
  File "LICENSE"
  File "dist\THIRD-PARTY-LICENSES.txt"
  WriteUninstaller "$INSTDIR\Afinstaller.exe"

  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\Stemmero.exe"

  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "Daniel Prehn"
  WriteRegStr HKCU "${UNINSTKEY}" "URLInfoAbout" "https://github.com/monstermus/stemmero"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\Stemmero.exe"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Afinstaller.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1

  ; autostart + genstart via Opgavestyring
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\task.ps1" -Mode install -Exe "$INSTDIR\Stemmero.exe"'
  Pop $0
  StrCmp $0 "0" +2
    MessageBox MB_ICONEXCLAMATION|MB_OK "Autostart kunne ikke sættes op (fejlkode $0). Programmet kan stadig startes fra Start-menuen." /SD IDOK
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ; fjern opgaven først, så den ikke genstarter programmet
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\task.ps1" -Mode uninstall'
  nsExec::Exec 'taskkill /F /IM Stemmero.exe'
  Sleep 800

  Delete "$INSTDIR\Stemmero.exe"
  Delete "$INSTDIR\task.ps1"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD-PARTY-LICENSES.txt"
  Delete "$INSTDIR\Afinstaller.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  DeleteRegKey HKCU "${UNINSTKEY}"
SectionEnd
