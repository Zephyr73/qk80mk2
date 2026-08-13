"""
qk80.py - QK80 MK2 / tabkb LCD + Matrix LED protocol library.

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
"""

from __future__ import annotations

import colorsys
import struct
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Union

from PIL import Image

VENDOR_ID = 0x514B
PRODUCT_ID = 0x4D02

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
CDC_CHUNK = CDC_BUFFER_SIZE - 8  # 56

HID_REPORT = 33  # report id (0) + 32 payload
HID_CHUNK = 25

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


# --------------------------------------------------------------------------
# Encoders
# --------------------------------------------------------------------------

def to_rgb565(img: Image.Image) -> bytes:
    """PIL RGB image -> raw RGB565 bytes (r>>3, g>>2, b>>3), row-major."""
    raw = img.convert("RGB").tobytes()
    out = bytearray(len(raw) // 3 * 2)
    j = 0
    for i in range(0, len(raw), 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out[j] = v & 0xFF
        out[j + 1] = v >> 8
        j += 2
    return bytes(out)


def resize_cover(img: Image.Image, width: int = SCREEN_W, height: int = SCREEN_H) -> Image.Image:
    """Scale to cover width x height then center-crop (fills the full frame)."""
    img = img.convert("RGB")
    src_w, src_h = img.size
    scale = max(width / src_w, height / src_h)
    img = img.resize(
        (max(width, round(src_w * scale)), max(height, round(src_h * scale))),
        Image.LANCZOS,
    )
    x = (img.width - width) // 2
    y = (img.height - height) // 2
    return img.crop((x, y, x + width, y + height))


def encode_image(img: Image.Image, magic: bytes = b"ABKT") -> bytes:
    """PIL image -> ABKT/ABKG bytes (20-byte header + raw RGB565).

    ABKT = "Theme" image (default, lands on Themes -> Default Theme),
    ABKG = "Custom Image" (Apps -> Custom Animation). Identical layout; only
    the 4-byte magic differs (the firmware routes the two to different
    screens).
    """
    img = resize_cover(img)
    pixels = to_rgb565(img)
    return (
        magic
        + struct.pack("<H", 20)          # 4:  header start
        + struct.pack("<H", 20)          # 6:  header size
        + struct.pack("<I", 20 + len(pixels))  # 8: total file size
        + struct.pack("<H", img.width)   # 12: width
        + struct.pack("<H", img.height)  # 14: height
        + struct.pack("<H", 0)           # 16
        + struct.pack("<H", 1)           # 18: frame count (1)
        + pixels
    )


def encode_video(frames: List[Image.Image], durations_ms: List[int],
                 magic: bytes = b"ANIT") -> bytes:
    """PIL frames + durations (ms) -> ANIT/ANIM bytes (header + RGB565 frames).

    ANIT = "Theme" video (default, lands on Themes -> Default Theme),
    ANIM = "Custom Animation" (Apps). Identical layout; only the 4-byte magic
    differs (the firmware routes the two to different screens).
    """
    if not frames:
        raise ValueError("no frames")
    assert len(frames) == len(durations_ms), "frames/durations length mismatch"
    n = len(frames)
    encoded = [to_rgb565(resize_cover(f)) for f in frames]  # encode once
    header_size = 20 + 2 * n
    header = (
        magic
        + struct.pack("<H", 20)
        + struct.pack("<H", header_size)
        + struct.pack("<I", header_size + sum(len(b) for b in encoded))
        + struct.pack("<H", SCREEN_W)
        + struct.pack("<H", SCREEN_H)
        + struct.pack("<H", 0)
        + struct.pack("<H", n)
    )
    durations = b"".join(struct.pack("<H", d) for d in durations_ms)
    return header + durations + b"".join(encoded)


def gif_to_video(gif: Image.Image, max_frames: int = 500, magic: bytes = b"ANIT") -> bytes:
    """Open an animated GIF and encode it as ANIT/ANIM."""
    frames: List[Image.Image] = []
    durations: List[int] = []
    try:
        n = gif.n_frames
    except Exception:
        n = 1
    for i in range(min(n, max_frames)):
        gif.seek(i)
        frames.append(gif.convert("RGB").copy())
        durations.append(int(gif.info.get("duration", 100)) or 100)
    return encode_video(frames, durations, magic)


def encode_slider(frames: List[Image.Image], interval_sec: int, anim: int,
                  magic: bytes = b"ANPS") -> bytes:
    """PIL frames + slide interval(s) + transition -> ANPS/ANPT bytes.

    ANPS = "Custom Slider" (default, lands on Apps -> Custom Animation),
    ANPT = "Theme" slider (Themes). Same layout: 24-byte header (base + u16
    interval_sec + u16 transition) + raw RGB565 frames.
    """
    if not frames:
        raise ValueError("no frames")
    n = len(frames)
    frame_bytes = 2 * SCREEN_W * SCREEN_H
    header = (
        magic
        + struct.pack("<H", 20)
        + struct.pack("<H", 24)                 # header size
        + struct.pack("<I", 24 + n * frame_bytes)
        + struct.pack("<H", SCREEN_W)
        + struct.pack("<H", SCREEN_H)
        + struct.pack("<H", 0)
        + struct.pack("<H", n)
        + struct.pack("<H", interval_sec)
        + struct.pack("<H", anim)
    )
    body = b"".join(to_rgb565(resize_cover(f)) for f in frames)
    return header + body


def album_to_slider(images: List[str], interval_sec: int, anim: int,
                    max_frames: int = 500, magic: bytes = b"ANPS") -> bytes:
    """Import a folder/album of images -> ANPS/ANPT slider."""
    frames = []
    for path in images[:max_frames]:
        with Image.open(path) as im:
            frames.append(im.copy())
    return encode_slider(frames, interval_sec, anim, magic)


# --- Matrix LED -----------------------------------------------------------

def encode_tabml(frames: List[Image.Image], fps: int, rows: int, cols: int) -> bytes:
    """List of RGB frames (each rows*cols) -> 'tabml' file bytes."""
    header = bytearray(32)
    header[0:5] = b"tabml"
    header[5] = len(frames)
    header[6] = fps
    header[7] = rows
    header[8] = cols
    body = bytearray()
    for f in frames:
        body += f.convert("RGB").tobytes()
    return bytes(header) + body


def matrix_hsv_data(frames: List[Image.Image], rows: int, cols: int) -> bytes:
    """RGB frames -> HSV upload bytes ([H,S,V] per LED per frame, 0-255)."""
    out = bytearray()
    for f in frames:
        raw = f.convert("RGB").tobytes()
        for i in range(0, len(raw), 3):
            out += bytes(rgb_to_hsv256(raw[i], raw[i + 1], raw[i + 2]))
    return bytes(out)


def rgb_to_hsv256(r: int, g: int, b: int):
    """RGB(0-255) -> [H,S,V] each 0-255, matching the site's get256HSV().

    Deliberately hand-rolled instead of :func:`colorsys.rgb_to_hsv`: this math
    reproduces the configurator's ``get256HSV()`` byte-for-byte, so the HSV
    bytes we send are identical to the official tool's.
    """
    rp, gp, bp = r / 255, g / 255, b / 255
    cmax, cmin = max(rp, gp, bp), min(rp, gp, bp)
    delta = cmax - cmin
    h = 0.0
    if delta:
        # delta == 0 is a pure gray (all channels equal): h stays 0.
        if cmax == rp:
            h = 60 * (((gp - bp) / delta) % 6)
        elif cmax == gp:
            h = 60 * ((bp - rp) / delta + 2)
        else:
            h = 60 * ((rp - gp) / delta + 4)
    s = 0.0 if cmax == 0 else delta / cmax
    v = cmax
    h = (h + 360) % 360
    return (round(255 * h / 360), round(255 * s), round(255 * v))


def hsv256_to_rgb(h: int, s: int, v: int = 255) -> tuple:
    """HSV(0-255 each) -> (r, g, b) 0-255, the inverse of :func:`rgb_to_hsv256`.

    Used to turn the (hue, sat) the firmware reports back into an RGB tuple
    for display. ``v`` defaults to 255 so a color is shown at full value.
    """
    rp, gp, bp = colorsys.hsv_to_rgb((h % 256) / 255, s / 255, v / 255)
    return (round(rp * 255), round(gp * 255), round(bp * 255))


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


# --- Matrix LED (solid colors / custom patterns only) ----------------------

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


def matrix_pattern_rgb(pattern: Sequence[str], color: str) -> List[tuple]:
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


# --------------------------------------------------------------------------
# Transports
# --------------------------------------------------------------------------

def be32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


@dataclass
class Progress:
    callback: Optional[Callable[[int, int], None]] = None  # (done, total)
    total: int = 0
    done: int = 0

    def step(self, n: int):
        self.done += n
        if self.callback:
            self.callback(self.done, self.total)


class CDCTransport:
    """QK80 MK2 tab-file / matrix transport over the USB CDC serial port."""

    def __init__(self, port: Optional[str] = None):
        self.port_name = port
        self.ser = None

    def open(self):
        import serial
        from serial.tools import list_ports

        if not self.port_name:
            for p in list_ports.comports():
                if (getattr(p, "vid", None) == VENDOR_ID and
                        getattr(p, "pid", None) == PRODUCT_ID):
                    self.port_name = p.device
                    break
            if not self.port_name:
                raise RuntimeError(
                    "QK80 MK2 serial port not found (VID/PID 0x514B/0x4D02). "
                    "Pass --port COMx."
                )
        self.ser = serial.Serial(self.port_name, BAUD, timeout=2, write_timeout=2)
        time.sleep(0.2)

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _write(self, cmd: int, args: bytes):
        packet = bytearray(CDC_BUFFER_SIZE)
        packet[0] = cmd
        packet[1:1 + len(args)] = args
        self.ser.write(bytes(packet))
        self.ser.flush()

    def _read_response(self) -> bytes:
        resp = self.ser.read(CDC_BUFFER_SIZE)
        if len(resp) != CDC_BUFFER_SIZE:
            raise TimeoutError(f"CDC response short: {len(resp)} bytes")
        return resp

    def cancel(self):
        """Abort any in-progress tab-file transfer. Safe to call any time.

        BaseException (not just Exception) is caught so a spammed Ctrl+C
        during the cancel write cannot stop it from going out.
        """
        for _ in range(2):
            try:
                self._write(CDC_FILE_CANCEL, b"")
                break
            except BaseException:
                continue

    def set_tab_file(self, data: bytes, progress: Progress = None):
        self._write(CDC_FILE_INFO, data[:20])
        resp = self._read_response()
        if resp[21] == ERR_FLAG:
            raise RuntimeError("file rejected by keyboard (0xEE at header byte 20)")
        flow = bool(resp[22])
        try:
            for off in range(0, len(data), CDC_CHUNK):
                chunk = data[off:off + CDC_CHUNK]
                self._write(CDC_FILE_BUFFER, be32(off) + bytes([len(chunk)]) + chunk)
                if flow:
                    r = self._read_response()
                    if not self._echo_ok(r, be32(off) + bytes([len(chunk)]) + chunk):
                        raise RuntimeError("bad CDC response echo")
                if progress:
                    progress.step(len(chunk))
        except BaseException:
            # On error OR Ctrl+C mid-transfer, tell the keyboard to abort so it
            # does not keep expecting the rest of the file (never bricks it).
            self.cancel()
            raise

    def set_matrix_lighting(self, frames: int, fps: int, rows: int, cols: int,
                            data: bytes, progress: Progress = None):
        self._write(CDC_MATRIX_INFO, bytes([frames, fps, rows, cols]))
        resp = self._read_response()
        if resp[5] == ERR_FLAG:
            raise RuntimeError("matrix info rejected (0xEE)")
        flow = bool(resp[6])
        try:
            for off in range(0, len(data), CDC_CHUNK):
                chunk = data[off:off + CDC_CHUNK]
                self._write(CDC_MATRIX_BUFFER, be32(off) + bytes([len(chunk)]) + chunk)
                if flow:
                    r = self._read_response()
                    if not self._echo_ok(r, be32(off) + bytes([len(chunk)]) + chunk):
                        raise RuntimeError("bad CDC response echo")
                if progress:
                    progress.step(len(chunk))
        except BaseException:
            self.cancel()
            raise

    @staticmethod
    def _echo_ok(resp: bytes, args: bytes) -> bool:
        return resp[0] != 0 and resp[1:1 + len(args)] == args


class HIDTransport:
    """VIA raw HID (usage page 0xFF60) transport; used when CDC is unavailable."""

    def __init__(self):
        self.device = None
        self.path = None

    def open(self):
        import hid

        for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
            if d.get("usage_page") == 0xFF60:
                self.path = d["path"]
                break
        if not self.path:
            raise RuntimeError("QK80 MK2 VIA HID endpoint not found (0xFF60)")
        self.device = hid.device()
        self.device.open_path(self.path)

    def close(self):
        if self.device:
            self.device.close()

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _send(self, cmd: int, args: bytes) -> bytes:
        packet = bytearray(HID_REPORT)
        packet[1] = cmd
        packet[2:2 + len(args)] = args
        self.device.write(bytes(packet))
        time.sleep(0.002)
        resp = bytes(self.device.read(HID_REPORT, timeout_ms=2000))
        if len(resp) < 1 + len(args):
            raise RuntimeError(f"bad HID echo for cmd 0x{cmd:02x}")
        # Two echo layouts: custom-value commands (0x07/0x08/0x09) echo
        # [cmd, args...]; tab-block commands (0xD1) echo [0xFF, args...]
        # with the 0xD1 byte dropped.
        if resp[0] == cmd and resp[1:1 + len(args)] == args:
            return resp
        if resp[0] == 0xFF and resp[1:1 + len(args)] == args:
            return resp
        raise RuntimeError(f"bad HID echo for cmd 0x{cmd:02x}")

    def cancel(self):
        """Abort any in-progress tab-file transfer. Safe to call any time.

        BaseException (not just Exception) is caught so a spammed Ctrl+C
        during the cancel write cannot stop it from going out.
        """
        for _ in range(2):
            try:
                self._send(HID_TAB_BLOCKS, bytes([HID_BLOCK_FILE_CANCEL]))
                break
            except BaseException:
                continue

    def set_tab_file(self, data: bytes, progress: Progress = None):
        resp = self._send(HID_TAB_BLOCKS, bytes([HID_BLOCK_FILE_INFO]) + data[:20])
        if resp[-1]:
            raise RuntimeError(f"file rejected (last byte 0x{resp[-1]:02x})")
        try:
            for off in range(0, len(data), HID_CHUNK):
                chunk = data[off:off + HID_CHUNK]
                self._send(HID_TAB_BLOCKS, bytes([HID_BLOCK_FILE_BUFFER]) + be32(off) +
                           bytes([len(chunk)]) + chunk)
                if progress:
                    progress.step(len(chunk))
        except BaseException:
            # On error OR Ctrl+C mid-transfer, tell the keyboard to abort so it
            # does not keep expecting the rest of the file (never bricks it).
            self.cancel()
            raise

    def set_matrix_lighting(self, frames: int, fps: int, rows: int, cols: int,
                            data: bytes, progress: Progress = None):
        resp = self._send(HID_TAB_BLOCKS, bytes([HID_BLOCK_MATRIX_INFO, frames, fps, rows, cols]))
        if resp[-1]:
            raise RuntimeError("matrix info rejected")
        try:
            for off in range(0, len(data), HID_CHUNK):
                chunk = data[off:off + HID_CHUNK]
                self._send(HID_TAB_BLOCKS, bytes([HID_BLOCK_MATRIX_BUFFER]) + be32(off) +
                           bytes([len(chunk)]) + chunk)
                if progress:
                    progress.step(len(chunk))
        except BaseException:
            self.cancel()
            raise

    def set_matrix_led(self, brightness: Optional[int] = None,
                       effect: Optional[Union[str, int]] = None,
                       color: Optional[Sequence[int]] = None) -> None:
        """Set VIA Lighting -> MATRIX LED values (HID 0x07, subsystem 26).

        These are the settings the configurator's Brightness slider / Effect
        dropdown / Color picker change, and they apply to all matrix modes
        (Letters / Typewriter / Rain). ``brightness`` is 0-255, ``effect`` is
        a name from :data:`MATRIX_LED_EFFECTS` or 0-4, ``color`` is ``(hue,
        sat)`` - the same two bytes the configurator's hue/sat color picker
        sends (NOT RGB). Values are committed with 0x09 so they persist.

        The hue is pre-compensated onto the firmware's coarse hue wheel (see
        :data:`MATRIX_HUE_STEPS`) so that what you set is what the matrix
        actually shows and ``get_matrix_led`` reports back.
        """
        if brightness is None and effect is None and color is None:
            return
        if brightness is not None:
            brightness = int(brightness)
            if not 0 <= brightness <= 255:
                raise ValueError("matrix LED brightness must be 0-255")
            self._send(HID_CUSTOM_SET, bytes([MATRIX_LED_CHANNEL,
                                              MATRIX_LED_VALUE_BRIGHTNESS,
                                              brightness]))
        if effect is not None:
            if isinstance(effect, str):
                try:
                    effect = MATRIX_LED_EFFECTS.index(effect.lower())
                except ValueError:
                    raise ValueError(f"unknown matrix effect {effect!r}; use one "
                                     f"of {MATRIX_LED_EFFECTS}") from None
            effect = int(effect)
            if not 0 <= effect < len(MATRIX_LED_EFFECTS):
                raise ValueError(f"matrix effect must be 0-{len(MATRIX_LED_EFFECTS) - 1}")
            self._send(HID_CUSTOM_SET, bytes([MATRIX_LED_CHANNEL,
                                              MATRIX_LED_VALUE_EFFECT, effect]))
        if color is not None:
            h, s = (int(x) for x in color)
            if not all(0 <= x <= 255 for x in (h, s)):
                raise ValueError("matrix LED color (hue, sat) must be 0-255")
            h = _hue_to_stored(h)  # see MATRIX_HUE_STEPS
            self._send(HID_CUSTOM_SET, bytes([MATRIX_LED_CHANNEL,
                                              MATRIX_LED_VALUE_COLOR, h, s]))
        self._send(HID_CUSTOM_SAVE, bytes([MATRIX_LED_CHANNEL]))

    def get_matrix_led(self) -> dict:
        """Read VIA Lighting -> MATRIX LED values (HID 0x08, subsystem 26)."""
        br = self._send(HID_CUSTOM_GET, bytes([MATRIX_LED_CHANNEL,
                                               MATRIX_LED_VALUE_BRIGHTNESS]))
        ef = self._send(HID_CUSTOM_GET, bytes([MATRIX_LED_CHANNEL,
                                               MATRIX_LED_VALUE_EFFECT]))
        co = self._send(HID_CUSTOM_GET, bytes([MATRIX_LED_CHANNEL,
                                               MATRIX_LED_VALUE_COLOR]))
        effect = ef[3]
        return {
            "brightness": br[3],
            "effect": effect,
            "effect_name": MATRIX_LED_EFFECTS[effect] if effect < len(MATRIX_LED_EFFECTS) else "?",
            "color": (co[3], co[4]),
        }


# --- High-level helpers ----------------------------------------------------

def upload(data: bytes, transport: str = "cdc", port: Optional[str] = None,
           progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
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


def set_matrix_color(color: str, port: Optional[str] = None) -> None:
    """Set the Letters / Typewriter / Rain mode color (HID, persists).

    This is the configurator's Lighting -> MATRIX LED -> Color picker. It does
    NOT touch the Custom grid - fill that separately with
    :func:`set_matrix_custom`. ``color`` is a :data:`MATRIX_COLORS` name,
    ``'#rrggbb'``, or ``'r g b'``.
    """
    rgb = parse_color([color])
    h, s, _v = rgb_to_hsv256(*rgb)
    with HIDTransport() as t:
        t.set_matrix_led(color=(h, s))


def set_matrix_custom(color: str, transport: str = "cdc",
                      port: Optional[str] = None) -> None:
    """Fill only the 7x7 Custom grid solid with ``color``.

    Does not touch the Letters / Typewriter / Rain mode color or effect.
    ``color`` is a :data:`MATRIX_COLORS` name, ``'#rrggbb'``, or ``'r g b'``.
    Ctrl+C is safe.
    """
    rgb = parse_color([color])
    frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS), rgb)
    data = _matrix_frame_to_hsv(frame)
    with CDCTransport(port) if transport == "cdc" else HIDTransport() as t:
        t.set_matrix_lighting(1, 1, MATRIX_ROWS, MATRIX_COLS, data)


def set_matrix_pattern(pattern: Sequence[str], color: str, transport: str = "cdc",
                       port: Optional[str] = None) -> None:
    """Draw a manual 7x7 pattern on the Custom matrix mode only.

    Does not touch the Letters / Typewriter / Rain mode color or effect.
    ``pattern`` is 7 strings of 7 characters; ``'.'`` = LED off, any other
    character = LED on in ``color`` (a :data:`MATRIX_COLORS` name). Example
    (a heart):

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


def reset_matrix(transport: str = "cdc", port: Optional[str] = None) -> None:
    """Restore the Custom matrix mode to its factory default (all LEDs off)."""
    data = matrix_blank_hsv()
    with CDCTransport(port) if transport == "cdc" else HIDTransport() as t:
        t.set_matrix_lighting(1, 1, MATRIX_ROWS, MATRIX_COLS, data)


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


def set_matrix_brightness(percent: int, port: Optional[str] = None) -> None:
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


def set_matrix_effect(name: str, port: Optional[str] = None) -> None:
    """Switch the matrix mode: off / typewriter / terminal / raindrop / custom."""
    with HIDTransport() as t:
        t.set_matrix_led(effect=name)


def get_matrix_led(port: Optional[str] = None) -> dict:
    """Read the current matrix LED values (brightness, effect, color).

    Returns ``{"brightness": 0-255, "effect": int, "effect_name": str,
    "color": (hue, sat)}`` where ``color`` is the raw (hue, sat) the firmware
    stores (use :func:`hsv256_to_rgb` to display it as RGB).
    """
    with HIDTransport() as t:
        return t.get_matrix_led()


def probe_devices() -> dict:
    """Enumerate connected QK80 MK2 devices over CDC (serial) and HID.

    Returns ``{"cdc": [...], "hid": [...]}`` for anything matching the QK80
    MK2 IDs (VID 0x514B / PID 0x4D02), so callers can confirm the device is
    present and decide which transport to use. Both lists are empty when the
    keyboard is not connected.
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


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _show_devices() -> None:
    print(f"QK80 MK2 detection (VID 0x{VENDOR_ID:04X}, PID 0x{PRODUCT_ID:04X}):")
    try:
        dev = probe_devices()
    except ImportError as e:
        print(f"ERROR: {e}")
        print("hint: run '.venv\\Scripts\\pip install -r requirements.txt' first")
        return
    if dev["cdc"]:
        for d in dev["cdc"]:
            print(f"  CDC: {d['port']}  {d['product'] or 'unknown product'}"
                  f"  ({d['manufacturer'] or 'unknown vendor'})")
    else:
        print("  CDC: none found (keyboard unplugged or driver missing)")
    if dev["hid"]:
        for d in dev["hid"]:
            path = d["path"]
            if isinstance(path, bytes):
                path = path.decode("utf-8", "replace")
            via = "  <-- VIA raw (HID transport)" if d["usage_page"] == 0xFF60 else ""
            print(f"  HID: {path}  usage_page=0x{d['usage_page']:04x}{via}")
    else:
        print("  HID: none found")


def main():
    import argparse

    ap = argparse.ArgumentParser(description="QK80 MK2 LCD / Matrix LED tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        up = p.add_mutually_exclusive_group()
        up.add_argument("--upload", action="store_true",
                        help="upload to the keyboard (this is the default)")
        up.add_argument("--no-upload", action="store_true",
                        help="encode only, do not upload")
        p.add_argument("--transport", choices=["cdc", "hid"], default="cdc",
                       help="upload transport (default: cdc)")
        p.add_argument("--port", default=None, help="serial port (CDC only)")
        p.add_argument("--save", default=None, help="also save the encoded file")

    p_img = sub.add_parser("image", help="PNG/JPG -> ABKT theme / ABKG custom image")
    p_img.add_argument("src")
    p_img.add_argument("--variant", default="theme", choices=["theme", "custom"],
                       help="theme=ABKT (default; Themes screen), "
                            "custom=ABKG (Apps -> Custom Animation screen)")
    add_common(p_img)

    p_vid = sub.add_parser("video", help="GIF -> ANIT theme / ANIM custom animation")
    p_vid.add_argument("src")
    p_vid.add_argument("--max-frames", type=int, default=500)
    p_vid.add_argument("--variant", default="theme", choices=["theme", "custom"],
                       help="theme=ANIT (default; Themes screen), "
                            "custom=ANIM (Apps -> Custom Animation screen)")
    add_common(p_vid)

    p_mat = sub.add_parser(
        "matrix",
        help="7x7 Matrix LED zone: universal color/brightness/effect, get, or "
             "Custom-grid operations")
    p_mat.add_argument("action", nargs="?", default=None,
                       choices=["color", "brightness", "effect", "get", "custom",
                                "solid", "reset"] + list(MATRIX_COLORS),
                       help="'color' (or just a color name) sets the Letters / "
                            "Typewriter / Rain mode color (the Custom grid is "
                            "untouched); 'brightness' sets the brightness of all "
                            "modes (1-100%%); 'effect' switches the mode; 'get' "
                            "prints the current values; 'custom' fills the Custom "
                            "grid with a color name, draws --pattern, or 'reset's "
                            "it; 'solid' and 'reset' are shortcuts for 'custom' "
                            "solid/reset")
    p_mat.add_argument("value", nargs="*", metavar="VALUE",
                       help="for 'color': a name, '#rrggbb', or 'r g b'; for "
                            "'brightness': 1-100; for 'effect': off/typewriter/"
                            "terminal/raindrop/custom; for 'custom': a color name, "
                            "'solid', or 'reset'")
    p_mat.add_argument("--color", choices=list(MATRIX_COLORS), default="white",
                       help=f"LED color for custom grid ops (default white); one of: "
                            f"{MATRIX_COLOR_NAMES}")
    p_mat.add_argument("--pattern", nargs="+", metavar="ROW",
                       help="custom: 7 rows of 7 chars ('.' = LED off, any other char "
                            "= LED on in --color)")
    add_common(p_mat)

    p_slider = sub.add_parser("slider",
                              help="Album of images -> ANPS custom / ANPT theme slider")
    p_slider.add_argument("src", nargs="+",
                          help="image files, sorted by name like the app")
    p_slider.add_argument("--interval", type=int, default=5,
                          choices=[5, 10, 15, 30], help="seconds per slide")
    p_slider.add_argument("--anim", type=int, default=ANIM_TRANS_NONE,
                          help="transition (1 none, 2 down, 3 up, 4 right, 5 left)")
    p_slider.add_argument("--format", default="ANPS", choices=["ANPS", "ANPT"],
                          help="ANPS=custom slider (default; Apps -> Custom Animation "
                               "screen), ANPT=theme slider (Themes screen)")
    add_common(p_slider)

    sub.add_parser("devices", help="list detected QK80 MK2 devices (CDC + HID)")

    a = ap.parse_args()

    def upload(transport, data: bytes) -> None:
        progress = Progress(callback=lambda d, t: print(f"  {d}/{t} bytes"))
        progress.total = len(data)
        transport.set_tab_file(data, progress)

    transport = None
    try:
        if a.cmd == "matrix":
            # 'matrix <color>' is shorthand for 'matrix color <color>'; both
            # need HID for the mode color. Custom-grid ops use --transport.
            hid_action = (a.action in MATRIX_COLORS or a.action == "color"
                          or a.action in ("effect", "brightness", "get"))
            if hid_action and not getattr(a, "no_upload", False):
                transport = HIDTransport()  # Lighting -> MATRIX LED lives on HID
            elif not getattr(a, "no_upload", False):
                transport = CDCTransport(a.port) if a.transport == "cdc" else HIDTransport()
        elif a.cmd != "devices" and not getattr(a, "no_upload", False):
            transport = CDCTransport(a.port) if a.transport == "cdc" else HIDTransport()
        if transport:
            transport.open()
        ok = False
        try:
            if a.cmd == "devices":
                _show_devices()
            elif a.cmd == "image":
                img = Image.open(a.src)
                if a.variant == "theme":
                    data = encode_image(img)
                else:
                    data = encode_image(img, magic=b"ABKG")
                print(f"encoded {data[:4].decode()} "
                      f"({'theme image' if a.variant == 'theme' else 'custom image'}) "
                      f"({len(data)} bytes)")
                if a.save:
                    open(a.save, "wb").write(data)
                    print(f"  saved -> {a.save}")
                if transport:
                    upload(transport, data)
                    print("image uploaded")
            elif a.cmd == "video":
                gif = Image.open(a.src)
                if a.variant == "theme":
                    data = gif_to_video(gif, a.max_frames)
                else:
                    data = gif_to_video(gif, a.max_frames, magic=b"ANIM")
                print(f"encoded {data[:4].decode()} "
                      f"({'theme animation' if a.variant == 'theme' else 'custom animation'}) "
                      f"({len(data)} bytes)")
                if a.save:
                    open(a.save, "wb").write(data)
                    print(f"  saved -> {a.save}")
                if transport:
                    upload(transport, data)
                    print("animation uploaded")
            elif a.cmd == "slider":
                files = sorted(a.src)
                data = album_to_slider(files, a.interval, a.anim, magic=a.format.encode())
                print(f"encoded {a.format} ({len(data)} bytes, {len(files)} images)")
                if a.save:
                    open(a.save, "wb").write(data)
                    print(f"  saved -> {a.save}")
                if transport:
                    upload(transport, data)
                    print("slider uploaded")
            elif a.cmd == "matrix":
                action = a.action
                value = list(a.value)
                if action in MATRIX_COLORS:
                    value = [action]
                    action = "color"  # shorthand: `matrix cyan` == `matrix color cyan`
                if action in ("color", "effect", "brightness", "get"):
                    if not transport:
                        raise RuntimeError("matrix color/brightness/effect/get need "
                                           "the keyboard (drop --no-upload)")
                    if action == "get":
                        m = transport.get_matrix_led()
                        rgb = hsv256_to_rgb(*m["color"])
                        print(f"matrix LED: brightness={round(m['brightness'] / 255 * 100)}% "
                              f"effect={m['effect_name']} "
                              f"color=#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}")
                    elif action == "color":
                        rgb = parse_color(value)
                        h, s, _v = rgb_to_hsv256(*rgb)
                        transport.set_matrix_led(color=(h, s))
                        print(f"matrix: mode color set to #{rgb[0]:02x}{rgb[1]:02x}"
                              f"{rgb[2]:02x} (Letters/Typewriter/Rain modes; "
                              f"the Custom grid is untouched)")
                    elif action == "effect":
                        if len(value) != 1:
                            raise RuntimeError("effect needs one of: "
                                               f"{MATRIX_LED_EFFECTS}")
                        transport.set_matrix_led(effect=value[0])
                        print(f"matrix: effect set to {value[0].lower()} "
                              f"(off/typewriter/terminal/raindrop/custom)")
                    else:
                        if len(value) != 1:
                            raise RuntimeError("brightness needs one value 1-100")
                        pct = int(value[0])
                        if not 1 <= pct <= 100:
                            raise RuntimeError("brightness must be 1-100%")
                        transport.set_matrix_led(brightness=round(pct * 255 / 100))
                        print(f"matrix: brightness set to {pct}%")
                else:
                    # Custom grid ops: 'custom', 'solid' (alias), 'reset' (alias)
                    if action == "reset" or (a.pattern is None and value
                                             and value[0].lower() == "reset"):
                        frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS), (0, 0, 0))
                        label = "custom grid cleared (factory default)"
                    elif a.pattern:
                        frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS))
                        frame.putdata(matrix_pattern_rgb(a.pattern, a.color))
                        label = f"custom pattern in {a.color}"
                    else:
                        sub = value[0].lower() if value else ""
                        if sub in MATRIX_COLORS:
                            fill, label = sub, f"custom grid filled {sub}"
                        elif sub in ("", "solid"):
                            fill, label = a.color, f"custom grid filled {a.color}"
                        else:
                            raise RuntimeError(
                                f"unknown matrix custom sub-action {sub!r}; use a "
                                f"color name ({MATRIX_COLOR_NAMES}), 'solid', or 'reset'")
                        frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS),
                                          MATRIX_COLORS[fill])
                    data = _matrix_frame_to_hsv(frame)
                    if a.save:
                        tabml = encode_tabml([frame], 1, MATRIX_ROWS, MATRIX_COLS)
                        open(a.save, "wb").write(tabml)
                        print(f"encoded tabml -> {a.save} ({len(tabml)} bytes)")
                    if transport:
                        transport.set_matrix_lighting(1, 1, MATRIX_ROWS, MATRIX_COLS, data)
                        print(f"matrix LEDs: {label}")
                    else:
                        print(f"matrix LEDs: {label} (encode only, not uploaded)")
            ok = True
        finally:
            if transport and not ok:
                try:
                    transport.cancel()
                except BaseException:
                    pass
            if transport:
                try:
                    transport.close()
                except BaseException:
                    pass
    except KeyboardInterrupt:
        try:
            print("\ninterrupted: upload cancelled, the keyboard was sent a cancel command "
                  "and is safe to retry or unplug")
        except BaseException:
            pass
    except Exception as e:
        msg = str(e)
        print(f"ERROR: {msg}")
        if "could not open port" in msg.lower():
            print("hint: close cfg.qwertykeys.com in your browser (it holds the serial port),")
            print("      or unplug/replug the keyboard, then run again.")
        elif isinstance(e, (FileNotFoundError, OSError)) or "port" in msg.lower():
            print("hint: plug in the keyboard, or pass --port COMx")


if __name__ == "__main__":
    main()
