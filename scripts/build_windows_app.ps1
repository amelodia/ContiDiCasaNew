Param()

# Crea dist/ContiDiCasa/ e dist/ContiDiCasa-windows.zip (Windows) con PyInstaller.
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $Activate) {
    . $Activate
}

$Python = @("python")
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    $Python = @("py", "-3")
}

function Invoke-ProjectPython {
    if ($Python.Length -gt 1) {
        & $Python[0] $Python[1] @args
    } else {
        & $Python[0] @args
    }
}

Invoke-ProjectPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installo PyInstaller nel Python corrente..." -ForegroundColor Yellow
    Invoke-ProjectPython -m pip install --upgrade pip
    Invoke-ProjectPython -m pip install "pyinstaller>=6.0"
}

Invoke-ProjectPython -m pip install -r (Join-Path $Root "requirements.txt")
Invoke-ProjectPython (Join-Path $Root "scripts\bump_version_build.py")

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "dist\ContiDiCasa") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $Root "dist\ContiDiCasa-windows.zip") -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force -Path (Join-Path $Root "build") | Out-Null
$env:PYINSTALLER_CONFIG_DIR = Join-Path $Root "build\pyinstaller-cache"
$env:MPLCONFIGDIR = Join-Path $Root "build\matplotlib-cache"
New-Item -ItemType Directory -Force -Path $env:PYINSTALLER_CONFIG_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:MPLCONFIGDIR | Out-Null

Invoke-ProjectPython -m PyInstaller --noconfirm (Join-Path $Root "ContiDiCasa.spec")

$DistDir = Join-Path $Root "dist\ContiDiCasa"
$ZipPath = Join-Path $Root "dist\ContiDiCasa-windows.zip"
Compress-Archive -Path $DistDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Fatto: $DistDir"
Write-Host "Archivio pronto: $ZipPath"
Write-Host "Distribuire l'intera cartella o lo zip, non il solo ContiDiCasa.exe."
