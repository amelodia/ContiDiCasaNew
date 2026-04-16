# PyInstaller — bundle macOS (.app). Uso: pyinstaller ContiDiCasa.spec
# Dipendenze build: pip install pyinstaller (vedi scripts/build_macos_app.sh)

import sys

block_cipher = None

hidden = [
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
    argv_emulation=False,
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
    icon=None,
    bundle_identifier="it.contidicasa.desktop",
    info_plist={
        "CFBundleName": "Conti di casa",
        "CFBundleDisplayName": "Conti di casa",
        "NSHighResolutionCapable": True,
    },
)
