#!/usr/bin/env bash
# Render the pamphlet to a print-ready PDF, a 200 dpi PNG and a small web preview.
set -uo pipefail

cd "$(dirname "$0")/.."
SRC="file://$PWD/velan-foods-pamphlet.html"
OUT="$PWD/out"
mkdir -p "$OUT"

# Use the real binary: the /usr/local/bin/google-chrome wrapper forces
# --remote-debugging-port, which stops headless Chrome from ever exiting.
CHROME="${CHROME:-/usr/bin/google-chrome-stable}"
[ -x "$CHROME" ] || CHROME="$(command -v google-chrome-stable || command -v google-chrome)"

run() {
  local ud
  ud="$(mktemp -d)"
  timeout 120 "$CHROME" \
    --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage \
    --no-first-run --no-default-browser-check --disable-extensions \
    --disable-background-networking --disable-component-update --disable-sync \
    --hide-scrollbars --allow-file-access-from-files \
    --virtual-time-budget=8000 --user-data-dir="$ud" \
    "$@" "$SRC" >/dev/null 2>&1
  rm -rf "$ud"
}

run --print-to-pdf="$OUT/velan-foods-pamphlet.pdf" --no-pdf-header-footer

# Rasterise the PDF (not the screen view) so the PNG matches the print output.
python3 tools/pdf_to_png.py \
  "$OUT/velan-foods-pamphlet.pdf" \
  "$OUT/velan-foods-pamphlet.png" 200

# Lightweight copy that GitHub and messaging apps will display inline.
python3 tools/pdf_to_png.py \
  "$OUT/velan-foods-pamphlet.pdf" \
  "preview.jpg" 110

for f in "$OUT/velan-foods-pamphlet.pdf" "$OUT/velan-foods-pamphlet.png" "$PWD/preview.jpg"; do
  if [ -s "$f" ]; then
    echo "ok   $f ($(du -h "$f" | cut -f1))"
  else
    echo "FAIL $f was not produced" >&2
    exit 1
  fi
done
