@echo off
setlocal
cd /d "%~dp0"
echo Avvio Conti di casa (eventuali errori compaiono qui sotto)...
echo.
py -3 main_app.py
echo.
echo Exit code: %ERRORLEVEL%
pause
