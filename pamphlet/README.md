# Velan Home Foods — one-page pamphlet

A print-ready A4 flyer for Velan Home Foods' South Indian breakfast menu. The
design is a single HTML file with all measurements in millimetres, so what you
see on screen is exactly what comes out of the printer.

## What to hand to a printer

| File | Use |
| --- | --- |
| `out/velan-home-foods-pamphlet.pdf` | Send this to a print shop. A4 portrait, single page, full-bleed colour. |
| `out/velan-home-foods-pamphlet.png` | 200 dpi image for WhatsApp, Instagram or email. |
| `out/velan-home-foods-pamphlet-standalone.html` | The whole pamphlet in one file (fonts and photos inlined). Open in any browser and print — no other files needed. |

## Details on the flyer

- **Business:** Velan Home Foods — South Indian Breakfast
- **Menu:** Idly, Ven Pongal, Vadai, Vada Curry, Sambar, Chutney (3 types), Kesari
- **Phone:** 042034343
- **Offer:** Free delivery, minimum order $30 AUD

## Editing

Text and prices live in the markup at the bottom of
`velan-home-foods-pamphlet.html`; colours and type sizes are CSS custom
properties and rules at the top of the same file. The palette is deep green
`#0c3b2c` with mustard gold `#f5b820`.

Because the page is absolutely positioned to fixed millimetre coordinates,
changing the amount of text can push a block into its neighbour. The vertical
budget for the A4 page is:

| Block | Top | Notes |
| --- | --- | --- |
| Masthead | 8 mm | Logo, title, kicker pill |
| Colour band change | 116 mm | Gold hairline; the platter straddles this line |
| Menu | 157 mm | Two columns, 4 + 3 items |
| Delivery offer | 231 mm | |
| Footer | 260 mm | Phone and call to action |

After editing, re-render and check the result.

## Re-rendering

```bash
./tools/render.sh              # HTML -> PDF, then PDF -> 200 dpi PNG
python3 tools/build-standalone.py   # inline everything into one HTML file
```

`render.sh` drives headless Chrome. It deliberately calls
`/usr/bin/google-chrome-stable` rather than the `google-chrome` wrapper on this
machine, because that wrapper forces `--remote-debugging-port` and headless
Chrome then never exits. The PNG is rasterised from the PDF rather than
screenshotted, so the preview can never drift from the printed output.

Requires Python with `Pillow` and `pypdfium2`.

## Assets

- `assets/platter.png` — the breakfast platter, generated then background-keyed
  to transparency so the banana leaf can straddle the gold and green bands.
- `assets/logo.png` — circular pot-and-leaf emblem.
- `assets/fonts.css` — Playfair Display, Poppins and Bebas Neue, latin subsets
  embedded as base64 so the flyer never depends on a network or on locally
  installed fonts.

`tools/make-cutouts.py` and `tools/embed-fonts.py` regenerate the transparent
cutouts and the font stylesheet respectively.
