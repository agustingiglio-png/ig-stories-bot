#!/usr/bin/env python3
"""Genera portadas premium para fides.bags. Dos conceptos:

  A (hero)  : foto de producto de fondo + degradado chocolate + info (campaña).
  B (card)  : tarjeta chocolate con marco fino + logo en circulo + info.

Salen a _previews/ para elegir; el elegido se copia a photos/00_portada.jpg.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
PREV = ROOT / "_previews"
HERO_SRC = ROOT / "originales" / "IMG_0423.jpeg"   # carteras marron+gris (on-brand)

W, H = 1080, 1920
BG = (58, 41, 34)
CREAM = (242, 235, 225)
TAN = (203, 173, 136)
HAIR = (120, 96, 80)

LOGO = ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf"]
R = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"]
SB = ["C:/Windows/Fonts/segoeuisb.ttf", "C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"]


def font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def tracked(d, cx, y, text, fnt, fill, tracking):
    widths = [d.textlength(c, font=fnt) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        d.text((x, y), c, font=fnt, fill=fill, anchor="lm")
        x += w + tracking


def hline(d, cy, width=120, color=TAN):
    d.rectangle([W // 2 - width // 2, cy, W // 2 + width // 2, cy + 1], fill=color)


def chevron(d, cx, cy, s=20, color=TAN, wt=3):
    d.line([(cx - s, cy - s + 6), (cx, cy + 6), (cx + s, cy - s + 6)], fill=color, width=wt)


def _info_block(d, y0):
    """Bloque comun de info, arrancando en y0. Devuelve y final."""
    tracked(d, W // 2, y0, "MEDIOS DE PAGO", font(R, 23), TAN, 8)
    tracked(d, W // 2, y0 + 56, "Efectivo  ·  Transferencia  ·  Tarjeta de crédito",
            font(R, 27), CREAM, 0)
    hline(d, y0 + 118)
    tracked(d, W // 2, y0 + 196, "ENVÍOS A TODO EL PAÍS", font(SB, 40), CREAM, 2)
    hline(d, y0 + 288)
    tracked(d, W // 2, y0 + 366, "MIRÁ EL STOCK EN LAS PRÓXIMAS HISTORIAS",
            font(R, 26), CREAM, 1)
    chevron(d, W // 2, y0 + 428)
    return y0 + 470


# --- A: hero con foto de fondo ----------------------------------------------
def variant_hero():
    with Image.open(HERO_SRC) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
        lut = [min(255, int(((i / 255.0) ** 0.82) * 255 + 0.5)) for i in range(256)]
        im = im.point(lut * 3)
        im = ImageEnhance.Color(im).enhance(1.12)
    im = ImageOps.fit(im, (W, H), Image.LANCZOS, centering=(0.5, 0.28))

    # overlay chocolate: leve arriba, solido abajo (para el texto)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = ov.load()
    top_a, mid, botfull = 70, 0.42, 0.66
    for y in range(H):
        f = y / H
        if f < mid:
            a = top_a
        elif f < botfull:
            a = int(top_a + (255 - top_a) * (f - mid) / (botfull - mid))
        else:
            a = 255
        for x in range(W):
            px[x, y] = (BG[0], BG[1], BG[2], a)
    im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")

    d = ImageDraw.Draw(im)
    d.text((W // 2, 940), "fides.", font=font(LOGO, 104), fill=CREAM, anchor="mm")
    tracked(d, W // 2, 1035, "CARTERAS & BOLSOS", font(R, 24), TAN, 8)
    _info_block(d, 1180)
    tracked(d, W // 2, 1840, "@fides.bags", font(R, 27), TAN, 6)
    return im


# --- B: tarjeta con marco + logo en circulo ---------------------------------
def variant_card():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # marco fino
    d.rectangle([44, 44, W - 44, H - 44], outline=TAN, width=2)
    d.rectangle([58, 58, W - 58, H - 58], outline=HAIR, width=1)
    # logo en circulo
    cx, cy, r = W // 2, 470, 168
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=TAN, width=3)
    d.text((cx, cy - 6), "fides.", font=font(LOGO, 92), fill=CREAM, anchor="mm")
    tracked(d, cx, cy + 92, "CARTERAS & BOLSOS", font(R, 22), TAN, 7)
    _info_block(d, 1120)
    tracked(d, W // 2, 1810, "@fides.bags", font(R, 27), TAN, 6)
    return im


def main():
    PREV.mkdir(exist_ok=True)
    variant_hero().save(PREV / "cover_A_hero.jpg", "JPEG", quality=93)
    variant_card().save(PREV / "cover_B_card.jpg", "JPEG", quality=93)
    print("covers ->", PREV)


if __name__ == "__main__":
    main()
