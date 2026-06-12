@echo off
setlocal
cd /d "%~dp0"
echo Build installer Windows Conti di casa...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows_app.ps1"
echo.
if exist "dist\ContiDiCasa-Windows-Setup.exe" (
    echo Installer creato: dist\ContiDiCasa-Windows-Setup.exe
) else (
    echo Installer non creato. Serve Inno Setup 6 oppure usare lo zip in dist\ContiDiCasa-Windows.zip
)
pause
