"""High-level convenience functions for library users.

The friendly layer on top of the encoders and transports: one-call uploads,
matrix-LED color/effect/brightness setters, and device discovery. The
recommended entry point is :func:`upload`:

    import qk80

    data = qk80.encode_image(Image.open("photo.png"))
    qk80.upload(data)
"""

from __future__ import annotations

from typing import Callable, Sequence

from PIL import Image

from .constants import MATRIX_COLS, MATRIX_ROWS, PRODUCT_ID, VENDOR_ID
from .encoders import rgb_to_hsv256
from .matrix import (
    MATRIX_COLOR_NAMES,
    MATRIX_COLORS,
    _matrix_frame_to_hsv,
    matrix_blank_hsv,
    matrix_pattern_hsv,
    parse_color,
)
from .transport import CDCTransport, HIDTransport, Progress


def upload(data: bytes, transport: str = "cdc", port: str | None = None,
           progress_cb: Callable[[int, int], None] | None = None) -> None:
    """Open the transport, upload a tab file, and close it.

    The recommended entry point for library users:

        data = qk80.encode_image(Image.open("photo.png"))
        qk80.upload(data)

    Ctrl+C is safe: the keyboard is sent a cancel command before the port is
    released, so an interrupted upload never leaves the device stuck.
    """
    with CDCTransport(port) if transport == "cdc" else HIDTransport() as t:
        prog = Progress(callback=progress_cb) if progress_cb else None
        if prog:
            prog.total = len(data)
        t.set_tab_file(data, prog)


def set_matrix_color(color: str, port: str | None = None) -> None:
    """Set the Letters / Typewriter / Rain mode color (HID, persists).

    This is the configurator's Lighting -> MATRIX LED -> Color picker. It does
    NOT touch the Custom grid - fill that separately with
    :func:`set_matrix_custom`. ``color`` is a :data:`qk80.matrix.MATRIX_COLORS`
    name, ``'#rrggbb'``, or ``'r g b'``.
    """
    rgb = parse_color([color])
    h, s, _v = rgb_to_hsv256(*rgb)
    with HIDTransport() as t:
        t.set_matrix_led(color=(h, s))


def set_matrix_custom(color: str, transport: str = "cdc",
                      port: str | None = None) -> None:
    """Fill only the 7x7 Custom grid solid with ``color``.

    Does not touch the Letters / Typewriter / Rain mode color or effect.
    ``color`` is a :data:`qk80.matrix.MATRIX_COLORS` name, ``'#rrggbb'``, or
    ``'r g b'``. Ctrl+C is safe.
    """
    rgb = parse_color([color])
    frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS), rgb)
    data = _matrix_frame_to_hsv(frame)
    with CDCTransport(port) if transport == "cdc" else HIDTransport() as t:
        t.set_matrix_lighting(1, 1, MATRIX_ROWS, MATRIX_COLS, data)


def set_matrix_pattern(pattern: Sequence[str], color: str, transport: str = "cdc",
                       port: str | None = None) -> None:
    """Draw a manual 7x7 pattern on the Custom matrix mode only.

    Does not touch the Letters / Typewriter / Rain mode color or effect.
    ``pattern`` is 7 strings of 7 characters; ``'.'`` = LED off, any other
    character = LED on in ``color`` (a :data:`qk80.matrix.MATRIX_COLORS`
    name). Example (a heart):

        qk80.set_matrix_pattern(
            ["...", ...],  # 7 rows
            "red")

    Image/video uploads to the matrix are intentionally not supported.
    Ctrl+C is safe.
    """
    if color not in MATRIX_COLORS:
        raise ValueError(f"unknown matrix color {color!r}; choose from "
                         f"{MATRIX_COLOR_NAMES}")
    data = matrix_pattern_hsv(pattern, color)
    with CDCTransport(port) if transport == "cdc" else HIDTransport() as t:
        t.set_matrix_lighting(1, 1, MATRIX_ROWS, MATRIX_COLS, data)


def reset_matrix(transport: str = "cdc", port: str | None = None) -> None:
    """Restore the Custom matrix mode to its factory default (all LEDs off)."""
    data = matrix_blank_hsv()
    with CDCTransport(port) if transport == "cdc" else HIDTransport() as t:
        t.set_matrix_lighting(1, 1, MATRIX_ROWS, MATRIX_COLS, data)


def set_matrix_brightness(percent: int, port: str | None = None) -> None:
    """Set the matrix LED brightness as a percentage, 1-100 (HID, persists).

    Applies to every matrix mode (the firmware scales the whole matrix LED
    driver). The 0-255 value actually sent is ``round(percent * 255 / 100)``.
    Note the firmware clamps values below ~16% to a hardware floor.
    """
    percent = int(percent)
    if not 1 <= percent <= 100:
        raise ValueError("matrix LED brightness must be 1-100%")
    value = round(percent * 255 / 100)
    with HIDTransport() as t:
        t.set_matrix_led(brightness=value)


def set_matrix_effect(name: str, port: str | None = None) -> None:
    """Switch the matrix mode: off / typewriter / terminal / raindrop / custom."""
    with HIDTransport() as t:
        t.set_matrix_led(effect=name)


def get_matrix_led(port: str | None = None) -> dict:
    """Read the current matrix LED values (brightness, effect, color).

    Returns ``{"brightness": 0-255, "effect": int, "effect_name": str,
    "color": (hue, sat)}`` where ``color`` is the raw (hue, sat) the firmware
    stores (use :func:`qk80.encoders.hsv256_to_rgb` to display it as RGB).
    """
    with HIDTransport() as t:
        return t.get_matrix_led()


def probe_devices() -> dict:
    """Enumerate connected devices over CDC (serial) and HID.

    Returns ``{"cdc": [...], "hid": [...]}`` for anything matching
    :data:`qk80.constants.VENDOR_ID` / ``PRODUCT_ID``, so callers can confirm
    the device is present and decide which transport to use. Both lists are
    empty when the keyboard is not connected.
    """
    from serial.tools import list_ports

    cdc = []
    try:
        for p in list_ports.comports():
            if getattr(p, "vid", None) == VENDOR_ID and getattr(p, "pid", None) == PRODUCT_ID:
                cdc.append({
                    "port": p.device,
                    "product": getattr(p, "product", None),
                    "manufacturer": getattr(p, "manufacturer", None),
                })
    except Exception:
        pass

    hid_devices = []
    try:
        import hid
        for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
            hid_devices.append({
                "path": d.get("path"),
                "usage_page": d.get("usage_page"),
                "usage": d.get("usage"),
            })
    except Exception:
        pass

    return {"cdc": cdc, "hid": hid_devices}
