"""7x7 matrix-LED helpers: named colors, manual patterns, HSV conversion.

Builds the HSV upload payloads for the Custom matrix zone (see
:func:`qk80.encoders.matrix_hsv_data`). Also owns the color-name table and
color parsing shared by the high-level helpers and the CLI.
"""

from __future__ import annotations

from typing import Sequence

from PIL import Image

from .constants import MATRIX_COLS, MATRIX_ROWS
from .encoders import matrix_hsv_data


MATRIX_COLORS = {
    "red":     (255, 0, 0),
    "orange":  (255, 165, 0),
    "yellow":  (255, 255, 0),
    "green":   (0, 255, 0),
    "cyan":    (0, 255, 255),
    "blue":    (0, 0, 255),
    "magenta": (255, 0, 255),
    "purple":  (128, 0, 255),
    "white":   (255, 255, 255),
    "off":     (0, 0, 0),
}

MATRIX_COLOR_NAMES = ", ".join(MATRIX_COLORS)

# Firmware quirk (measured): the matrix LED mode color is stored on a coarse
# ~30-degree hue wheel and any other hue byte is snapped UP to the next wheel
# step on readback. Every named color in MATRIX_COLORS except cyan is already
# an exact wheel step, so pre-compensating the hue keeps what-you-set equal to
# what-shows (cyan 128 would otherwise snap to 149 and look blue).
MATRIX_HUE_STEPS = (0, 21, 42, 64, 85, 106, 127, 149, 170, 192, 213, 234)


def _hue_to_stored(h: int) -> int:
    """Map a desired hue byte to the value the firmware stores faithfully."""
    if h > MATRIX_HUE_STEPS[-1]:
        return h  # above the wheel the firmware passes the byte through
    return min(MATRIX_HUE_STEPS, key=lambda s: abs(s - h))


def _matrix_frame_to_hsv(frame: Image.Image) -> bytes:
    """One rows*cols RGB frame -> HSV upload bytes (all LEDs same size check)."""
    return matrix_hsv_data([frame], MATRIX_ROWS, MATRIX_COLS)


def matrix_solid_hsv(color: str) -> bytes:
    """Primary color name -> one 7x7 frame of HSV upload bytes.

    Sets all 49 LEDs of the Custom matrix pattern to the same color.
    """
    rgb = MATRIX_COLORS[color]
    frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS), rgb)
    return _matrix_frame_to_hsv(frame)


def matrix_blank_hsv() -> bytes:
    """One 7x7 frame with every LED off (the factory default Custom pattern)."""
    return matrix_solid_hsv("off")


def matrix_pattern_rgb(pattern: Sequence[str], color: str) -> list[tuple]:
    """Manual 7x7 Custom pattern -> list of 49 RGB pixels.

    ``pattern`` must be exactly 7 strings of 7 characters each (one per row,
    left to right). ``'.'`` leaves that LED off (black); any other character
    turns it on in ``color``.
    """
    if len(pattern) != MATRIX_ROWS or any(len(r) != MATRIX_COLS for r in pattern):
        raise ValueError(f"pattern must be {MATRIX_ROWS} rows of {MATRIX_COLS} "
                         f"characters, got {pattern!r}")
    rgb = MATRIX_COLORS[color]
    return [(rgb if ch != "." else (0, 0, 0)) for row in pattern for ch in row]


def matrix_pattern_hsv(pattern: Sequence[str], color: str) -> bytes:
    """Manual 7x7 Custom pattern -> HSV upload bytes. See :func:`matrix_pattern_rgb`."""
    pixels = matrix_pattern_rgb(pattern, color)
    frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS))
    frame.putdata(pixels)
    return _matrix_frame_to_hsv(frame)


def parse_color(spec: Sequence[str]) -> tuple:
    """Parse a color spec into ``(r, g, b)`` 0-255.

    Accepts a single ``MATRIX_COLORS`` name (``'cyan'``), ``'#rrggbb'``, or
    three channel values (``['255', '0', '0']``).
    """
    spec = list(spec)
    if len(spec) == 1:
        s = spec[0].strip().lower()
        if s in MATRIX_COLORS:
            return MATRIX_COLORS[s]
        if s.startswith("#") and len(s) == 7:
            try:
                r, g, b = (int(s[i:i + 2], 16) for i in (1, 3, 5))
                return (r, g, b)
            except ValueError:
                raise ValueError(f"invalid hex color {spec[0]!r}") from None
    if len(spec) == 3:
        try:
            r, g, b = (int(x) for x in spec)
        except ValueError:
            raise ValueError(f"invalid color {list(spec)!r}") from None
        if all(0 <= x <= 255 for x in (r, g, b)):
            return (r, g, b)
    raise ValueError(f"invalid color {list(spec)!r}; use a name from "
                     f"{MATRIX_COLOR_NAMES}, '#rrggbb', or 'r g b'")
