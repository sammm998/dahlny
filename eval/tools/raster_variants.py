"""Rastervarianter av en ritnings-PDF för fas 11 (SPEC 13): 200 dpi-skanning och simulerat foto.

    python eval/tools/raster_variants.py RITNING.pdf UT_KATALOG [--seed 7]

- skanning: 200 dpi, gråskala, brus σ=6;
- foto: 200 dpi, trapetsperspektiv 3 %, skugga mot ena hörnet (−35 %), brus σ=8, oskärpa 0,8 px, JPEG 80.
Utdata (`<namn>_200dpi.pdf`, `<namn>_foto.pdf`) innehåller kundens ritning – checkas aldrig in.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

DPI = 200
SCAN_NOISE, PHOTO_NOISE, KEYSTONE, SHADOW, BLUR = 6.0, 8.0, 0.03, 0.35, 0.8


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    src = pymupdf.open(args.pdf)
    scan, photo = pymupdf.open(), pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        w, h = img.size
        g = np.asarray(img.convert("L"), dtype=np.float32)
        s = Image.fromarray(np.clip(g + rng.normal(0, SCAN_NOISE, g.shape), 0, 255).astype(np.uint8))
        buf = io.BytesIO()
        s.save(buf, "PNG")
        scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, stream=buf.getvalue())
        dx = int(KEYSTONE * w)
        ph = img.transform((w, h), Image.QUAD, (dx, 0, 0, h, w, h, w - dx, 0), resample=Image.BICUBIC,
                           fillcolor=(235, 235, 230))  # fmt: skip
        a = np.asarray(ph, dtype=np.float32)
        yy, xx = np.mgrid[0:h, 0:w]
        shade = 1 - SHADOW * np.clip(1 - np.hypot(xx / w, yy / h) / 1.2, 0, 1)
        a = np.clip(a * shade[..., None] + rng.normal(0, PHOTO_NOISE, a.shape), 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(a).filter(ImageFilter.GaussianBlur(BLUR)).save(buf, "JPEG", quality=80)
        photo.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, stream=buf.getvalue())
    scan.save(args.out / f"{args.pdf.stem}_200dpi.pdf")
    photo.save(args.out / f"{args.pdf.stem}_foto.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
