@echo off
setlocal
cd /d "%~dp0"
set "TARGET=%~dp0AVVIA.bat"
set "LINK=%USERPROFILE%\Desktop\Conti di casa.lnk"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LINK%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%SystemRoot%\System32\imageres.dll,109'; $s.Description = 'Conti di casa (sorgente)'; $s.Save()"
echo Creato collegamento sul desktop:
echo %LINK%
pause
