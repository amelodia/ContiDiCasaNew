@echo off
setlocal
cd /d "%~dp0"
if exist "dist\ContiDiCasa\ContiDiCasa.exe" (
    cd /d "%~dp0dist\ContiDiCasa"
    call "%~dp0scripts\AvviaContiDiCasa.bat"
    exit /b %errorlevel%
)
if exist "C:\Program Files\ContiDiCasa\ContiDiCasa.exe" (
    cd /d "C:\Program Files\ContiDiCasa"
    call "%~dp0scripts\AvviaContiDiCasa.bat"
    exit /b %errorlevel%
)
echo Nessuna build trovata. Scarica l'installer da GitHub Actions oppure esegui BUILD_WINDOWS.bat.
pause
exit /b 1
