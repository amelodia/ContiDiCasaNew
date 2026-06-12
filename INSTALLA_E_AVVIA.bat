@echo off
setlocal
cd /d "%~dp0"
echo Cartella: %CD%
echo Python:
py -3 --version
echo.
echo Installazione dipendenze...
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto err
echo.
echo Test cryptography...
py -3 -c "from cryptography.fernet import Fernet; print('cryptography OK')"
if errorlevel 1 (
  echo Reinstallo cryptography e cffi...
  py -3 -m pip install --force-reinstall cryptography cffi
)
echo.
echo Avvio Conti di casa...
py -3 main_app.py
goto end
:err
echo ERRORE durante installazione.
:end
pause
