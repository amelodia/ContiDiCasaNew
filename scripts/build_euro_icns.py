#!/usr/bin/env python3
"""Genera un file .icns per il bundle macOS dall'JPEG incorporato in euro_login_asset (stesso del login)."""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from io import BytesIO
from pathlib import Path


def main() -> int:
    if sys.platform != "darwin":
        print("Questo script richiede macOS (iconutil).", file=sys.stderr)
        return 1
    if len(sys.argv) < 2:
        print("Uso: python3 scripts/build_euro_icns.py <output.icns>", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    out_icns = Path(sys.argv[1]).resolve()
    try:
        from PIL import Image
    except ImportError as exc:
        print(f"Pillow richiesto: {exc}", file=sys.stderr)
        return 1
    try:
        from euro_login_asset import EURO_JPEG_B64
    except ImportError as exc:
        print(f"Modulo euro_login_asset non trovato: {exc}", file=sys.stderr)
        return 1

    raw = base64.standard_b64decode(EURO_JPEG_B64)
    if not raw:
        print("EURO_JPEG_B64 vuoto.", file=sys.stderr)
        return 1
    im = Image.open(BytesIO(raw)).convert("RGBA")
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))

    iconset = out_icns.with_suffix(".iconset")
    if iconset.is_dir():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    # Nomi richiesti da iconutil (pixel effettivi del PNG).
    sizes: list[tuple[int, str]] = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    try:
        resample = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
    except AttributeError:
        resample = Image.LANCZOS
    for px, name in sizes:
        thumb = im.resize((px, px), resample)
        thumb.save(iconset / name, format="PNG")

    out_icns.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out_icns)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or str(exc), file=sys.stderr)
        shutil.rmtree(iconset, ignore_errors=True)
        return 1
    shutil.rmtree(iconset, ignore_errors=True)
    print(f"Icona applicazione: {out_icns}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
