"""Tab-file format encoders (pure functions, no I/O).

Turn PIL images / GIFs / frame lists into the byte formats the keyboard
understands: ABKT/ABKG images, ANIT/ANIM animations, ANPS/ANPT sliders, and
``tabml`` matrix-LED files. Byte-for-byte compatible with the official
cfg.qwertykeys.com ``kbres.wasm`` output (see PROTOCOL.md).
"""

from __future__ import annotations

import colorsys
import struct

from PIL import Image

from .constants import MATRIX_COLS, MATRIX_ROWS, SCREEN_H, SCREEN_W


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
        Image.Resampling.LANCZOS,
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
        + struct.pack("<H", 20)                 # 4:  header start
        + struct.pack("<H", 20)                 # 6:  header size
        + struct.pack("<I", 20 + len(pixels))   # 8:  total file size
        + struct.pack("<H", img.width)          # 12: width
        + struct.pack("<H", img.height)         # 14: height
        + struct.pack("<H", 0)                  # 16
        + struct.pack("<H", 1)                  # 18: frame count (1)
        + pixels
    )


def encode_video(frames: list[Image.Image], durations_ms: list[int],
                 magic: bytes = b"ANIT") -> bytes:
    """PIL frames + durations (ms) -> ANIT/ANIM bytes (header + RGB565 frames).

    ANIT = "Theme" video (default, lands on Themes -> Default Theme),
    ANIM = "Custom Animation" (Apps). Identical layout; only the 4-byte magic
    differs (the firmware routes the two to different screens).
    """
    if not frames:
        raise ValueError("no frames")
    if len(frames) != len(durations_ms):
        raise ValueError("frames/durations length mismatch")
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
    frames: list[Image.Image] = []
    durations: list[int] = []
    try:
        n = gif.n_frames
    except Exception:
        n = 1
    for i in range(min(n, max_frames)):
        gif.seek(i)
        frames.append(gif.convert("RGB").copy())
        durations.append(int(gif.info.get("duration", 100)) or 100)
    return encode_video(frames, durations, magic)


def encode_slider(frames: list[Image.Image], interval_sec: int, anim: int,
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


def album_to_slider(images: list[str], interval_sec: int, anim: int,
                    max_frames: int = 500, magic: bytes = b"ANPS") -> bytes:
    """Import a folder/album of images -> ANPS/ANPT slider."""
    frames = []
    for path in images[:max_frames]:
        with Image.open(path) as im:
            frames.append(im.copy())
    return encode_slider(frames, interval_sec, anim, magic)


# --- Matrix LED -----------------------------------------------------------

def encode_tabml(frames: list[Image.Image], fps: int, rows: int, cols: int) -> bytes:
    """List of RGB frames (each rows*cols) -> 'tabml' file bytes."""
    n = len(frames)
    for name, value in (("frames", n), ("fps", fps), ("rows", rows), ("cols", cols)):
        if not 0 <= value <= 255:
            raise ValueError(f"encode_tabml: {name} must be 0-255, got {value}")
    header = bytearray(32)
    header[0:5] = b"tabml"
    header[5] = n
    header[6] = fps
    header[7] = rows
    header[8] = cols
    body = bytearray()
    for f in frames:
        body += f.convert("RGB").tobytes()
    return bytes(header) + body


def matrix_hsv_data(frames: list[Image.Image], rows: int, cols: int) -> bytes:
    """RGB frames -> HSV upload bytes ([H,S,V] per LED per frame, 0-255)."""
    out = bytearray()
    for f in frames:
        if f.size != (cols, rows):
            raise ValueError(f"matrix frame must be {cols}x{rows}, got {f.size[0]}x{f.size[1]}")
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
