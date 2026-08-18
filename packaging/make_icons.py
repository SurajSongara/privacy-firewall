"""Generate the app icons from a single vector-ish drawing.

Run this only when the icon design changes; the generated ``icon.png``,
``icon.ico`` and ``icon.icns`` are committed so a build never depends on
Pillow being installed.

    python packaging/make_icons.py

The mark is a document with two redaction bars across it — the product's
actual job — on a deep slate field.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
MASTER = 1024

BACKGROUND = (25, 34, 54)  # deep slate
PAPER = (247, 248, 252)  # off-white document
BAR = (17, 22, 36)  # redaction bar
ACCENT = (79, 140, 255)  # blue accent bar

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw_master() -> Image.Image:
    """Render the icon at 1024px with an alpha channel."""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded-square field.
    d.rounded_rectangle([0, 0, MASTER - 1, MASTER - 1], radius=224, fill=BACKGROUND)

    # Document sheet with a folded look (plain rectangle reads better at 16px).
    sheet = [252, 196, 772, 828]
    d.rounded_rectangle(sheet, radius=40, fill=PAPER)

    # Text lines, with two of them redacted to black bars.
    left, right = 336, 688
    rows = [
        (300, ACCENT, 0.62),  # a normal line
        (400, BAR, 1.00),  # redacted
        (500, ACCENT, 0.48),  # a normal line
        (600, BAR, 0.86),  # redacted
        (700, ACCENT, 0.34),  # a normal line
    ]
    for y, colour, width_frac in rows:
        end = left + int((right - left) * width_frac)
        d.rounded_rectangle([left, y, end, y + 52], radius=26, fill=colour)

    return img


def main() -> None:
    """Write icon.png, icon.ico and icon.icns next to this script."""
    master = draw_master()

    png_path = HERE / "icon.png"
    master.resize((512, 512), Image.LANCZOS).save(png_path)
    print(f"wrote {png_path}")

    ico_path = HERE / "icon.ico"
    master.save(ico_path, sizes=[(s, s) for s in ICO_SIZES])
    print(f"wrote {ico_path}")

    icns_path = HERE / "icon.icns"
    try:
        # ICNS wants a square RGBA image; Pillow derives the members it needs.
        master.save(icns_path)
        print(f"wrote {icns_path}")
    except Exception as exc:  # noqa: BLE001 - ICNS save is platform-dependent
        print(f"WARNING: could not write {icns_path}: {exc}")
        print("The macOS build will fall back to the default PyInstaller icon.")


if __name__ == "__main__":
    main()
