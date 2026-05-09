#!/usr/bin/env python3
"""Genera un file .ico Windows dal JPEG incorporato in euro_login_asset."""
from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python scripts/build_euro_ico.py <output.ico>", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    out_ico = Path(sys.argv[1]).resolve()
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

    try:
        resample = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
    except AttributeError:
        resample = Image.LANCZOS

    out_ico.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon = im.resize((256, 256), resample)
    icon.save(out_ico, format="ICO", sizes=sizes)
    print(f"Icona applicazione: {out_ico}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
