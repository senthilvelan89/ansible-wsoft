"""Build assets/fonts.css with the pamphlet's webfonts inlined as base64.

Fonts come from Fontsource rather than the Google Fonts CSS API on purpose.
The API now serves Playfair Display as a variable font, and headless Chrome
embeds variable fonts into PDFs as Type3 glyph procedures, which some prepress
workflows render poorly and which breaks text selection. Fontsource ships
static per-weight instances, so Chrome embeds them as ordinary CID fonts.
"""
import base64
import pathlib
import urllib.request

CDN = "https://cdn.jsdelivr.net/npm/@fontsource/{slug}/files/{slug}-latin-{weight}-{style}.woff2"

# (css family name, fontsource slug, faces actually used by the pamphlet)
FAMILIES = [
    ("Playfair Display", "playfair-display",
     [(700, "normal"), (700, "italic"), (900, "normal")]),
    ("Poppins", "poppins",
     [(w, "normal") for w in (400, 500, 600, 700, 800)]),
    ("Bebas Neue", "bebas-neue", [(400, "normal")]),
]

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "fonts.css"

blocks = []
total = 0
for family, slug, faces in FAMILIES:
    for weight, style in faces:
        url = CDN.format(slug=slug, weight=weight, style=style)
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        total += len(data)
        b64 = base64.b64encode(data).decode()
        blocks.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            f"  font-style: {style};\n"
            f"  font-weight: {weight};\n"
            "  font-display: block;\n"
            f"  src: url(data:font/woff2;base64,{b64}) format('woff2');\n"
            "}"
        )
        print(f"embedded {family} {weight} {style} ({len(data) // 1024} KB)")

OUT.write_text("\n".join(blocks) + "\n")
print(f"\nwrote {OUT} — {len(blocks)} faces, {total // 1024} KB of font data")
