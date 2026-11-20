"""Draw the app icon (the white knight on a blue tile, as in the sidebar) into app/build/icon.png and icon.ico.

    python tools/make_icon.py
"""

import io
import re
from pathlib import Path

import resvg_py
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SPRITE = ROOT / "app" / "renderer" / "assets" / "pieces.svg"
OUT = ROOT / "app" / "build"


def knight_svg(size: int) -> str:
    sprite = SPRITE.read_text(encoding="utf-8")
    knight = re.search(r'<g id="wn".*?</g>\s*(?=<g id=|</defs>|</svg>)', sprite, re.S)
    if knight is None:  # structure of the sprite differs: fall back to the whole symbol list and <use>
        raise SystemExit("could not find the white knight in pieces.svg")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 512 512">
  <defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2E9BFF"/><stop offset="1" stop-color="#0A60E0"/></linearGradient></defs>
  <rect x="16" y="16" width="480" height="480" rx="112" fill="url(#bg)"/>
  <g transform="translate(76 66) scale(9.1)">{knight.group(0)}</g>
</svg>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    png = bytes(resvg_py.svg_to_bytes(svg_string=knight_svg(512), width=512, height=512))
    (OUT / "icon.png").write_bytes(png)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    image.save(OUT / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    print("wrote", OUT / "icon.png", "and", OUT / "icon.ico")


if __name__ == "__main__":
    main()
