#!/usr/bin/env python3
"""Crea dist/ContiDiCasa-Windows.zip dal contenuto di dist/ContiDiCasa."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    app_dir = root / "dist" / "ContiDiCasa"
    zip_path = root / "dist" / "ContiDiCasa-Windows.zip"
    if not app_dir.is_dir():
        print(f"Cartella non trovata: {app_dir}", file=sys.stderr)
        return 1
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.is_file():
        zip_path.unlink()
    count = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(app_dir.rglob("*")):
            if not path.is_file():
                continue
            arc = path.relative_to(app_dir).as_posix()
            zf.write(path, arc)
            count += 1
    print(f"Pacchetto Windows: {zip_path} ({count} file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
