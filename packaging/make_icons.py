"""Make the app icons from the one source picture, packaging/icon-source.png.

The source is a 1024x1024 PNG with transparent rounded corners (about 160 px
radius). From it this writes, into the output folder:

  LitReview.ico      Windows: the picture as it is, at 16 to 256 px.
  tray.png           the Windows tray icon (128 px, the colour logo).
  trayTemplate.png   the macOS menu-bar icon: a plain black cap on transparent,
                     36 px to be shown at 18 points (see menu_template).
  mac-preview.png    the macOS look at full size (to check it by eye).
  LitReview.iconset/ the macOS icon sizes, ready for `iconutil -c icns`
                     (iconutil only exists on a Mac, so CI runs it there).

macOS does not round or shadow an app icon for you, so the Mac version is made
here: the picture is scaled to 824x824 and centred on a transparent 1024x1024
canvas (Apple's template leaves that margin for the shadow), cut to a squircle
(a superellipse, closer to Apple's continuous corner than a plain circular
radius; the source's own, smaller rounding falls outside it), and given a soft
drop shadow.

    python packaging/make_icons.py [--source PATH] [--out DIR]
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent

CANVAS = 1024
ART = 824  # the icon shape inside the Mac canvas
SQUIRCLE_POWER = 5  # superellipse exponent; 4 is rounder-squarer, 5 is close to Apple's
SHADOW_OFFSET_Y = 12
SHADOW_BLUR = 14  # Gaussian radius (about a 28 px blur)
SHADOW_OPACITY = 0.5

# The macOS menu-bar icon: a 36 px canvas shown at 18 points (2x), holding the cap about
# 30 px (15 points) wide. A first guess to tune on a real Mac next to its neighbours
# (Wi-Fi, battery): change MENU_GLYPH_WIDTH_PX and rebuild.
MENU_CANVAS_PX = 36
MENU_GLYPH_WIDTH_PX = 30
MENU_ALPHA_FLOOR = 32  # a pixel counts as part of the glyph above this alpha, for its bounding box

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
# (file name, pixel size) for the macOS iconset.
ICONSET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def squircle_mask(size, power=SQUIRCLE_POWER, supersample=4):
    """A white superellipse on black, `size` px square, anti-aliased by drawing it
    larger and shrinking it."""
    big = size * supersample
    half = big / 2
    points = []
    steps = 2000
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        x = math.copysign(abs(c) ** (2 / power), c)
        y = math.copysign(abs(s) ** (2 / power), s)
        points.append((half + x * (half - 1), half + y * (half - 1)))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def mac_master(source):
    """The 1024 px macOS icon: squircle art with a margin and a drop shadow."""
    art = source.convert("RGBA").resize((ART, ART), Image.LANCZOS)
    # Keep what the source already made transparent (its own rounded corners),
    # and cut everything outside the squircle too.
    alpha = ImageChops.multiply(art.getchannel("A"), squircle_mask(ART))
    art.putalpha(alpha)

    offset = (CANVAS - ART) // 2
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    shadow_alpha = Image.new("L", (CANVAS, CANVAS), 0)
    shadow_alpha.paste(alpha, (offset, offset + SHADOW_OFFSET_Y))
    shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    shadow_alpha = shadow_alpha.point(lambda v: int(v * SHADOW_OPACITY))
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    canvas = Image.alpha_composite(canvas, shadow)

    canvas.alpha_composite(art, (offset, offset))
    return canvas


def menu_template(source, canvas=MENU_CANVAS_PX, glyph_width=MENU_GLYPH_WIDTH_PX):
    """The macOS menu-bar icon as a "template" image: black pixels whose opacity is the
    cap's shape, on a transparent `canvas` px square. The system recolours a template to
    suit the menu bar (dark on a light bar, white on a dark one), so the source's white
    tile is dropped and only the dark cap is kept.

    The cap is dark on a white tile in the source, so its opacity is how dark a pixel is
    (inverted luminance), times the source's own alpha (its transparent corners are RGB
    black, which would otherwise count as dark). The bounding box is taken from that
    result, not from the raw pixels, for the same reason."""
    source = source.convert("RGBA")
    darkness = ImageChops.invert(source.convert("L"))
    shape = ImageChops.multiply(darkness, source.getchannel("A"))
    box = shape.point(lambda v: 255 if v > MENU_ALPHA_FLOOR else 0).getbbox()
    if box is None:
        raise ValueError("the source picture has no dark shape to make a menu-bar icon from")
    glyph = shape.crop(box)
    height = max(1, round(glyph.height * glyph_width / glyph.width))
    if height > canvas:  # a tall shape: fit its height instead, so it is never cut off
        glyph_width = max(1, round(glyph.width * canvas / glyph.height))
        height = canvas
    glyph = glyph.resize((glyph_width, height), Image.LANCZOS)

    alpha = Image.new("L", (canvas, canvas), 0)
    alpha.paste(glyph, ((canvas - glyph_width) // 2, (canvas - height) // 2))
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    image.putalpha(alpha)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", default=str(HERE / "icon-source.png"))
    parser.add_argument("--out", default=str(HERE / "build"))
    args = parser.parse_args()

    source = Image.open(args.source).convert("RGBA")
    if source.size != (CANVAS, CANVAS):
        raise SystemExit(f"{args.source} must be {CANVAS}x{CANVAS}, it is {source.width}x{source.height}.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Windows. Each size is resized by hand (Pillow's own ICO resize is blurrier).
    frames = [source.resize((n, n), Image.LANCZOS) for n in ICO_SIZES]
    frames[-1].save(out / "LitReview.ico", format="ICO", sizes=[(n, n) for n in ICO_SIZES], append_images=frames[:-1])

    source.resize((128, 128), Image.LANCZOS).save(out / "tray.png")
    menu_template(source).save(out / "trayTemplate.png")

    master = mac_master(source)
    master.save(out / "mac-preview.png")
    iconset = out / "LitReview.iconset"
    iconset.mkdir(exist_ok=True)
    for name, pixels in ICONSET:
        master.resize((pixels, pixels), Image.LANCZOS).save(iconset / name)

    print(f"Icons written to {out}")


if __name__ == "__main__":
    main()
