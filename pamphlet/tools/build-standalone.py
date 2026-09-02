"""Inline the stylesheet and images to produce a single portable HTML file.

The result opens and prints correctly from any machine with no sibling asset
folder, which makes it easy to email to a print shop.
"""
import base64
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "velan-foods-pamphlet.html"
DST = ROOT / "out" / "velan-foods-pamphlet-standalone.html"

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}

html = SRC.read_text()

fonts = (ROOT / "assets" / "fonts.css").read_text()
html = html.replace(
    '<link rel="stylesheet" href="assets/fonts.css">',
    f"<style>\n{fonts}</style>",
)


def inline_image(match):
    path = ROOT / match.group(1)
    data = base64.b64encode(path.read_bytes()).decode()
    return f'src="data:{MIME[path.suffix]};base64,{data}"'


html = re.sub(r'src="(assets/[^"]+)"', inline_image, html)

if "assets/" in html:
    raise SystemExit(f"unresolved asset reference: {re.findall(r'assets/[^\"]+', html)}")

DST.parent.mkdir(exist_ok=True)
DST.write_text(html)
print(f"{DST}: {len(html) / 1e6:.1f} MB, fully self-contained")
