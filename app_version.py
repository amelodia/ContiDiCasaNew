"""Versione per UI, bundle macOS (.app) e metadati.

Imposta qui **APP_VERSION_MAJOR** e **APP_VERSION_MINOR** (primo e secondo numero).

Il terzo numero (**APP_VERSION_BUILD**) viene incrementato automaticamente eseguendo::

    python3 scripts/bump_version_build.py

oppure compilando con PyInstaller tramite ``ContiDiCasa.spec``.
"""

APP_VERSION_MAJOR = 1
APP_VERSION_MINOR = 0
APP_VERSION_BUILD = 105
APP_VERSION = f"{APP_VERSION_MAJOR}.{APP_VERSION_MINOR}.{APP_VERSION_BUILD}"
