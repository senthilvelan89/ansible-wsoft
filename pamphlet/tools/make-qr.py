"""Generate the WhatsApp click-to-chat QR code printed on the pamphlet.

The QR is what makes the "Order Now" call to action usable on paper, where the
hyperlink in the PDF cannot be tapped. It is written at high resolution so the
~20 mm printed square stays crisp, and decoded again afterwards to prove the
artwork on the flyer actually resolves to the intended chat link.
"""
import pathlib
import sys

import cv2
import numpy as np
import segno

# Australian mobile 0451 640 791 in the international form wa.me requires:
# country code, no plus sign, no leading zero, no separators.
#
# Deliberately no ?text= prefill here. The prefilled greeting on the clickable
# button in the PDF costs nothing, but in a QR it pushed the symbol from 29 to
# 57 modules across, which at a 22 mm printed square means 0.35 mm modules --
# too fine to scan reliably off paper. Both destinations open the same chat.
WHATSAPP_URL = "https://wa.me/61451640791"

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "whatsapp-qr.png"

# Error correction H tolerates the most damage, which matters for a flyer that
# gets folded, pinned to a noticeboard or photographed off a wall.
qr = segno.make(WHATSAPP_URL, error="h")
qr.save(OUT, scale=20, border=2, dark="#0a3327", light="#fff8e7")

decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(
    cv2.imread(str(OUT), cv2.IMREAD_GRAYSCALE)
)

img = cv2.imread(str(OUT))
modules = 17 + 4 * qr.version
print(f"{OUT.name}: {img.shape[1]}x{img.shape[0]} px, {OUT.stat().st_size // 1024} KB, "
      f"version {qr.version} ({modules} modules -> {22 / modules:.2f} mm each at 22 mm)")

if decoded != WHATSAPP_URL:
    print(f"FAIL decoded {decoded!r}\n     expected {WHATSAPP_URL!r}", file=sys.stderr)
    raise SystemExit(1)
print(f"decoded OK -> {decoded}")
