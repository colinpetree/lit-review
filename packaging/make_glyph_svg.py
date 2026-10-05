"""Write the graduation cap as two small SVG files for the macOS 26 "Liquid Glass" icon.

    pip install shapely svgelements numpy      (tools for this script only, not app requirements)
    python packaging/make_glyph_svg.py         (writes packaging/macos/glyph-*.svg)

The files are committed, because the icon is drawn on a Mac in Apple's free Icon Composer
app (a layered `.icon` package: a background fill and this cap as the foreground layer),
which has no build output to hand. `glyph-black.svg` is the cap for the default look and
`glyph-white.svg` for the dark one.

**The cap is a filled shape, not strokes.** Lucide draws its icons as 2 unit wide strokes
with no fill. Icon Composer's per-layer "Fill" colour fills a layer's shapes, so on a
stroke-only drawing it flooded the cap's inside and the cap stopped looking like a cap.
Here each stroke is turned into the outline of the area it covers (a buffer of half the
stroke width, with round ends and joins, exactly what a round-capped stroke paints), the
pieces are merged, and the result is one shape with holes (`fill-rule="evenodd"`), so any
fill colour paints just the cap.

The shape is Lucide's `graduation-cap` (ISC license, the same icon as the logo and listed in
THIRD_PARTY_NOTICES.txt), at the 24 unit size it is drawn in. The viewBox adds padding so
the cap fills about two thirds of the square, leaving room for the system's shapes and
shadows; scale it in Icon Composer if it needs to be larger or smaller.
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent / "macos"

PATHS = [
    "M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z",
    "M22 10v6",
    "M6 12.5V16a6 3 0 0 0 12 0v-3.5",
]
STROKE_WIDTH = 2.0  # Lucide's default
STEP = 0.02  # how far apart, in units, the points of a flattened curve are
DECIMALS = 3

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="-6 -6 36 36">
  <path fill="{color}" fill-rule="evenodd" d="{d}"/>
</svg>
"""


def flatten(path_data):
    """The path as a list of point lists, one per subpath, curves flattened to short lines."""
    import numpy
    from svgelements import Move, Path

    subpaths = []
    for subpath in Path(path_data).as_subpaths():
        points = []
        for segment in subpath:
            if isinstance(segment, Move):
                points.append((float(segment.end.x), float(segment.end.y)))
                continue
            steps = max(2, int(float(segment.length()) / STEP))
            for t in numpy.linspace(0, 1, steps + 1)[1:]:
                point = segment.npoint([t])[0]
                points.append((float(point[0]), float(point[1])))
        subpaths.append(points)
    return subpaths


def outline():
    """One shape (a shapely geometry) covering everything the three strokes paint."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    pieces = []
    for data in PATHS:
        for points in flatten(data):
            pieces.append(LineString(points).buffer(STROKE_WIDTH / 2, quad_segs=24, cap_style="round", join_style="round"))
    return unary_union(pieces).simplify(0.002)


def path_data(shape):
    """SVG path data for a shapely (multi)polygon: every ring as a closed subpath."""
    polygons = list(shape.geoms) if hasattr(shape, "geoms") else [shape]
    parts = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            points = [f"{x:.{DECIMALS}f} {y:.{DECIMALS}f}" for x, y in list(ring.coords)[:-1]]
            parts.append("M" + " L".join(points) + " Z")
    return " ".join(parts)


def svg(color, d):
    return TEMPLATE.format(color=color, d=d)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = path_data(outline())
    for name, color in (("glyph-black.svg", "#000000"), ("glyph-white.svg", "#FFFFFF")):
        (OUT / name).write_text(svg(color, d), encoding="utf-8", newline="\n")
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
