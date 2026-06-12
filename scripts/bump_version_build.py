#!/usr/bin/env python3
"""Incrementa APP_VERSION_BUILD (terzo numero) in app_version.py.

Esegui prima di PyInstaller o manualmente dopo modifiche sostanziali.
``scripts/build_macos_app.sh`` e ``scripts/build_windows_app.ps1`` invocano questo script.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "app_version.py"


def _sync_app_version_string(text: str, *, major: int, minor: int, build: int) -> str:
    replacement = f'APP_VERSION = f"{{APP_VERSION_MAJOR}}.{{APP_VERSION_MINOR}}.{{APP_VERSION_BUILD}}"'
    if re.search(r"^APP_VERSION\s*=", text, re.MULTILINE):
        text, n = re.subn(
            r"^APP_VERSION\s*=.*$",
            replacement,
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n != 1:
            print("Sostituzione APP_VERSION fallita", file=sys.stderr)
            sys.exit(1)
    else:
        text = text.rstrip() + f"\n{replacement}\n"
    return text


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    major_m = re.search(r"^APP_VERSION_MAJOR\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    minor_m = re.search(r"^APP_VERSION_MINOR\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    build_m = re.search(r"^APP_VERSION_BUILD\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    if not build_m:
        print("APP_VERSION_BUILD non trovato in app_version.py", file=sys.stderr)
        return 1
    major = int(major_m.group(1)) if major_m else 1
    minor = int(minor_m.group(1)) if minor_m else 0
    n = int(build_m.group(1)) + 1
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
    text2 = _sync_app_version_string(text2, major=major, minor=minor, build=n)
    PATH.write_text(text2, encoding="utf-8")
    print(f"app_version.py: APP_VERSION -> {major}.{minor}.{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
