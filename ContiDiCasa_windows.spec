# PyInstaller — bundle Windows onedir. Uso: pyinstaller ContiDiCasa_windows.spec
#
# Runtime accanto all'exe (contents_directory=".") e senza UPX sulle DLL: evita
# "Failed to load Python DLL" su installazioni Windows pulite / antivirus.

import os

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
    "email_client",
    "os_boot_time",
    "data_workspace",
    "mail_gate",
    "periodiche",
    "security_auth",
    "import_legacy",
    "estratto_conto_pdf",
    "light_enc_sidecar",
    "matplotlib.backends.backend_pdf",
    "win32com.client",
    "webview",
    "webview.platforms.edgechromium",
]

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("webview_print_worker.py", "."),
    ],
    hiddenimports=hidden,
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
    contents_directory=".",
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
)
