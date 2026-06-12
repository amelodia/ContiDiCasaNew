@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  Reinstalla Conti di casa (build aggiornata con fix Windows)
echo ============================================================
echo.
echo L'exe in "C:\Program Files\ContiDiCasa" e' una build VECCHIA
echo senza i fix di avvio. Questo script crea un nuovo installer.
echo.
echo Serve: Python 3.12 o 3.13 (consigliato) e Inno Setup 6 opzionale.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows_app.ps1"
if errorlevel 1 (
    echo.
    echo Build fallita. Puoi usare intanto: AVVIA.bat ^(da sorgente^)
    pause
    exit /b 1
)
if not exist "dist\ContiDiCasa-Windows-Setup.exe" (
    echo.
    echo Installer non creato ^(manca Inno Setup^).
    echo Esegui manualmente: dist\ContiDiCasa\ContiDiCasa.exe
    pause
    exit /b 0
)
echo.
echo Avvio installer ^(accetta icona desktop se la vuoi^)...
start "" "dist\ContiDiCasa-Windows-Setup.exe"
echo.
pause
