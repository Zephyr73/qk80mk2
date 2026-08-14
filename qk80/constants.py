"""Device identity, geometry, and wire-protocol constants.

Single source of truth for the QK80 MK2 protocol: device IDs, screen/matrix
geometry, transport chunk sizes, and the command bytes defined in PROTOCOL.md.
Import from ``qk80.constants`` or re-exported from the top-level ``qk80``
package.
"""

from __future__ import annotations

import os


def _env_int_hex(name: str, default: int) -> int:
    """Read a hex-or-decimal int from an env var, else return ``default``.

    Lets a fork target another board without editing this file, e.g.
    ``QK80_VID=0x514B`` / ``QK80_PID=0x4D02``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw, 0)
    except ValueError:
        raise RuntimeError(f"invalid {name} environment variable {raw!r}; "
                           f"use hex like 0x514B or decimal") from None


# Device identity. Override with the QK80_VID / QK80_PID / QK80_NAME
# environment variables (e.g. QK80_VID=0x514B) or edit here for a fork.
VENDOR_ID = _env_int_hex("QK80_VID", 0x514B)
PRODUCT_ID = _env_int_hex("QK80_PID", 0x4D02)
DEVICE_NAME = os.environ.get("QK80_NAME", "QK80 MK2")
VIA_USAGE_PAGE = 0xFF60

SCREEN_W = 320
SCREEN_H = 172

MATRIX_ROWS = 7
MATRIX_COLS = 7

# Slider transition animations (ANPS/ANPT), same enum as the configurator
ANIM_TRANS_NONE = 1
ANIM_TRANS_DOWN = 2
ANIM_TRANS_UP = 3
ANIM_TRANS_RIGHT = 4
ANIM_TRANS_LEFT = 5

BAUD = 115200
CDC_BUFFER_SIZE = 64
CDC_CHUNK = CDC_BUFFER_SIZE - 8

HID_REPORT = 33  # report id (0) + 32 payload
HID_CHUNK = HID_REPORT - 8

# CDC commands
CDC_MATRIX_INFO = 0xC0
CDC_MATRIX_BUFFER = 0xC1
CDC_FILE_INFO = 0xE0
CDC_FILE_BUFFER = 0xE1
CDC_FILE_CANCEL = 0xE2

# HID commands
HID_TAB_BLOCKS = 0xD1
HID_BLOCK_FILE_INFO = 0x20
HID_BLOCK_FILE_BUFFER = 0x21
HID_BLOCK_FILE_CANCEL = 0x22
HID_BLOCK_MATRIX_INFO = 0x30
HID_BLOCK_MATRIX_BUFFER = 0x31

# VIA Lighting -> MATRIX LED values (HID custom-value subsystem, the same
# commands the configurator sends for the Brightness/Effect/Color sliders)
HID_CUSTOM_SET = 0x07
HID_CUSTOM_GET = 0x08
HID_CUSTOM_SAVE = 0x09
MATRIX_LED_CHANNEL = 26
MATRIX_LED_VALUE_BRIGHTNESS = 1
MATRIX_LED_VALUE_EFFECT = 2
MATRIX_LED_VALUE_COLOR = 4
MATRIX_LED_EFFECTS = ("off", "typewriter", "terminal", "raindrop", "custom")

ERR_FLAG = 0xEE
