"""Command-line interface for the QK80 MK2 tool (``python -m qk80``).

Subcommands mirror the configurator's screens and the matrix-LED lighting
controls. For the full command reference see README.md, section 6 (CLI) and
section 7 (library API).
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

from PIL import Image

from .api import parse_sleep_mode, probe_devices
from .constants import (
    ANIM_TRANS_NONE,
    DEVICE_NAME,
    MATRIX_COLS,
    MATRIX_LED_EFFECTS,
    MATRIX_ROWS,
    PRODUCT_ID,
    SLEEP_MODES,
    VENDOR_ID,
)
from .encoders import (
    album_to_slider,
    encode_image,
    encode_tabml,
    gif_to_video,
    hsv256_to_rgb,
    rgb_to_hsv256,
)
from .matrix import (
    MATRIX_COLOR_NAMES,
    MATRIX_COLORS,
    _matrix_frame_to_hsv,
    matrix_pattern_rgb,
    parse_color,
)
from .transport import CDCTransport, HIDTransport, Progress


def _show_devices() -> None:
    print(f"{DEVICE_NAME} detection (VID 0x{VENDOR_ID:04X}, PID 0x{PRODUCT_ID:04X}):")
    try:
        dev = probe_devices()
    except ImportError as e:
        print(f"ERROR: {e}")
        print("hint: run 'uv sync' first (dependencies come from pyproject.toml)")
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
    ap = argparse.ArgumentParser(description=f"{DEVICE_NAME} LCD / Matrix LED tool")
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

    p_time = sub.add_parser(
        "time",
        help="sync the on-screen clock (Config -> Date and Time -> time sync, HID)")
    p_time.add_argument("action", nargs="?", default="sync",
                        choices=["sync", "set"],
                        help="'sync' uses the host's current local time (default); "
                             "'set' uses the given wall-clock time")
    p_time.add_argument("value", nargs="?", default=None,
                        help="for 'set': an ISO date-time like '2026-08-14 14:30:00'")

    p_lights = sub.add_parser(
        "lights",
        help="all-LED power on/off (Config -> Features -> Light Power, HID)")
    p_lights.add_argument("action", nargs="?", default="get",
                          choices=["on", "off", "get"],
                          help="'on'/'off' toggle the LED power; 'get' prints the "
                               "current state (default)")

    p_sleep = sub.add_parser(
        "sleep",
        help="sleep-mode timer (Config -> Features -> Sleep Mode, HID)")
    p_sleep.add_argument("value", nargs="?", default=None,
                         help="disable / 5min / 15min / 30min / 1h / 3h / 6h "
                              "(or an index 0-6); omit to print the current mode")

    sub.add_parser("devices", help=f"list detected {DEVICE_NAME} devices (CDC + HID)")

    a = ap.parse_args()

    def _cli_upload(transport, data: bytes) -> None:
        total = len(data)
        last_pct = -1
        start = time.monotonic()

        def on_progress(done, total):
            nonlocal last_pct
            pct = round(done * 100 / total)
            if pct != last_pct:  # redraw only when the % changes
                last_pct = pct
                print(f"\r  [{'#' * (pct // 2):<50}] {pct:3d}%  "
                      f"{done:,}/{total:,} bytes", end="", flush=True)

        try:
            progress = Progress(callback=on_progress)
            progress.total = total
            transport.set_tab_file(data, progress)
            print(f"\r  [{'#' * 50}] 100%  {total:,}/{total:,} bytes  "
                  f"({time.monotonic() - start:.1f}s)")
        except BaseException:
            print()
            raise

    transport = None
    try:
        if a.cmd == "matrix":
            if a.action is None:
                p_mat.print_help()  # bare `matrix` must not touch the device
                return
            # 'matrix <color>' is shorthand for 'matrix color <color>'; both
            # need HID for the mode color. Custom-grid ops use --transport.
            hid_action = (a.action in MATRIX_COLORS or a.action == "color"
                          or a.action in ("effect", "brightness", "get"))
            if hid_action and not getattr(a, "no_upload", False):
                transport = HIDTransport()  # Lighting -> MATRIX LED lives on HID
            elif not getattr(a, "no_upload", False):
                transport = CDCTransport(a.port) if a.transport == "cdc" else HIDTransport()
        elif a.cmd in ("time", "lights", "sleep"):
            transport = HIDTransport()  # VIA custom values live on HID, like matrix LED
        elif a.cmd != "devices" and not getattr(a, "no_upload", False):
            transport = CDCTransport(a.port) if a.transport == "cdc" else HIDTransport()
        if transport:
            transport.open()
        ok = False
        try:
            if a.cmd == "devices":
                _show_devices()
            elif a.cmd == "image":
                with Image.open(a.src) as img:
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
                    _cli_upload(transport, data)
                    print("image uploaded")
            elif a.cmd == "video":
                with Image.open(a.src) as gif:
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
                    _cli_upload(transport, data)
                    print("animation uploaded")
            elif a.cmd == "slider":
                files = sorted(a.src)
                data = album_to_slider(files, a.interval, a.anim, magic=a.format.encode())
                print(f"encoded {a.format} ({len(data)} bytes, {len(files)} images)")
                if a.save:
                    open(a.save, "wb").write(data)
                    print(f"  saved -> {a.save}")
                if transport:
                    _cli_upload(transport, data)
                    print("slider uploaded")
            elif a.cmd == "matrix":
                action = a.action
                value = a.value
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
            elif a.cmd == "time":
                if a.action == "set":
                    if not a.value:
                        raise RuntimeError(
                            "time set needs an ISO date-time like '2026-08-14 14:30:00'")
                    when = datetime.fromisoformat(a.value.replace(" ", "T"))
                    shown = when.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    when = None
                    shown = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                transport.sync_time(when)
                print(f"time: keyboard clock set to {shown} "
                      f"(Config -> Date and Time -> time sync)")
            elif a.cmd == "lights":
                if a.action == "get":
                    state = transport.get_light_power()
                    print(f"light power: {'on' if state else 'off'}")
                else:
                    transport.set_light_power(a.action == "on")
                    print(f"light power: {a.action} "
                          f"(Config -> Features -> Light Power)")
            elif a.cmd == "sleep":
                if a.value is None:
                    n = transport.get_sleep_mode()
                    label = SLEEP_MODES[n][1] if 0 <= n < len(SLEEP_MODES) else "?"
                    print(f"sleep mode: {label}")
                else:
                    n = parse_sleep_mode(a.value)
                    transport.set_sleep_mode(n)
                    print(f"sleep mode: {SLEEP_MODES[n][1]} "
                          f"(Config -> Features -> Sleep Mode)")
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
