"""Rasterise the pamphlet PDF so the preview matches exactly what prints.

Usage: pdf_to_png.py <src.pdf> <dst.png|dst.jpg> [dpi]

A .jpg destination is written as JPEG, which keeps the small web preview a
fraction of the size of a PNG for this photo-heavy artwork.
"""
import pathlib
import sys

import pypdfium2 as pdfium

src, dst = sys.argv[1], sys.argv[2]
dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 200

page = pdfium.PdfDocument(src)[0]
img = page.render(scale=dpi / 72).to_pil().convert("RGB")

if pathlib.Path(dst).suffix.lower() in (".jpg", ".jpeg"):
    img.save(dst, quality=86, optimize=True, progressive=True)
else:
    img.save(dst, optimize=True)

size_kb = pathlib.Path(dst).stat().st_size // 1024
print(f"{dst}: {img.size[0]}x{img.size[1]} @ {dpi} dpi, {size_kb} KB")
