@echo off
REM Bygger Stemmero-Setup.exe. Kraever Python og NSIS:
REM   winget install Python.Python.3.12
REM   winget install NSIS.NSIS
cd /d "%~dp0"

python -m pip install -r requirements-build.txt || goto :fejl
python -m unittest discover -s tests -v || goto :fejl
python -m PyInstaller --clean --noconfirm --noconsole --onefile --name Stemmero --add-data "LICENSE;." --collect-all sounddevice stemmero.py || goto :fejl
python scripts\collect_licenses.py || goto :fejl

set MAKENSIS=makensis
where makensis >nul 2>nul || set MAKENSIS="%ProgramFiles(x86)%\NSIS\makensis.exe"
%MAKENSIS% installer.nsi || goto :fejl

echo.
echo Faerdig: Stemmero-Setup.exe
pause
exit /b 0

:fejl
echo.
echo Noget gik galt - se fejlen ovenfor.
pause
exit /b 1
