@echo off
setlocal

set "ROOT=%~dp0.."
set "APP=%ROOT%\main_app.py"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 -c "import sys" >nul 2>nul
    if %ERRORLEVEL%==0 (
        py -3 "%APP%" %*
        exit /b %ERRORLEVEL%
    )
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python -c "import sys" >nul 2>nul
    if %ERRORLEVEL%==0 (
        python "%APP%" %*
        exit /b %ERRORLEVEL%
    )
)

echo.
echo Python 3 non trovato.
echo Installa Python da https://www.python.org/downloads/windows/
echo e seleziona "Add python.exe to PATH", oppure installa/riabilita il Python Launcher per Windows.
echo.
echo Dopo l'installazione, esegui:
echo   py -3 -m pip install -r "%ROOT%\requirements.txt"
echo.
pause
exit /b 1
