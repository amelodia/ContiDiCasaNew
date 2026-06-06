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
    python -m pip install "pyinstaller>=6.11"
}

python -m pip install -r (Join-Path $Root "requirements.txt")
python -m pip install "pyinstaller>=6.11"

if (-not $NoVersionBump) {
    python (Join-Path $Root "scripts\bump_version_build.py")
}

$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "ContiDiCasa"
$ZipPath = Join-Path $DistDir "ContiDiCasa-Windows.zip"
$InstallerPath = Join-Path $DistDir "ContiDiCasa-Windows-Setup.exe"

Remove-Item -Recurse -Force $BuildDir, $AppDir, $ZipPath, $InstallerPath -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir | Out-Null

$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir "pyinstaller-cache"
$env:MPLCONFIGDIR = Join-Path $BuildDir "matplotlib-cache"
New-Item -ItemType Directory -Force -Path $env:PYINSTALLER_CONFIG_DIR, $env:MPLCONFIGDIR | Out-Null

python (Join-Path $Root "scripts\build_euro_ico.py") (Join-Path $BuildDir "ContiDiCasa.ico")

python -m PyInstaller --noconfirm --contents-directory . (Join-Path $Root "ContiDiCasa_windows.spec")

if (-not (Test-Path $AppDir)) {
    throw "Build PyInstaller non trovato: $AppDir"
}

function Repair-ContiDiCasaOnedirLayout {
    param([string]$AppRoot)
    $internal = Join-Path $AppRoot "_internal"
    if (-not (Test-Path $internal)) {
        return
    }
    $dllAtRoot = Get-ChildItem -Path $AppRoot -Filter "python*.dll" -File -ErrorAction SilentlyContinue
    if (-not $dllAtRoot) {
        Write-Host "Correzione layout: sposto il contenuto di _internal accanto a ContiDiCasa.exe" -ForegroundColor Yellow
    } else {
        Write-Host "Correzione layout: rimuovo cartella _internal residua" -ForegroundColor Yellow
    }
    Get-ChildItem -Path $internal -Force | ForEach-Object {
        $dest = Join-Path $AppRoot $_.Name
        if (Test-Path $dest) {
            Remove-Item -Recurse -Force $dest
        }
        Move-Item -LiteralPath $_.FullName -Destination $AppRoot -Force
    }
    Remove-Item -Recurse -Force $internal -ErrorAction Stop
}

Repair-ContiDiCasaOnedirLayout -AppRoot $AppDir

$pythonDll = Get-ChildItem -Path $AppDir -Filter "python*.dll" -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pythonDll) {
    throw @"
Build Windows non valida: python*.dll non trovato accanto a ContiDiCasa.exe in:
  $AppDir

L'exe PyInstaller 6 con layout flat richiede le DLL nella stessa cartella dell'exe (non solo in _internal).
Aggiornare PyInstaller (>=6.11) e ricompilare.
"@
}

Write-Host "Layout OK: $($pythonDll.Name) accanto a ContiDiCasa.exe" -ForegroundColor Green

Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $ZipPath -Force

$env:CDC_APP_VERSION = python -c "import app_version; print(app_version.APP_VERSION)"
$Iscc = (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue)
$IsccPath = $null
if ($Iscc) {
    $IsccPath = $Iscc.Source
}
if (-not $Iscc) {
    $CommonIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $CommonIscc) {
        $IsccPath = $CommonIscc
    }
}
if ($IsccPath) {
    & $IsccPath (Join-Path $Root "installer\ContiDiCasa.iss")
    if (-not (Test-Path $InstallerPath)) {
        throw "Installer Inno Setup non trovato: $InstallerPath"
    }
} else {
    Write-Warning "ISCC.exe non trovato: salto generazione installer .exe."
}

Write-Host ""
Write-Host "Fatto: $AppDir"
Write-Host "Pacchetto Windows: $ZipPath"
if (Test-Path $InstallerPath) {
    Write-Host "Installer Windows: $InstallerPath"
}
Write-Host ""
Write-Host "Distribuire l'intera cartella dist\ContiDiCasa (o l'installer), non il solo ContiDiCasa.exe." -ForegroundColor Yellow
