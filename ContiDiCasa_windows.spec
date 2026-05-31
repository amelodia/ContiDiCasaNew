# PyInstaller — bundle Windows onedir. Uso: pyinstaller ContiDiCasa_windows.spec
#
# Runtime accanto all'exe (contents_directory=".") e senza UPX sulle DLL: evita
# "Failed to load Python DLL" su installazioni Windows pulite / antivirus.

import importlib.util
import os

from PyInstaller.utils.hooks import collect_all

_vpath = os.path.join(SPECPATH, "app_version.py")
_vspec = importlib.util.spec_from_file_location("cdc_app_version", _vpath)
_vmod = importlib.util.module_from_spec(_vspec)
_vspec.loader.exec_module(_vmod)
_ICO_PATH = os.path.join(SPECPATH, "build", "ContiDiCasa.ico")
_EXE_ICON = _ICO_PATH if os.path.isfile(_ICO_PATH) else None

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
    "cdc_round_color_wheel",
    "cdc_ui_palette",
    "cdc_ui_theme",
    "email_client",
    "os_boot_time",
    "data_workspace",
    "mail_gate",
    "periodiche",
    "security_auth",
    "tk_foreground",
    "import_legacy",
    "estratto_conto_pdf",
    "light_enc_sidecar",
    "matplotlib.backends.backend_pdf",
    "win32com.client",
    "webview",
    "webview.platforms.edgechromium",
]

_sv_ttk_collect = collect_all("sv_ttk")
_sv_ttk_datas = list(_sv_ttk_collect[0])
_sv_ttk_binaries = list(_sv_ttk_collect[1])
_sv_ttk_hidden = list(_sv_ttk_collect[2])

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=_sv_ttk_binaries,
    datas=[
        ("webview_print_worker.py", "."),
        *_sv_ttk_datas,
    ],
    hiddenimports=hidden + _sv_ttk_hidden,
    hookspath=[],
    hooksconfig={},
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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=_EXE_ICON,
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
    upx=False,
    upx_exclude=[],
    name="ContiDiCasa",
    contents_directory=".",
)
