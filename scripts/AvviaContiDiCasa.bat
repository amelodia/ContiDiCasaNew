@echo off
setlocal
cd /d "%~dp0"
if not exist "ContiDiCasa.exe" (
    echo ERRORE: ContiDiCasa.exe non trovato in questa cartella.
    echo Non spostare solo l'exe: servono tutti i file della cartella ContiDiCasa.
    pause
    exit /b 1
)
if not exist "python312.dll" if not exist "python3.dll" (
    echo ERRORE: python312.dll mancante accanto a ContiDiCasa.exe.
    echo Reinstalla dalla cartella dist\ContiDiCasa completa o dall'installer.
    pause
    exit /b 1
)
start "" "%~dp0ContiDiCasa.exe"
