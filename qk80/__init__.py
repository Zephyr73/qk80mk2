"""qk80 - QK80 MK2 / tabkb LCD + Matrix LED protocol library.

Reverse-engineered from cfg.qwertykeys.com (deployed bundle) and the
open-source configurator (github.com/tabkb/cc). See PROTOCOL.md.

Formats (all verified byte-for-byte against the official kbres.wasm output):
  * ABKG (LCD image): 20-byte header + 320x172 raw RGB565, row-major
  * ANIM (LCD animation): 36(+2N)-byte header + N raw RGB565 frames
  * ANPS/ANPT (LCD slider): 24-byte header + N raw RGB565 frames
  * tabml (Matrix LED file): 32-byte header + raw RGB888 per LED per frame
  * Matrix LED upload data: HSV bytes per LED per frame (not RGB)

Transports:
  * CDC (USB serial @115200, 64-byte packets)  - QK80 MK2 uses this
      file:      [0xE0, first20] then [0xE1, off(4BE), len, chunk<=56], cancel [0xE2]
      matrix:    [0xC0, frames,fps,rows,cols] then [0xC1, off(4BE), len, chunk<=56]
  * HID (VIA raw endpoint 0xFF60, 33-byte packets) - fallback / older firmwares
      file:      [0xD1,0x20,first20] then [0xD1,0x21,off(4BE),len,chunk<=25], cancel [0xD1,0x22]
      matrix:    [0xD1,0x30,frames,fps,rows,cols] then [0xD1,0x31,off(4BE),len,chunk<=25]
      lighting:  [0x07/0x08/0x09, 26, value, ...] - matrix-LED brightness/effect/color

Modules:
  qk80.constants  - device identity + wire-protocol constants
  qk80.encoders   - pure byte-format encoders (images/animations/sliders/matrix)
  qk80.matrix     - 7x7 matrix-LED helpers (colors, patterns, HSV conversion)
  qk80.transport  - CDC + HID USB transports and transfer progress
  qk80.api        - high-level convenience functions
  qk80.cli        - command-line interface (``python -m qk80``)

The public API (constants, encoders, matrix helpers, transports, high-level
functions and ``main()``) is re-exported here, so ``import qk80`` behaves
exactly like the previous single-file ``qk80.py`` module.
"""

from __future__ import annotations

from .api import (
    get_matrix_led,
    probe_devices,
    reset_matrix,
    set_matrix_brightness,
    set_matrix_color,
    set_matrix_custom,
    set_matrix_effect,
    set_matrix_pattern,
    upload,
)
from .cli import main
from .constants import (
    ANIM_TRANS_DOWN,
    ANIM_TRANS_LEFT,
    ANIM_TRANS_NONE,
    ANIM_TRANS_RIGHT,
    ANIM_TRANS_UP,
    BAUD,
    CDC_BUFFER_SIZE,
    CDC_CHUNK,
    CDC_FILE_BUFFER,
    CDC_FILE_CANCEL,
    CDC_FILE_INFO,
    CDC_MATRIX_BUFFER,
    CDC_MATRIX_INFO,
    DEVICE_NAME,
    ERR_FLAG,
    HID_BLOCK_FILE_BUFFER,
    HID_BLOCK_FILE_CANCEL,
    HID_BLOCK_FILE_INFO,
    HID_BLOCK_MATRIX_BUFFER,
    HID_BLOCK_MATRIX_INFO,
    HID_CHUNK,
    HID_CUSTOM_GET,
    HID_CUSTOM_SAVE,
    HID_CUSTOM_SET,
    HID_REPORT,
    HID_TAB_BLOCKS,
    MATRIX_COLS,
    MATRIX_LED_CHANNEL,
    MATRIX_LED_EFFECTS,
    MATRIX_LED_VALUE_BRIGHTNESS,
    MATRIX_LED_VALUE_COLOR,
    MATRIX_LED_VALUE_EFFECT,
    MATRIX_ROWS,
    PRODUCT_ID,
    SCREEN_H,
    SCREEN_W,
    VENDOR_ID,
    VIA_USAGE_PAGE,
)
from .encoders import (
    album_to_slider,
    encode_image,
    encode_slider,
    encode_tabml,
    encode_video,
    gif_to_video,
    hsv256_to_rgb,
    matrix_hsv_data,
    resize_cover,
    rgb_to_hsv256,
    to_rgb565,
)
from .matrix import (
    MATRIX_COLOR_NAMES,
    MATRIX_COLORS,
    MATRIX_HUE_STEPS,
    matrix_blank_hsv,
    matrix_pattern_hsv,
    matrix_pattern_rgb,
    matrix_solid_hsv,
    parse_color,
)
from .transport import CDCTransport, HIDTransport, Progress, be32
