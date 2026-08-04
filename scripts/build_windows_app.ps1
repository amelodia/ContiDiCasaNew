# Crea dist\ContiDiCasa\ContiDiCasa.exe e dist\ContiDiCasa-windows.zip con PyInstaller.
# Eseguire da Windows PowerShell dopo aver creato/attivato un Python 3 recente.
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$IsRunningOnWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
if (-not $IsRunningOnWindows) {
    throw "Questo script deve essere eseguito su Windows."
}

$VenvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
}

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installo PyInstaller nel Python corrente..."
    python -m pip install --upgrade pip
    python -m pip install "pyinstaller>=6.0"
}

python -m pip install -r (Join-Path $Root "requirements.txt")
python (Join-Path $Root "scripts\bump_version_build.py")

$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$AppDist = Join-Path $DistDir "ContiDiCasa"
$ZipPath = Join-Path $DistDir "ContiDiCasa-windows.zip"

Remove-Item -Recurse -Force $BuildDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $AppDist -ErrorAction SilentlyContinue
Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $BuildDir | Out-Null

$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir "pyinstaller-cache"
$env:MPLCONFIGDIR = Join-Path $BuildDir "matplotlib-cache"
New-Item -ItemType Directory -Force $env:PYINSTALLER_CONFIG_DIR | Out-Null
New-Item -ItemType Directory -Force $env:MPLCONFIGDIR | Out-Null

python (Join-Path $Root "scripts\build_euro_ico.py") (Join-Path $BuildDir "ContiDiCasa.ico")
python -m PyInstaller --noconfirm (Join-Path $Root "ContiDiCasa-Windows.spec")

Compress-Archive -Path (Join-Path $AppDist "*") -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Fatto: $AppDist"
Write-Host "Archivio: $ZipPath"
