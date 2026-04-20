#!/usr/bin/env python3
"""Incrementa APP_VERSION_BUILD (terzo numero) in app_version.py.

Esegui prima di PyInstaller o manualmente dopo modifiche sostanziali.
``scripts/build_macos_app.sh`` invoca questo script automaticamente.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "app_version.py"


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    m = re.search(r"^APP_VERSION_BUILD\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    if not m:
        print("APP_VERSION_BUILD non trovato in app_version.py", file=sys.stderr)
        return 1
    n = int(m.group(1)) + 1
    text2, k = re.subn(
        r"^APP_VERSION_BUILD\s*=\s*\d+\s*$",
        f"APP_VERSION_BUILD = {n}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if k != 1:
        print("Sostituzione APP_VERSION_BUILD fallita", file=sys.stderr)
        return 1
    PATH.write_text(text2, encoding="utf-8")
    print(f"app_version.py: APP_VERSION_BUILD -> {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
