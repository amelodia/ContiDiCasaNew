# PyInstaller — bundle macOS (.app). Uso: pyinstaller ContiDiCasa.spec
# Dipendenze build: pip install pyinstaller (vedi scripts/build_macos_app.sh)

import importlib.util
import os
import subprocess
import sys

_AUTO_BUMP = os.environ.get("CDC_AUTO_BUMP_VERSION", "1").strip().lower() not in ("0", "false", "no", "off")
_BUMP_SCRIPT = os.path.join(SPECPATH, "scripts", "bump_version_build.py")
if _AUTO_BUMP and os.path.isfile(_BUMP_SCRIPT):
    subprocess.run([sys.executable, _BUMP_SCRIPT], cwd=SPECPATH, check=True)

_vpath = os.path.join(SPECPATH, "app_version.py")
_vspec = importlib.util.spec_from_file_location("cdc_app_version", _vpath)
_vmod = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_vmod)
_APP_VERSION = _vmod.APP_VERSION
_ICNS_PATH = os.path.join(SPECPATH, "build", "ContiDiCasa.icns")
_BUNDLE_ICON = _ICNS_PATH if os.path.isfile(_ICNS_PATH) else None

block_cipher = None

hidden = [
    "app_help_text",
    "app_version",
    "pypdf",
    "pypdf.generic",
    "pypdf._text_extraction",
    "cryptography.hazmat.backends.openssl",
    "PIL._imagingtk",
    "certifi",
    "cloud_sync_wait",
    "email_client",
    "os_boot_time",
    "data_workspace",
    "mail_gate",
    "periodiche",
    "security_auth",
    "import_legacy",
    "estratto_conto_pdf",
    "light_enc_sidecar",
    # Matplotlib PDF backend è importato dinamicamente da fig.savefig(..., format="pdf").
    "matplotlib.backends.backend_pdf",
]

if sys.platform == "darwin":
    hidden += [
        "AppKit",
        "Foundation",
        "objc",
    ]

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ContiDiCasa",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=(sys.platform == "darwin"),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ContiDiCasa",
)

app = BUNDLE(
    coll,
    name="ContiDiCasa.app",
    icon=_BUNDLE_ICON,
    bundle_identifier="it.contidicasa.desktop",
    info_plist={
        "CFBundleName": "Conti di casa",
        "CFBundleDisplayName": "Conti di casa",
        "CFBundleShortVersionString": _APP_VERSION,
        "CFBundleVersion": _APP_VERSION,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.finance",
        "NSHighResolutionCapable": True,
    },
)
