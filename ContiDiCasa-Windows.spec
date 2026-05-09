# PyInstaller — bundle Windows one-folder. Uso: python -m PyInstaller ContiDiCasa-Windows.spec
# Dipendenze build: pip install pyinstaller; poi pip install -r requirements.txt su Windows.

import importlib.util
import os
import sys

if sys.platform != "win32":
    raise SystemExit("ContiDiCasa-Windows.spec deve essere eseguito con Python Windows.")

_vpath = os.path.join(SPECPATH, "app_version.py")
_vspec = importlib.util.spec_from_file_location("cdc_app_version", _vpath)
_vmod = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_vmod)
_APP_VERSION = _vmod.APP_VERSION
_ICO_PATH = os.path.join(SPECPATH, "build", "ContiDiCasa.ico")
_BUNDLE_ICON = _ICO_PATH if os.path.isfile(_ICO_PATH) else None

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
    "webview",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    # Matplotlib PDF backend è importato dinamicamente da fig.savefig(..., format="pdf").
    "matplotlib.backends.backend_pdf",
]

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=[("webview_print_worker.py", ".")],
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
    icon=_BUNDLE_ICON,
    version=None,
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
