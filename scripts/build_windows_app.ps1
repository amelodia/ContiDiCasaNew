$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if ($env:OS -ne "Windows_NT") {
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

Remove-Item -Recurse -Force (Join-Path $Root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $Root "dist\ContiDiCasa") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path $Root "dist\ContiDiCasa-windows.zip") -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force -Path (Join-Path $Root "build") | Out-Null
$env:PYINSTALLER_CONFIG_DIR = Join-Path $Root "build\pyinstaller-cache"
$env:MPLCONFIGDIR = Join-Path $Root "build\matplotlib-cache"
New-Item -ItemType Directory -Force -Path $env:PYINSTALLER_CONFIG_DIR, $env:MPLCONFIGDIR | Out-Null

python -m PyInstaller --noconfirm (Join-Path $Root "ContiDiCasa.spec")

$DistDir = Join-Path $Root "dist\ContiDiCasa"
$ExePath = Join-Path $DistDir "ContiDiCasa.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build non riuscita: $ExePath non trovato."
}

$ZipPath = Join-Path $Root "dist\ContiDiCasa-windows.zip"
Compress-Archive -Path (Join-Path $DistDir "*") -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Fatto: $DistDir"
Write-Host "Archivio: $ZipPath"
