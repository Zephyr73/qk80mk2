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

from .constants import (
    MATRIX_COLS,
    MATRIX_ROWS,
    PRODUCT_ID,
    VENDOR_ID,
)
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


def sync_time(when=None) -> None:
    """Sync the on-screen clock to the host (Config -> Date and Time -> time sync).

    The keyboard's clock has no timezone handling, so this sends the local
    wall-clock read of ``when`` and persists it (survives power cycles), using
    the same bytes as the configurator's Time Sync button. ``when`` is
    optional: ``None`` = the host's current local time; a ``datetime`` = that
    wall-clock moment (naive = local); a number = UTC epoch seconds. See
    :meth:`qk80.transport.HIDTransport.sync_time` for details.
    """
    with HIDTransport() as t:
        t.sync_time(when)


def parse_sleep_mode(value) -> int:
    """Map a human sleep-mode value to its firmware index (0-6).

    Accepts an index (``0``-``6``), an exact duration (``"5min"``,
    ``"15 minutes"``, ``"1h"``, ``"3 hours"``, ``"6h"``), or ``"disable"`` /
    ``"off"``. Returns the index used by :func:`set_sleep_mode` and
    :data:`qk80.constants.SLEEP_MODES`; raises ``ValueError`` for anything
    else.
    """
    import re

    if isinstance(value, bool):
        raise ValueError("sleep mode must be an index or duration, not a bool")
    if isinstance(value, int):
        n = value
    else:
        s = str(value).strip().lower()
        if s in ("disable", "disabled", "off", "never", "none"):
            n = 0
        else:
            m = re.fullmatch(r"(\d+)\s*(min(?:ute)?s?|m|h(?:ours?)?)?", s)
            if not m:
                raise ValueError(
                    f"unknown sleep mode {value!r}; use an index 0-6, a duration "
                    f"like '5min'/'1h'/'3 hours', or 'disable'")
            minutes = int(m.group(1))
            if m.group(2) and m.group(2).startswith("h"):
                minutes *= 60
            n = {0: 0, 5: 1, 15: 2, 30: 3, 60: 4, 180: 5, 360: 6}.get(minutes)
            if n is None:
                raise ValueError(
                    f"sleep mode {value!r} is not a supported duration; choose "
                    f"5/15/30 minutes, 1/3/6 hours, or 'disable'")
    if not 0 <= n <= 6:
        raise ValueError(f"sleep mode index must be 0-6, got {value!r}")
    return n


def set_light_power(on: bool, port: str | None = None) -> None:
    """Turn all LED power on/off (Config -> Features -> Light Power).

    Mirrors the configurator's Light Power toggle (HID, persists across power
    cycles). ``on`` is truthy for on, falsy for off.
    """
    with HIDTransport() as t:
        t.set_light_power(bool(on))


def get_light_power(port: str | None = None) -> bool:
    """Read the current LED power state (Config -> Features -> Light Power)."""
    with HIDTransport() as t:
        return t.get_light_power()


def set_sleep_mode(mode, port: str | None = None) -> None:
    """Set the sleep-mode timer (Config -> Features -> Sleep Mode).

    ``mode`` is passed to :func:`parse_sleep_mode` - an index ``0``-``6``, a
    duration (``"5min"``, ``"30 minutes"``, ``"1h"``, ``"3 hours"``), or
    ``"disable"``. Sent the same way as the configurator's dropdown (HID,
    persists across power cycles).
    """
    with HIDTransport() as t:
        t.set_sleep_mode(parse_sleep_mode(mode))


def get_sleep_mode(port: str | None = None) -> int:
    """Read the current sleep-mode index (0-6, see SLEEP_MODES)."""
    with HIDTransport() as t:
        return t.get_sleep_mode()


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
