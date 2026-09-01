"""Download Google Fonts latin subsets and emit a CSS file with base64 data URIs."""
import base64
import re
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

FAMILIES = [
    "Playfair+Display:ital,wght@0,700;0,800;0,900;1,700",
    "Poppins:wght@400;500;600;700;800",
    "Bebas+Neue",
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


blocks_out = []
for family in FAMILIES:
    css = fetch(f"https://fonts.googleapis.com/css2?family={family}&display=swap").decode()
    for block in re.findall(r"@font-face\s*\{[^}]*\}", css):
        # Keep only the latin subset to keep the embedded payload small.
        rng = re.search(r"unicode-range:\s*([^;]+);", block)
        if not rng or "U+0000-00FF" not in rng.group(1):
            continue
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not url:
            continue
        data = fetch(url.group(1))
        b64 = base64.b64encode(data).decode()
        block = block.replace(url.group(1), f"data:font/woff2;base64,{b64}")
        block = re.sub(r"\s*unicode-range:[^;]+;", "", block)
        blocks_out.append(block.strip())
        name = re.search(r"font-family:\s*'([^']+)'", block).group(1)
        weight = re.search(r"font-weight:\s*([\d ]+)", block)
        style = re.search(r"font-style:\s*(\w+)", block)
        print(f"embedded {name} {weight.group(1).strip() if weight else '?'} "
              f"{style.group(1) if style else ''} ({len(data)//1024} KB)")

with open("fonts.css", "w") as fh:
    fh.write("\n".join(blocks_out) + "\n")
print(f"\nwrote fonts.css with {len(blocks_out)} faces")
