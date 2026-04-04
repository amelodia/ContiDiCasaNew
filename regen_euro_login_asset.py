#!/usr/bin/env python3
"""
Rigenera ``euro_login_asset.py``.

Senza opzioni: crea un JPEG neutro (sfondo finestra login + simbolo €), senza disco giallo.
Con ``--from-assets``: incorpora ``assets/euro.jpg`` (foto personalizzata).
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "assets" / "euro.jpg"
OUT = ROOT / "euro_login_asset.py"

# Allineato a security_auth._LOGIN_IMG_CANVAS_BG
_BANNER_BG = (216, 236, 245)
_SYMBOL_INK = (28, 52, 78)


def build_neutral_login_jpeg(*, size: int = 200) -> bytes:
    """JPEG minimale per accesso: stesso azzurro della finestra, simbolo € (niente moneta stilizzata)."""
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (size, size), _BANNER_BG)
    d = ImageDraw.Draw(im)
    font = None
    for p in (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\arialuni.ttf",
    ):
        try:
            font = ImageFont.truetype(p, int(size * 0.44))
            break
        except OSError:
            continue
    sym = "€"
    if font is not None:
        bbox = d.textbbox((0, 0), sym, font=font)
        x = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (size - (bbox[3] - bbox[1])) // 2 - bbox[1]
        d.text((x, y), sym, fill=_SYMBOL_INK, font=font)
    else:
        f0 = ImageFont.load_default()
        d.text((size // 2 - 4, size // 2 - 4), "E", fill=_SYMBOL_INK, font=f0)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def write_euro_login_module(data: bytes) -> None:
    b64 = base64.b64encode(data).decode("ascii")
    w = 76
    lines = [b64[i : i + w] for i in range(0, len(b64), w)]
    body = (
        "# Immagine login incorporata (JPEG). Rigenerare con: python3 regen_euro_login_asset.py [--from-assets]\n"
        "EURO_JPEG_B64 = (\n"
        + "".join(f'    "{line}"\n' for line in lines)
        + ")\n"
    )
    OUT.write_text(body, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Rigenera euro_login_asset.py")
    ap.add_argument(
        "--from-assets",
        action="store_true",
        help=f"Incorpora {SRC} (foto tua) invece del segnaposto neutro",
    )
    args = ap.parse_args()
    if args.from_assets:
        if not SRC.is_file():
            print(f"Errore: manca {SRC}", file=sys.stderr)
            sys.exit(1)
        data = SRC.read_bytes()
        src = "assets/euro.jpg"
    else:
        try:
            data = build_neutral_login_jpeg()
        except ImportError:
            print("Errore: serve Pillow (pip install Pillow) per generare il segnaposto.", file=sys.stderr)
            sys.exit(1)
        src = "segnaposto neutro (sfondo + €)"
    write_euro_login_module(data)
    print(f"OK: {len(data)} byte da {src} -> {OUT.name}")


if __name__ == "__main__":
    main()
