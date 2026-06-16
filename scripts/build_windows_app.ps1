param(
    [switch]$NoVersionBump
)

$ErrorActionPreference = "Stop"
# GitHub Actions PowerShell 7: non terminare lo script su exit code != 0 di comandi nativi (ISCC, ecc.).
$PSNativeCommandUseErrorActionPreference = $false

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

python -m compileall -q .
if ($LASTEXITCODE -ne 0) {
    throw "Compilazione sorgenti fallita"
}

python (Join-Path $Root "scripts\build_euro_ico.py") (Join-Path $BuildDir "ContiDiCasa.ico")

python -m PyInstaller --noconfirm (Join-Path $Root "ContiDiCasa_windows.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller fallito con codice $LASTEXITCODE"
}

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
    if ($dllAtRoot) {
        Write-Host "Layout flat gia' valido: rimuovo solo _internal residua" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $internal -ErrorAction SilentlyContinue
        return
    }
    Write-Host "Correzione layout: sposto il contenuto di _internal accanto a ContiDiCasa.exe" -ForegroundColor Yellow
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

$LauncherBat = Join-Path $Root "scripts\AvviaContiDiCasa.bat"
if (Test-Path $LauncherBat) {
    Copy-Item -LiteralPath $LauncherBat -Destination (Join-Path $AppDir "Avvia ContiDiCasa.bat") -Force
}

python (Join-Path $Root "scripts\make_windows_zip.py")
if ($LASTEXITCODE -ne 0) {
    throw "Creazione zip fallita"
}

if (-not (Test-Path $ZipPath)) {
    throw "Pacchetto zip non creato: $ZipPath"
}

function Resolve-IsccPath {
    $candidates = @(
        (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 5\ISCC.exe")
        (Join-Path $env:ChocolateyInstall "bin\ISCC.exe")
        "C:\ProgramData\chocolatey\bin\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if ($candidates) {
        return (Resolve-Path $candidates[0]).Path
    }
    $found = Get-ChildItem -Path @(
        ${env:ProgramFiles(x86)},
        $env:ProgramFiles,
        "C:\ProgramData\chocolatey\lib"
    ) -Filter "ISCC.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) {
        return $found.FullName
    }
    return $null
}

$env:CDC_APP_VERSION = (
    python -c "import app_version; print(app_version.APP_VERSION, end='')"
).Trim()
if (-not $env:CDC_APP_VERSION) {
    $env:CDC_APP_VERSION = "0.0.0"
}

$IsccPath = Resolve-IsccPath
if ($IsccPath) {
    Write-Host "Inno Setup: $IsccPath (versione app $($env:CDC_APP_VERSION))" -ForegroundColor Cyan
    $IssPath = Join-Path $Root "installer\ContiDiCasa.iss"
    & $IsccPath "/DMyAppVersion=$($env:CDC_APP_VERSION)" $IssPath
    $isccExit = $LASTEXITCODE
    if ($isccExit -ne 0) {
        Write-Warning "Inno Setup fallito con codice $isccExit"
    }
    if (-not (Test-Path $InstallerPath)) {
        Write-Warning "Installer Inno Setup non trovato: $InstallerPath"
    }
} else {
    Write-Warning "ISCC.exe non trovato: salto generazione installer .exe."
}

if ($env:CI -eq "true" -and -not (Test-Path $InstallerPath)) {
    throw @"
Installer Windows non creato su CI.
ISCC: $(if ($IsccPath) { $IsccPath } else { 'non trovato' })
Atteso: $InstallerPath
Verificare choco install innosetup e installer/ContiDiCasa.iss
"@
}

Write-Host ""
Write-Host "Fatto: $AppDir"
Write-Host "Pacchetto Windows: $ZipPath"
if (Test-Path $InstallerPath) {
    Write-Host "Installer Windows: $InstallerPath"
}
Write-Host ""
Write-Host "Distribuire l'intera cartella dist\ContiDiCasa (o l'installer), non il solo ContiDiCasa.exe." -ForegroundColor Yellow
exit 0
