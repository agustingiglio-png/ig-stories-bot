#!/usr/bin/env python3
"""Genera 3 propuestas de branding minimal/profesional sobre una imagen muestra."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "originales" / "IMG_0443.jpg"      # muestra: cartera negra
OUT = ROOT / "_previews"
CANVAS = (1080, 1920)


def font(path_list, size):
    for p in path_list:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


SANS = ["C:/Windows/Fonts/segoeuil.ttf", "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]
SANS_SB = ["C:/Windows/Fonts/segoeuisb.ttf", "C:/Windows/Fonts/segoeui.ttf",
           "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans.ttf"]


def tracked(draw, cx, y, text, fnt, fill, tracking):
    widths = [draw.textlength(c, font=fnt) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=fnt, fill=fill, anchor="lm")
        x += w + tracking


def load_photo():
    with Image.open(SRC) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
        return ImageOps.autocontrast(im, cutoff=1)


# --- A: editorial framed (bone, margenes amplios, wordmark tracked) ----------
def variant_a():
    bg = (244, 239, 232)
    c = Image.new("RGB", CANVAS, bg)
    im = load_photo()
    im = ImageOps.contain(im, (860, 1360), Image.LANCZOS)
    x = (CANVAS[0] - im.size[0]) // 2
    y = 150 + (1360 - im.size[1]) // 2
    c.paste(im, (x, y))
    d = ImageDraw.Draw(c)
    tracked(d, 540, 1690, "F I D E S", font(SANS_SB, 40), (40, 36, 31), 6)
    tracked(d, 540, 1740, "BOLSOS ARTESANALES", font(SANS, 21), (120, 110, 96), 6)
    return c


# --- B: full-bleed + gradiente + wordmark abajo ------------------------------
def variant_b():
    im = ImageOps.fit(load_photo(), CANVAS, Image.LANCZOS, centering=(0.5, 0.45))
    grad = Image.new("L", (1, CANVAS[1]), 0)
    for yy in range(CANVAS[1]):
        t = max(0, (yy - CANVAS[1] * 0.6) / (CANVAS[1] * 0.4))
        grad.putpixel((0, yy), int(150 * t))
    grad = grad.resize(CANVAS)
    black = Image.new("RGB", CANVAS, (0, 0, 0))
    im = Image.composite(black, im, grad)
    d = ImageDraw.Draw(im)
    tracked(d, 540, 1800, "F I D E S . B A G S", font(SANS, 30), (255, 255, 255), 4)
    return im


# --- C: minimal hairline frame ----------------------------------------------
def variant_c():
    bg = (247, 244, 238)
    c = Image.new("RGB", CANVAS, bg)
    im = load_photo()
    im = ImageOps.contain(im, (840, 1280), Image.LANCZOS)
    x = (CANVAS[0] - im.size[0]) // 2
    y = 210 + (1280 - im.size[1]) // 2
    c.paste(im, (x, y))
    d = ImageDraw.Draw(c)
    m = 70
    d.rectangle([m, m, CANVAS[0] - m, CANVAS[1] - m], outline=(70, 63, 54), width=2)
    tracked(d, 540, 1760, "FIDES.BAGS", font(SANS, 30), (55, 50, 43), 8)
    return c


def main():
    OUT.mkdir(exist_ok=True)
    variant_a().save(OUT / "A_editorial.jpg", "JPEG", quality=92)
    variant_b().save(OUT / "B_fullbleed.jpg", "JPEG", quality=92)
    variant_c().save(OUT / "C_hairline.jpg", "JPEG", quality=92)
    # montaje comparativo
    imgs = [Image.open(OUT / f) for f in ("A_editorial.jpg", "B_fullbleed.jpg", "C_hairline.jpg")]
    thumbs = [i.resize((540, 960)) for i in imgs]
    combo = Image.new("RGB", (540 * 3 + 40, 1010), (255, 255, 255))
    for idx, t in enumerate(thumbs):
        combo.paste(t, (idx * (540 + 20), 40))
    d = ImageDraw.Draw(combo)
    f = font(SANS_SB, 30)
    for idx, lbl in enumerate(("A  Editorial", "B  Full-bleed", "C  Hairline")):
        d.text((idx * (540 + 20) + 270, 20), lbl, font=f, fill=(0, 0, 0), anchor="mm")
    combo.save(OUT / "comparacion.jpg", "JPEG", quality=92)
    print("previews OK ->", OUT)


if __name__ == "__main__":
    main()
