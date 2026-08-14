"""USB transports for tab-file / matrix uploads.

Two mutually-exclusive paths to the keyboard:

  * CDC (USB serial @115200, 64-byte packets) - QK80 MK2 uses this
  * HID (VIA raw endpoint 0xFF60, 33-byte packets) - fallback / older firmwares

Both expose ``set_tab_file`` / ``set_matrix_lighting`` so the higher layers
and the CLI can swap transports without knowing the wire details.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from .constants import (
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
    MATRIX_LED_CHANNEL,
    MATRIX_LED_EFFECTS,
    MATRIX_LED_VALUE_BRIGHTNESS,
    MATRIX_LED_VALUE_COLOR,
    MATRIX_LED_VALUE_EFFECT,
    PRODUCT_ID,
    VENDOR_ID,
    VIA_USAGE_PAGE,
)
from .matrix import _hue_to_stored


def be32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


@dataclass
class Progress:
    callback: Callable[[int, int], None] | None = None  # (done, total)
    total: int = 0
    done: int = 0

    def step(self, n: int):
        self.done += n
        if self.callback:
            self.callback(self.done, self.total)


class CDCTransport:
    """Tab-file / matrix transport over the USB CDC serial port."""

    def __init__(self, port: str | None = None):
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
                    f"{DEVICE_NAME} serial port not found "
                    f"(VID/PID 0x{VENDOR_ID:04X}/0x{PRODUCT_ID:04X}). "
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
                    if not self._echo_ok(r, CDC_FILE_BUFFER,
                                         be32(off) + bytes([len(chunk)]) + chunk):
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
                    if not self._echo_ok(r, CDC_MATRIX_BUFFER,
                                         be32(off) + bytes([len(chunk)]) + chunk):
                        raise RuntimeError("bad CDC response echo")
                if progress:
                    progress.step(len(chunk))
        except BaseException:
            self.cancel()
            raise

    @staticmethod
    def _echo_ok(resp: bytes, cmd: int, args: bytes) -> bool:
        return resp[0] == cmd and resp[1:1 + len(args)] == args


class HIDTransport:
    """VIA raw HID (usage page 0xFF60) transport; used when CDC is unavailable."""

    def __init__(self):
        self.device = None
        self.path = None

    def open(self):
        import hid

        for d in hid.enumerate(VENDOR_ID, PRODUCT_ID):
            if d.get("usage_page") == VIA_USAGE_PAGE:
                self.path = d["path"]
                break
        if not self.path:
            raise RuntimeError(f"{DEVICE_NAME} VIA HID endpoint not found "
                               f"(usage page 0x{VIA_USAGE_PAGE:04X})")
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

    def set_matrix_led(self, brightness: int | None = None,
                       effect: str | int | None = None,
                       color: Sequence[int] | None = None) -> None:
        """Set VIA Lighting -> MATRIX LED values (HID 0x07, subsystem 26).

        These are the settings the configurator's Brightness slider / Effect
        dropdown / Color picker change, and they apply to all matrix modes
        (Letters / Typewriter / Rain). ``brightness`` is 0-255, ``effect`` is
        a name from :data:`qk80.constants.MATRIX_LED_EFFECTS` or 0-4, ``color``
        is ``(hue, sat)`` - the same two bytes the configurator's hue/sat color
        picker sends (NOT RGB). Values are committed with 0x09 so they persist.

        The hue is pre-compensated onto the firmware's coarse hue wheel (see
        :data:`qk80.matrix.MATRIX_HUE_STEPS`) so that what you set is what the
        matrix actually shows and ``get_matrix_led`` reports back.
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
