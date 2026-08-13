# QK80 MK2 screen uploader

Upload images, GIFs and slideshows to the QK80 MK2's 320x172 LCD directly from
the command line — no browser, no wasm. The same files the official
configurator (cfg.qwertykeys.com) produces, byte-for-byte, sent over the same
protocol.

It is also a **small library**: `qk80.py` exposes the encoders and transports,
so you can build your own Python programs that feed this display — a
current-game detector, a "now playing" album-art screen, a stats ticker,
whatever you like. See [Library API](#library-api) and `examples/`.

```
qk80.py image  tests/black.png      # image  -> Themes -> Default Theme
qk80.py video  tests/anim.gif       # GIF    -> Themes -> Default Theme
qk80.py slider tests/black.png tests/red.png   # album -> Apps -> Custom Animation
```

## The outcome

On the keyboard, uploaded content lands on one of two screens:

| CLI command              | Format | Lands on                          |
|--------------------------|--------|-----------------------------------|
| `image` (default)        | ABKT   | **Themes → Default Theme**        |
| `video` (default)        | ANIT   | **Themes → Default Theme**        |
| `slider` (default)       | ANPS   | **Apps → Custom Animation**       |
| `image --variant custom` | ABKG   | Apps → Custom Animation           |
| `video --variant custom` | ANIM   | Apps → Custom Animation           |
| `slider --format ANPT`   | ANPT   | Themes → Default Theme            |

The defaults are chosen to match this routing: image/video default to the
"theme" variants (`ABKT`/`ANIT`, which land on the Themes screen) and slider to
the "custom" variant (`ANPS`, which lands on Apps → Custom Animation). The
`--variant` / `--format` flags let you send content to the other screen.

## How it works

1. **Encode** the source into the keyboard's on-disk format. A PNG/GIF/album is
   scaled to cover 320x172 and converted to raw RGB565, wrapped in a small
   header whose first four bytes are the *magic* that tells the firmware which
   screen to use:

   | Magic | Meaning                    |
   |-------|----------------------------|
   | `ABKT`| Theme image                |
   | `ABKG`| Custom image               |
   | `ANIT`| Theme animation            |
   | `ANIM`| Custom animation           |
   | `ANPS`| Custom slider              |
   | `ANPT`| Theme slider               |

   These files are byte-identical to what the official site's `kbres.wasm`
   produces (verified: 0 differing bytes for image, video and slider).

2. **Upload** the file over USB CDC (serial @115200, 64-byte packets): a
   `0xE0` header packet with the first 20 file bytes, then `0xE1` buffer
   packets carrying 56-byte chunks (flow-controlled per chunk), `0xE2` to
   cancel. An HID fallback (`0xD1 0x20/0x21`) exists for firmwares without CDC.

The site does exactly the same thing: it sends only the encoded file bytes —
there is no extra "which screen" command. The screen is decided entirely by the
4-byte magic, so a byte-identical upload from this tool is indistinguishable
from one done in the browser.

## Requirements

* Python 3.10+
* A QK80 MK2 plugged in via USB
* `cfg.qwertykeys.com` **closed** (it holds the serial port — this tool will
  fail with a port-open error until you close the browser tab)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Usage

All commands upload to the keyboard by default. Every command accepts these
common flags:

| Flag | Meaning |
|------|---------|
| `--transport cdc\|hid` | transport (default `cdc`; `hid` uses the VIA HID fallback) |
| `--port COMx` | pick a serial port (CDC only; auto-detected by default) |
| `--save FILE` | also write the encoded file (in addition to uploading) |
| `--no-upload` | encode only, never touch the keyboard |
| `--upload` | upload (this is the default; kept for explicitness) |

> `matrix color` (and the bare-colorname shorthand `matrix cyan`) /
> `matrix effect` / `matrix brightness` / `matrix get` always use the HID
> transport — `--transport` is ignored for them.

### `devices` — what the computer sees

```powershell
.venv\Scripts\python qk80.py devices
```

Lists the QK80 MK2's CDC port and every HID interface, flagging the VIA raw
endpoint (`usage_page 0xFF60`) used by the HID transport.

### `image` — PNG/JPG → LCD image

`src` is the image file. `--variant` picks the destination screen:
`theme` = ABKT → **Themes → Default Theme** (default), `custom` = ABKG →
**Apps → Custom Animation**.

```powershell
.venv\Scripts\python qk80.py image tests\black.png                   # ABKT (Themes)
.venv\Scripts\python qk80.py image tests\gradient.png --variant custom  # ABKG (Apps)
.venv\Scripts\python qk80.py image photo.png --no-upload --save out.abkt
```

### `video` — GIF → LCD animation

`src` is an animated GIF. `--max-frames` caps the frame count (firmware limit
is 500); `--variant` picks the screen: `theme` = ANIT (default), `custom` =
ANIM.

```powershell
.venv\Scripts\python qk80.py video tests\anim.gif                    # ANIT (Themes)
.venv\Scripts\python qk80.py video tests\anim.gif --variant custom   # ANIM (Apps)
.venv\Scripts\python qk80.py video clip.gif --max-frames 300
```

### `slider` — album/slideshow

Takes any number of image files, sorted by name like the app does.

```powershell
.venv\Scripts\python qk80.py slider tests\black.png tests\red.png --interval 10
.venv\Scripts\python qk80.py slider 1.png 2.png 3.png --format ANPT --anim 3
```

> PowerShell does **not** expand `*.png` for native commands, so list the files
> explicitly (or expand with `Get-ChildItem`). `cmd.exe` expands them for you.

| Flag | Default | Meaning |
|------|---------|---------|
| `--interval` | `5` | seconds per slide (`5`, `10`, `15`, `30`) |
| `--anim` | `1` | transition: `1` none, `2` down, `3` up, `4` right, `5` left |
| `--format` | `ANPS` | `ANPS` = custom slider → Apps → Custom Animation, `ANPT` = theme slider → Themes → Default Theme |

### `matrix` — 7×7 Matrix LED

Two independent parts: the **mode settings** (color / brightness / effect,
which apply to the Letters / Typewriter / Rain modes) and the **Custom grid**
(the 49-LED pattern). Setting a mode setting never touches the Custom grid,
and editing the Custom grid never changes the mode settings.

**Mode settings** (HID, persist across power cycles — the same values as the
configurator's `Lighting -> MATRIX LED` sliders):

```powershell
.venv\Scripts\python qk80.py matrix color red            # mode color: name, #rrggbb, or r g b
.venv\Scripts\python qk80.py matrix color "#00ff00"
.venv\Scripts\python qk80.py matrix color 255 128 0
.venv\Scripts\python qk80.py matrix brightness 50        # 1-100%
.venv\Scripts\python qk80.py matrix effect raindrop      # off/typewriter/terminal/raindrop/custom
.venv\Scripts\python qk80.py matrix get                  # print current values
```

`matrix color` (or a bare color name — `qk80.py matrix cyan`) sets only the
Letters / Typewriter / Rain mode color; the Custom grid is left as it is.

**Custom grid** (the 49-LED pattern, uploaded over `0xC0`/`0xC1`):

```powershell
.venv\Scripts\python qk80.py matrix custom cyan                         # fill all 49 LEDs cyan
.venv\Scripts\python qk80.py matrix solid --color cyan                  # same, explicit
.venv\Scripts\python qk80.py matrix custom --color red --pattern "......." "..X.X.." ".XXX.X." "XXXXXXX" ".XXXXX." "..XXX.." "...X..."
.venv\Scripts\python qk80.py matrix custom reset                        # factory default (all off)
.venv\Scripts\python qk80.py matrix reset                               # same, shorthand
.venv\Scripts\python qk80.py matrix custom --pattern "..X..X." "......." "X..X..X" ".XXXXX." ".XXXXX." "..XXX.." "..X.X.." --no-upload --save grid.tabml
```

`--pattern` takes 7 rows of 7 characters: `.` = LED off, any other character =
LED on in `--color`. `--color` accepts the palette `red orange yellow green
cyan blue magenta purple white off` (default `white`).

Notes on the mode color: the firmware stores it as **hue/sat** (not RGB), and
quantizes hue onto a coarse wheel — `qk80.py` compensates automatically so
`matrix color cyan` really shows cyan. Brightness below ~16% clamps to the
hardware floor (the matrix cannot go darker).

## Failsafe (Ctrl+C)

Uploads can be interrupted at any time with `Ctrl+C`. The tool always sends the
keyboard a **cancel command** (`0xE2` over CDC, `0xD1 0x22` over HID) before
releasing the serial port, so an interrupted transfer is aborted cleanly and
**never bricks the device** — the screen simply keeps whatever content was
last uploaded successfully, and you can retry. Verified: interrupting
mid-transfer sends `0xE2` and exits with a clear message, no traceback.

## Device identification

The tool matches the QK80 MK2 by its IDs over both transports:

| ID        | Value    |
|-----------|----------|
| Vendor ID | `0x514B` (`QK`) |
| Product ID| `0x4D02` (QK80 MK2) |
| Firmware  | `0x109`  |
| HID       | VIA raw endpoint, usage page `0xFF60` |
| CDC       | USB serial @ 115200 |

`qk80.py devices` lists what the computer actually sees on each bus and flags
the VIA HID endpoint, so you can confirm the keyboard is detected correctly.
The same check is used internally by the library via `qk80.probe_devices()`.

## Library API

This is the part other projects build on. Import `qk80.py` from your own
program, feed it any image, and let it handle encoding + transport:

```python
import qk80
from PIL import Image

# 1. Encode any image (PNG/JPG/GIF) to a display file
data = qk80.encode_abkg(Image.open("cover.png"))     # ABKT -> Themes screen
# data = qk80.encode_anim(frames, durations_ms)       # multi-frame
# data = qk80.encode_anps(frames, interval, anim)     # slideshow

# 2. Upload it (auto-detects the serial port; CDC, HID fallback available)
qk80.upload(data)                                    # Ctrl+C-safe
```

Other useful pieces:

* `qk80.encode_abkg(img, magic=b"ABKT")` / `b"ABKG"` — image (Themes / Apps)
* `qk80.encode_anim(frames, durations_ms, magic=b"ANIT")` / `b"ANIM"` — video
* `qk80.encode_anps(frames, interval_sec, anim, magic=b"ANPS")` / `b"ANPT"` — slideshow
* `qk80.gif_to_anim(gif, max_frames=500, magic=b"ANIM")` — encode a GIF file directly
* `qk80.album_to_anps(images, interval_sec, anim, magic=b"ANPS")` — encode an image list
* `qk80.set_matrix_color("cyan")` — Letters / Typewriter / Rain mode color
  (HID, persists); does NOT touch the Custom grid
* `qk80.set_matrix_custom("cyan")` / `qk80.set_matrix_pattern(pattern, "red")` /
  `qk80.reset_matrix()` — 7x7 Matrix LED Custom grid only (solid fill / manual
  grid / clear); never touches the mode color or effect
* `qk80.set_matrix_brightness(50)` / `qk80.set_matrix_effect("typewriter")` /
  `qk80.get_matrix_led()` — mode color/brightness/effect (HID, persists; same as
  the configurator's Lighting -> MATRIX LED sliders); brightness is 1-100
* `qk80.MATRIX_COLORS` — the color palette dict (`"red": (255, 0, 0)`, …);
  `qk80.parse_color(["#ff0000"])` parses a name / hex / `r g b` into `(r, g, b)`;
  `qk80.hsv256_to_rgb(h, s)` converts the hue/sat the firmware reports to RGB
* `qk80.encode_tabml(frames, fps, rows, cols)` — Matrix LED frame(s) → `tabml` file bytes
* `qk80.upload(data, transport="cdc", port=None, progress_cb=...)` — open → send → close
* `qk80.CDCTransport(port)` / `qk80.HIDTransport()` — low-level transports
  (`set_tab_file`, `set_matrix_lighting`, `set_matrix_led`, `get_matrix_led`, `cancel`)
* `qk80.probe_devices()` — structured list of detected QK80 MK2 devices

The pattern for any "feed this display" program is: **produce an image →
encode → upload**. See `examples/` for a now-playing and a current-game
starting point.

## Layout

| Path           | Purpose                                             |
|----------------|-----------------------------------------------------|
| `qk80.py`      | Encoders, transports and CLI (pure Python, no wasm) |
| `PROTOCOL.md`  | Reverse-engineered wire protocol + file formats     |
| `examples/`    | Starting points for building your own feeds         |
| `tests/`       | Sample media for trying the tool                    |
| `requirements.txt` | Python dependencies                              |
| `LICENSE`      | MIT license                                         |

## Notes

* Protocol and formats were reverse-engineered from the deployed
  `cfg.qwertykeys.com` bundle and cross-checked with the open-source
  `tabkb/cc` configurator — details in `PROTOCOL.md`.
* The routing table above was verified on a physical QK80 MK2. On firmware
  older than v1.1.0 the magic-based per-screen routing may not exist; if all
  uploads land on one screen, flash `qk80mk2_master_v1.1.1.uf2` + PLC v1.1.1
  (both are on the QK80 MK2 product page) via the bootloader.
