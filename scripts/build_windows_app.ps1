param(
    [switch]$NoVersionBump
)

$ErrorActionPreference = "Stop"

$IsWindowsPlatform = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $IsWindowsPlatform) {
    throw "Questo script e pensato per Windows."
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$VenvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
}

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    python -m pip install --upgrade pip
    python -m pip install "pyinstaller>=6.0"
}

python -m pip install -r (Join-Path $Root "requirements.txt")

if (-not $NoVersionBump) {
    python (Join-Path $Root "scripts\bump_version_build.py")
}

$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "ContiDiCasa"
$ZipPath = Join-Path $DistDir "ContiDiCasa-Windows.zip"

Remove-Item -Recurse -Force $BuildDir, $AppDir, $ZipPath -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir | Out-Null

$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir "pyinstaller-cache"
$env:MPLCONFIGDIR = Join-Path $BuildDir "matplotlib-cache"
New-Item -ItemType Directory -Force -Path $env:PYINSTALLER_CONFIG_DIR, $env:MPLCONFIGDIR | Out-Null

python -m PyInstaller --noconfirm (Join-Path $Root "ContiDiCasa_windows.spec")

if (-not (Test-Path $AppDir)) {
    throw "Build PyInstaller non trovato: $AppDir"
}

Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Fatto: $AppDir"
Write-Host "Pacchetto Windows: $ZipPath"
