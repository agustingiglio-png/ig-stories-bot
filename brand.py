#!/usr/bin/env python3
"""Branding FULL-BLEED uniforme para las FOTOS de photos/ (Stories cohesivas).

- Foto recortada a 1080x1920 (llena la pantalla, centrada).
- Ajuste de color leve y parejo para que todas combinen.
- Degradado sutil abajo + wordmark 'FIDES.BAGS' en blanco (tracked).

Los ORIGINALES se respaldan en originales/ (una sola vez) y SIEMPRE se parte
de ahi, asi se puede re-brandear sin degradar. Los videos NO se tocan aca.

Uso:  python brand.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
PHOTOS = ROOT / "photos"
BACKUP = ROOT / "originales"
IMAGE_EXT = {".jpg", ".jpeg", ".png"}

CANVAS = (1080, 1920)
WORDMARK = "F I D E S . B A G S"
WM_SIZE = 30
WM_TRACK = 4
GRAD_STRENGTH = 150          # oscurecimiento maximo del degradado inferior (0-255)
GRAD_START = 0.60            # desde donde arranca el degradado (fraccion de alto)

SANS = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]


def _font(size):
    for p in SANS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _tracked(draw, cx, y, text, fnt, fill, tracking, shadow=None):
    widths = [draw.textlength(c, font=fnt) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x0 = cx - total / 2
    for dx, dy, col in (shadow or []) + [(0, 0, fill)]:
        x = x0
        for c, w in zip(text, widths):
            draw.text((x + dx, y + dy), c, font=fnt, fill=col, anchor="lm")
            x += w + tracking


def brand_one(src: Path) -> Image.Image:
    with Image.open(src) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
        im = ImageOps.autocontrast(im, cutoff=1)
    im = ImageOps.fit(im, CANVAS, Image.LANCZOS, centering=(0.5, 0.45))

    # degradado inferior para legibilidad del wordmark
    grad = Image.new("L", (1, CANVAS[1]), 0)
    span = CANVAS[1] * (1 - GRAD_START)
    for yy in range(CANVAS[1]):
        t = max(0.0, (yy - CANVAS[1] * GRAD_START) / span)
        grad.putpixel((0, yy), int(GRAD_STRENGTH * t))
    grad = grad.resize(CANVAS)
    im = Image.composite(Image.new("RGB", CANVAS, (0, 0, 0)), im, grad)

    d = ImageDraw.Draw(im)
    _tracked(d, CANVAS[0] // 2, 1800, WORDMARK, _font(WM_SIZE),
             (255, 255, 255), WM_TRACK,
             shadow=[(2, 2, (0, 0, 0))])   # sombra sutil para legibilidad
    return im


def main():
    BACKUP.mkdir(exist_ok=True)
    files = sorted([p for p in PHOTOS.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_EXT],
                   key=lambda p: p.name.lower())
    if not files:
        print("No hay imagenes en photos/")
        return
    for src in files:
        bak = BACKUP / src.name
        if not bak.exists():
            shutil.copy2(src, bak)
        out = brand_one(bak)
        target = src if src.suffix.lower() in (".jpg", ".jpeg") else src.with_suffix(".jpg")
        out.save(target, "JPEG", quality=92, optimize=True)
        if src.suffix.lower() == ".png":
            src.unlink()
        print(f"  brandeada: {target.name}")
    print(f"Listo. {len(files)} imagenes full-bleed. Originales en originales/")


if __name__ == "__main__":
    main()
