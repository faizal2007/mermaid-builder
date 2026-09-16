"""Draw ``src/diagram_maker/icon.ico``: a mermaid flowchart on a purple tile.

The icon is generated rather than hand-drawn so that all seven sizes stay in
step.  Every shape is described in a 0-1 coordinate space and rasterised per
size with analytic anti-aliasing, so the 16 px title-bar icon gets the same
treatment as the 256 px tile.  Nothing outside the standard library is needed,
which keeps the packaging extra down to PyInstaller alone.

It is written into the package because the window sets it at run time, and the
build embeds the same file in the .exe.

Usage::

    uv run python packaging/make_icon.py
    uv run python packaging/make_icon.py --preview build/icon-preview.png
"""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

#: the sizes Windows asks for, from the title bar up to the large tile
SIZES = (16, 24, 32, 48, 64, 128, 256)

#: 256 px goes in as PNG, the rest as BMP - what every other .ico on disk does
PNG_SIZES = (256,)

TILE_TOP = (0xA6, 0x87, 0xEA)
TILE_BOTTOM = (0x6B, 0x43, 0xBD)
INK = (0xFF, 0xFF, 0xFF)

#: the package owns the icon: the window loads it, the build copies it in
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "src" / "diagram_maker" / "icon.ico"

TILE_RADIUS = 0.225

#: centre x, centre y, half width, half height
NODES = (
    (0.50, 0.18, 0.17, 0.09),
    (0.24, 0.74, 0.17, 0.11),
    (0.76, 0.74, 0.17, 0.11),
)
NODE_RADIUS = 0.035

#: x0, y0, x1, y1 - each runs from the root node into a child node
BRANCHES = (
    (0.50, 0.27, 0.24, 0.70),
    (0.50, 0.27, 0.76, 0.70),
)
BRANCH_WIDTH = 0.05
ARROW_LENGTH = 0.13
ARROW_WIDTH = 0.072

#: how far above the child node the arrow stops, so the head reads as a head
ARROW_GAP = 0.03

Point = tuple[float, float]
Distance = Callable[[float, float], float]
Op = tuple[Distance, tuple[int, int, int], float]


# --------------------------------------------------------------- distances #


def _rounded_box(cx: float, cy: float, hw: float, hh: float, radius: float) -> Distance:
    """Signed distance to a rounded rectangle, negative inside."""

    def distance(x: float, y: float) -> float:
        qx = abs(x - cx) - (hw - radius)
        qy = abs(y - cy) - (hh - radius)
        outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
        return outside + min(max(qx, qy), 0.0) - radius

    return distance


def _capsule(x0: float, y0: float, x1: float, y1: float, half: float) -> Distance:
    """Signed distance to a line with round caps, negative inside."""
    dx, dy = x1 - x0, y1 - y0
    length_squared = dx * dx + dy * dy

    def distance(x: float, y: float) -> float:
        t = ((x - x0) * dx + (y - y0) * dy) / length_squared
        t = min(max(t, 0.0), 1.0)
        return math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)) - half

    return distance


def _polygon(points: list[Point]) -> Distance:
    """Signed distance to a convex polygon, negative inside."""
    middle = (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )
    edges: list[tuple[float, float, float, float]] = []
    for index, (ax, ay) in enumerate(points):
        bx, by = points[(index + 1) % len(points)]
        ex, ey = bx - ax, by - ay
        span = math.hypot(ex, ey) or 1.0
        nx, ny = -ey / span, ex / span
        # whichever way the points were wound, aim each normal at the middle
        if nx * (middle[0] - ax) + ny * (middle[1] - ay) < 0.0:
            nx, ny = -nx, -ny
        edges.append((ax, ay, nx, ny))

    def distance(x: float, y: float) -> float:
        # inside means every half-plane agrees, so the nearest one wins
        return -min(nx * (x - ax) + ny * (y - ay) for ax, ay, nx, ny in edges)

    return distance


# ------------------------------------------------------------------ shapes #


def _arrow(tip: Point, direction: Point, length: float, width: float) -> list[Point]:
    """A triangle with its point at ``tip``, opening back along ``direction``."""
    ux, uy = direction
    base = (tip[0] - ux * length, tip[1] - uy * length)
    px, py = -uy * width, ux * width
    return [tip, (base[0] + px, base[1] + py), (base[0] - px, base[1] - py)]


def _crossing(branch: tuple[float, float, float, float], reach: float, size: int) -> Point:
    """Where a branch meets the height ``reach``, in pixels."""
    x0, y0, x1, y1 = branch
    travel = (reach - y0) / (y1 - y0)
    return ((x0 + travel * (x1 - x0)) * size, reach * size)


def _ops(size: int) -> list[Op]:
    """The ink to lay over the tile, geometry scaled from 0-1 to ``size`` px."""
    ops: list[Op] = []
    for index, branch in enumerate(BRANCHES):
        x0, y0, x1, y1 = branch
        node_top = NODES[index + 1][1] - NODES[index + 1][3]
        span = math.hypot(x1 - x0, y1 - y0)
        ops.append(
            (
                # the line runs under the node, so the join never shows
                _capsule(
                    x0 * size,
                    y0 * size,
                    *_crossing(branch, node_top + 0.07, size),
                    BRANCH_WIDTH * size / 2,
                ),
                INK,
                1.0,
            )
        )
        ops.append(
            (
                _polygon(
                    _arrow(
                        _crossing(branch, node_top - ARROW_GAP, size),
                        ((x1 - x0) / span, (y1 - y0) / span),
                        ARROW_LENGTH * size,
                        ARROW_WIDTH * size,
                    )
                ),
                INK,
                1.0,
            )
        )
    for cx, cy, hw, hh in NODES:
        ops.append(
            (
                _rounded_box(
                    cx * size, cy * size, hw * size, hh * size, NODE_RADIUS * size
                ),
                INK,
                1.0,
            )
        )
    return ops


# ------------------------------------------------------------------- paint #


def _blend(
    line: bytearray, offset: int, rgb: tuple[int, int, int], alpha: float
) -> None:
    """Composite one pixel (straight alpha, source over) into an RGBA line."""
    if alpha <= 0.0:
        return
    existing = line[offset + 3] / 255.0
    out = alpha + existing * (1.0 - alpha)
    if out <= 0.0:
        return
    # how much of the pixel the colour already there still owns
    under = existing * (1.0 - alpha) / out
    for channel in range(3):
        mixed = rgb[channel] * (1.0 - under) + line[offset + channel] * under
        line[offset + channel] = min(255, round(mixed))
    line[offset + 3] = min(255, round(out * 255))


def render(size: int) -> bytes:
    """Return ``size * size`` RGBA pixels for the icon."""
    line = bytearray(size * 4)
    pixels = bytearray()
    paint = _ops(size)
    tile = _rounded_box(size / 2, size / 2, size / 2, size / 2, TILE_RADIUS * size)
    for y in range(size):
        line[:] = b"\0" * (size * 4)
        for x in range(size):
            centre = (x + 0.5, y + 0.5)
            # a one-pixel band around every edge is the whole anti-aliasing story
            covered = min(max(0.5 - tile(*centre), 0.0), 1.0)
            if covered > 0.0:
                # the tile is a vertical gradient, so it stops looking flat at 256
                mix = y / max(size - 1, 1)
                tile_rgb = tuple(
                    round(TILE_TOP[i] + (TILE_BOTTOM[i] - TILE_TOP[i]) * mix)
                    for i in range(3)
                )
                _blend(line, x * 4, tile_rgb, covered)
            for distance, rgb, alpha in paint:
                coverage = min(max(0.5 - distance(*centre), 0.0), 1.0) * alpha
                if coverage > 0.0:
                    _blend(line, x * 4, rgb, coverage)
        pixels += line
    return bytes(pixels)


# ------------------------------------------------------------ icon writing #


def _png(size: int, pixels: bytes) -> bytes:
    """Wrap RGBA pixels in a PNG container."""
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # filter: none
        raw += pixels[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    body = zlib.compress(bytes(raw), 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", body)
        + chunk(b"IEND", b"")
    )


def _bmp(size: int, pixels: bytes) -> bytes:
    """Wrap RGBA pixels in the DIB an .ico holds below 256 px."""
    header = struct.pack(
        "<IiiHHIIiiII",
        40,  # header size
        size,  # width
        size * 2,  # height: XOR image plus AND mask
        1,  # planes
        32,  # bits per pixel
        0,  # compression: BI_RGB
        size * size * 4,
        0,
        0,
        0,
        0,
    )
    body = bytearray()
    stride = size * 4
    for y in range(size - 1, -1, -1):  # DIB rows run bottom-up
        row = pixels[y * stride : (y + 1) * stride]
        bgra = bytearray(stride)
        bgra[0::4] = row[2::4]
        bgra[1::4] = row[1::4]
        bgra[2::4] = row[0::4]
        bgra[3::4] = row[3::4]
        body += bgra
    # the AND mask is unused at 32 bpp, but every reader expects its bytes
    body += bytes(((size + 31) // 32) * 4 * size)
    return header + bytes(body)


def write_ico(path: Path, sizes: tuple[int, ...] = SIZES) -> None:
    """Render ``sizes`` and write them out as one icon file."""
    images = [
        (size, _png(size, render(size)) if size in PNG_SIZES else _bmp(size, render(size)))
        for size in sizes
    ]
    offset = 6 + 16 * len(images)
    directory = bytearray()
    blob = bytearray()
    for size, data in images:
        directory += struct.pack(
            "<BBBBHHII",
            size % 256,  # 256 is stored as 0
            size % 256,
            0,  # colours in palette
            0,  # reserved
            1,  # planes
            32,  # bits per pixel
            len(data),
            offset,
        )
        blob += data
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + bytes(directory) + bytes(blob))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="icon file to write (default: src/diagram_maker/icon.ico)",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        help="also write the 256 px tile as a PNG, for eyeballing",
    )
    arguments = parser.parse_args()

    write_ico(arguments.out)
    print(f"wrote {arguments.out} ({arguments.out.stat().st_size:,} bytes)")
    if arguments.preview:
        arguments.preview.parent.mkdir(parents=True, exist_ok=True)
        arguments.preview.write_bytes(_png(256, render(256)))
        print(f"wrote {arguments.preview}")


if __name__ == "__main__":
    main()
