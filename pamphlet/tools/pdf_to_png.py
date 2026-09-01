"""Rasterise the pamphlet PDF so the preview matches exactly what prints."""
import sys

import pypdfium2 as pdfium

src, dst = sys.argv[1], sys.argv[2]
dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 200

page = pdfium.PdfDocument(src)[0]
img = page.render(scale=dpi / 72).to_pil().convert("RGB")
img.save(dst, optimize=True)
print(f"{dst}: {img.size[0]}x{img.size[1]} @ {dpi} dpi")
