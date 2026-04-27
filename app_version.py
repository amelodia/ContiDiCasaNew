"""Versione per UI, bundle macOS (.app) e metadati.

Imposta qui **APP_VERSION_MAJOR** e **APP_VERSION_MINOR** (primo e secondo numero).

Il terzo numero (**APP_VERSION_BUILD**) viene incrementato automaticamente eseguendo::

    python3 scripts/bump_version_build.py

oppure lanciando ``scripts/build_macos_app.sh`` (che invoca lo script prima di PyInstaller).
"""

APP_VERSION_MAJOR = 1
APP_VERSION_MINOR = 0
APP_VERSION_BUILD = 45
APP_VERSION = f"{11}.{1}.{0}"
