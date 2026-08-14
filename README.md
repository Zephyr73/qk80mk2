# QK80 MK2 — screen & Matrix LED uploader

Upload images, GIFs and slideshows to the QK80 MK2's 320x172 LCD, and control
its 7x7 Matrix LED — from the command line or from your own Python programs.
No browser, no wasm: the same files the official configurator
(cfg.qwertykeys.com) produces, byte-for-byte, sent over the same protocol.

## 1. Project vision

A small host-side SDK + CLI for the QK80 MK2. Give it any image and it handles
the encoding and transport; the library API makes it easy to build "feed this
display" programs:

* **Current-game detection** — show the Steam header of the game in focus
  (`examples/current_game.py`)
* **Now playing** — album art of the track you're listening to
  (`examples/now_playing.py`)
* **Stats / uptime tickers** — a dashboard on your desk
* **Slideshows** — albums, photos, anything

Both displays are covered: the 320x172 LCD (images, animations, sliders) and
the 7x7 Matrix LED (mode color/brightness/effect + custom 49-LED grid).

```
python -m qk80 image  tests/black.png      # image  -> Themes -> Default Theme
python -m qk80 video  tests/anim.gif       # GIF    -> Themes -> Default Theme
python -m qk80 slider tests/black.png tests/red.png   # album -> Apps -> Custom Animation
```

This started as a personal project, and it's shared as a **learning resource**:
the protocol reverse-engineering (`PROTOCOL.md`), the encoder byte layouts, and
the library API are all documented so you can understand how it works, use it in
your own programs, or build on top of it. Fork it, borrow the code, or open a PR
— it's MIT-licensed.

The code was developed with the help of AI assistants as pair-programming
partners (design, implementation, and review). It's intentionally written to be
readable: comments explain the *why* (for example the firmware hue-wheel
compensation quirk in the code), so you can trace how the pieces fit together
and take them into your own projects.

## 2. Quick start

```powershell
# 1. Get the code and install it (creates .venv with deps + this package)
git clone https://github.com/Zephyr73/qk80mk2.git
cd qk80mk2
uv sync

# 2. Upload a black 320x172 image to the Themes screen
.venv\Scripts\qk80 image tests\black.png
```

That uploads a black 320x172 image to the Themes screen. Plug in the keyboard
and the browser configurator must be closed (see Prerequisites). After
installation both `qk80 ...` and `python -m qk80 ...` work — every example in
this README uses the latter form.

## 3. Prerequisites

* **git** (to clone the repo)
* **Python 3.10+** — [uv](https://docs.astral.sh/uv/) recommended (see
  `.python-version`); plain `pip` works too (see Installation)
* A **QK80 MK2** plugged in via USB
* **`cfg.qwertykeys.com` closed** — the browser tab holds the serial port; this
  tool fails with a port-open error until you close it
* **Windows** works out of the box (the `hidapi` wheel bundles its native
  driver). On **macOS/Linux** the `hidapi` Python package needs the system HID
  library first, e.g. `sudo apt install libhidapi-hidraw0` on Debian/Ubuntu
  (`brew install hidapi` on macOS). The serial port shows up as `/dev/ttyACM*`.

## 4. Installation

The project is a proper installable package (`qk80`), so pick whichever tool
you already use. Both create a virtual environment and install the dependencies
**plus this package**, which is what makes `import qk80` work from any
directory and provides the `qk80` command.

**Option A — uv (recommended):**

```powershell
git clone https://github.com/Zephyr73/qk80mk2.git
cd qk80mk2
uv sync                          # creates .venv, installs deps + this package
.venv\Scripts\qk80 devices       # confirm the keyboard is detected
```

**Option B — plain pip:**

```powershell
git clone https://github.com/Zephyr73/qk80mk2.git
cd qk80mk2
python -m venv .venv
.venv\Scripts\pip install -e .   # editable install: deps + this package
.venv\Scripts\qk80 devices
```

On macOS/Linux the scripts live in `.venv/bin/` (`source .venv/bin/activate`
and then `qk80 devices`, or `.venv/bin/qk80 devices`).

Dependencies: `Pillow` (image handling), `pyserial` (CDC), `hidapi` (HID
fallback). They are declared in `pyproject.toml` and locked in `uv.lock`, so
`uv sync` / `pip install .` fetch them for you — there is no manual step.

## 5. Using qk80 in your own Python project

`qk80` is a normal installable package, so you can import it from any of your
own scripts or projects:

**a) Install this repo into your environment** (once):

```powershell
pip install git+https://github.com/Zephyr73/qk80mk2.git
# or, from a local clone:  pip install -e ./qk80mk2
```

Then `import qk80` works from anywhere:

```python
import qk80
from PIL import Image

# Encode + upload an image to the Themes screen (CDC auto-detect, Ctrl+C-safe)
data = qk80.encode_image(Image.open("cover.png"))
qk80.upload(data)

# Matrix LED: mode color (HID, persists) + a custom 7x7 grid pattern
qk80.set_matrix_color("cyan")
qk80.set_matrix_pattern([".......", "...X...", "..XXX..", ".XXXXX.",
                         "XXXXXXX", ".XXXXX.", "..X.X.."], "red")

# See what the computer sees
print(qk80.probe_devices())
```

**b) Declare it as a dependency** in your own `pyproject.toml`:

```toml
[project]
dependencies = ["qk80 @ git+https://github.com/Zephyr73/qk80mk2.git"]
```

**c) Or just copy the `qk80/` folder** into your project — it is fully
self-contained; the only runtime dependencies are `Pillow`, `pyserial`, and
`hidapi` (see [section 7](#7-library-api-reference) for the full API).

The general pattern for any "feed this display" program is: **produce an image
→ encode → upload** ([section 8](#8-examples) has two working templates).

## 6. CLI reference

All commands upload to the keyboard by default. After installation you can call
the tool either as `qk80 ...` or `python -m qk80 ...`. Every command accepts
these common flags:

| Flag | Meaning |
|------|---------|
| `--transport cdc\|hid` | transport (default `cdc`; `hid` uses the VIA HID fallback) |
| `--port COMx` | pick a serial port (CDC only; auto-detected by default) |
| `--save FILE` | also write the encoded file (in addition to uploading) |
| `--no-upload` | encode only, never touch the keyboard |
| `--upload` | upload (this is the default; mutually exclusive with `--no-upload`) |

> `matrix color` (and the bare-colorname shorthand `matrix cyan`) /
> `matrix effect` / `matrix brightness` / `matrix get` always use the HID
> transport — `--transport` is ignored for them.

### `devices` — what the computer sees

```powershell
.venv\Scripts\python -m qk80 devices
```

Lists the QK80 MK2's CDC port and every HID interface, flagging the VIA raw
endpoint (`usage_page 0xFF60`) used by the HID transport.

### `image` — PNG/JPG → LCD image

`src` is the image file. `--variant` picks the destination screen:
`theme` = ABKT → **Themes → Default Theme** (default), `custom` = ABKG →
**Apps → Custom Animation**.

```powershell
.venv\Scripts\python -m qk80 image tests\black.png                   # ABKT (Themes)
.venv\Scripts\python -m qk80 image tests\gradient.png --variant custom  # ABKG (Apps)
.venv\Scripts\python -m qk80 image photo.png --no-upload --save out.abkt
```

### `video` — GIF → LCD animation

`src` is an animated GIF. `--max-frames` caps the frame count (firmware limit
is 500); `--variant` picks the screen: `theme` = ANIT (default), `custom` =
ANIM.

```powershell
.venv\Scripts\python -m qk80 video tests\anim.gif                    # ANIT (Themes)
.venv\Scripts\python -m qk80 video tests\anim.gif --variant custom   # ANIM (Apps)
.venv\Scripts\python -m qk80 video clip.gif --max-frames 300
```

### `slider` — album/slideshow

Takes any number of image files, sorted by name like the app does.

```powershell
.venv\Scripts\python -m qk80 slider tests\black.png tests\red.png --interval 10
.venv\Scripts\python -m qk80 slider 1.png 2.png 3.png --format ANPT --anim 3
```

> PowerShell does **not** expand `*.png` for native commands, so list the files
> explicitly (or expand with `Get-ChildItem`). `cmd.exe` expands them for you.

| Flag | Default | Meaning |
|------|---------|---------|
| `--interval` | `5` | seconds per slide (`5`, `10`, `15`, `30`) |
| `--anim` | `1` | transition: `1` none, `2` down, `3` up, `4` right, `5` left |
| `--format` | `ANPS` | `ANPS` = custom slider → Apps → Custom Animation, `ANPT` = theme slider → Themes → Default Theme |

### `matrix` — 7x7 Matrix LED

Two independent parts: the **mode settings** (color / brightness / effect,
which apply to the Letters / Typewriter / Rain modes) and the **Custom grid**
(the 49-LED pattern). Setting a mode setting never touches the Custom grid,
and editing the Custom grid never changes the mode settings.

**Mode settings** (HID, persist across power cycles — the same values as the
configurator's `Lighting -> MATRIX LED` sliders):

```powershell
.venv\Scripts\python -m qk80 matrix color red            # mode color: name, #rrggbb, or r g b
.venv\Scripts\python -m qk80 matrix color "#00ff00"
.venv\Scripts\python -m qk80 matrix color 255 128 0
.venv\Scripts\python -m qk80 matrix brightness 50        # 1-100%
.venv\Scripts\python -m qk80 matrix effect raindrop      # off/typewriter/terminal/raindrop/custom
.venv\Scripts\python -m qk80 matrix get                  # print current values
```

`matrix color` (or a bare color name — `matrix cyan`) sets only the
Letters / Typewriter / Rain mode color; the Custom grid is left as it is.

**Custom grid** (the 49-LED pattern, uploaded over `0xC0`/`0xC1`):

```powershell
.venv\Scripts\python -m qk80 matrix custom cyan                         # fill all 49 LEDs cyan
.venv\Scripts\python -m qk80 matrix solid --color cyan                  # same, explicit
.venv\Scripts\python -m qk80 matrix custom --color red --pattern "......." "..X.X.." ".XXX.X." "XXXXXXX" ".XXXXX." "..XXX.." "...X..."
.venv\Scripts\python -m qk80 matrix custom reset                        # factory default (all off)
.venv\Scripts\python -m qk80 matrix reset                               # same, shorthand
.venv\Scripts\python -m qk80 matrix custom --pattern "..X..X." "......." "X..X..X" ".XXXXX." ".XXXXX." "..XXX.." "..X.X.." --no-upload --save grid.tabml
```

`--pattern` takes 7 rows of 7 characters: `.` = LED off, any other character =
LED on in `--color`. `--color` accepts the palette `red orange yellow green
cyan blue magenta purple white off` (default `white`).

Notes on the mode color: the firmware stores it as **hue/sat** (not RGB), and
quantizes hue onto a coarse wheel — the tool compensates automatically so
`matrix color cyan` really shows cyan. Brightness below ~16% clamps to the
hardware floor (the matrix cannot go darker).

## 7. Library API reference

This is the part other projects build on. Import the `qk80` package from your
own program, feed it any image, and let it handle encoding + transport:

```python
import qk80
from PIL import Image

# 1. Encode any image (PNG/JPG/GIF) to a display file
data = qk80.encode_image(Image.open("cover.png"))     # ABKT -> Themes screen

# 2. Upload it (auto-detects the serial port; CDC, HID fallback available)
qk80.upload(data)                                    # Ctrl+C-safe
```

### Encoders

| Function | Default | Produces |
|----------|---------|----------|
| `encode_image(img, magic=b"ABKT")` | Themes | ABKT / ABKG — single image |
| `encode_video(frames, durations_ms, magic=b"ANIT")` | Themes | ANIT / ANIM — multi-frame animation |
| `gif_to_video(gif, max_frames=500, magic=b"ANIT")` | Themes | ANIT / ANIM — encode a GIF directly |
| `encode_slider(frames, interval_sec, anim, magic=b"ANPS")` | Apps | ANPS / ANPT — slideshow |
| `album_to_slider(images, interval_sec, anim, max_frames=500, magic=b"ANPS")` | Apps | ANPS / ANPT — encode an image list |
| `encode_tabml(frames, fps, rows, cols)` | — | `tabml` — Matrix LED file bytes |
| `to_rgb565(img)` | — | raw RGB565 bytes, row-major (the low-level pixel conversion) |
| `matrix_hsv_data(frames, rows, cols)` | — | RGB frames → the HSV bytes uploaded to the matrix (`[H,S,V]` per LED per frame) |

Every encoder takes an optional `magic=` to send content to the *other* screen:
`encode_image(img, magic=b"ABKG")` lands on Apps, `gif_to_video(gif, magic=b"ANIM")`
on Apps, `encode_slider(frames, 5, 1, magic=b"ANPT")` on Themes.

### Matrix LED helpers

| Function | Effect |
|----------|--------|
| `set_matrix_color("cyan")` | Letters / Typewriter / Rain mode color (HID, persists); does NOT touch the Custom grid |
| `set_matrix_custom("cyan")` | Custom grid solid fill (color name, `#rrggbb`, or `r g b`) |
| `set_matrix_pattern(pattern, "red")` | Custom grid manual pattern (7 strings of 7 chars, `.` = off) |
| `reset_matrix()` | Custom grid factory default (all off) |
| `set_matrix_brightness(50)` | Mode brightness, 1-100 (HID, persists) |
| `set_matrix_effect("typewriter")` | Mode: off/typewriter/terminal/raindrop/custom |
| `get_matrix_led()` | `{"brightness": 0-255, "effect": int, "effect_name": str, "color": (hue, sat)}` |

Low-level building blocks (used by the helpers above; useful for custom
uploads or embedding the payloads in your own files):

| Function | Effect |
|----------|--------|
| `matrix_solid_hsv("cyan")` | one 7x7 HSV frame with all 49 LEDs in `color` |
| `matrix_blank_hsv()` | one 7x7 HSV frame, all LEDs off (the factory default) |
| `matrix_pattern_rgb(pattern, "red")` | 7×7 char pattern → list of 49 RGB pixels |
| `matrix_pattern_hsv(pattern, "red")` | 7×7 char pattern → HSV upload bytes |
| `MATRIX_HUE_STEPS` | the firmware's coarse hue wheel (see the note in the CLI `matrix` section) |

The mode-color helpers never touch the Custom grid, and the grid helpers never
change the mode color or effect.

### Transports & helpers

* `upload(data, transport="cdc", port=None, progress_cb=...)` — open → send → close
* `CDCTransport(port)` / `HIDTransport()` — low-level transports; usable as
  context managers (`with CDCTransport() as t:`). Both expose `set_tab_file(data, progress)`
  / `set_matrix_lighting(frames, fps, rows, cols, data, progress)` and `cancel()`
  (used on Ctrl+C / errors so the keyboard never gets stuck)
* `HIDTransport().set_matrix_led(brightness=, effect=, color=(hue, sat))` — the
  raw HID 0x07 call behind the mode-color helpers (values persist)
* `probe_devices()` — structured list of detected QK80 MK2 devices
* `parse_color(["#ff0000"])` / `parse_color(["255", "0", "0"])` — color spec → `(r, g, b)`
* `rgb_to_hsv256(r, g, b)` / `hsv256_to_rgb(h, s, v=255)` — RGB ↔ HSV (0-255)
* `MATRIX_COLORS` — the color palette dict; `MATRIX_LED_EFFECTS` — mode names
* `resize_cover(img)` — scale-to-cover 320x172 center crop
* `Progress(callback=cb)` — tiny transfer-progress counter (`total`, `done`,
  `step(n)`); pass it to a transport's `set_tab_file` for upload progress

Progress example:

```python
import qk80
from PIL import Image

def on_progress(done, total):
    print(f"\r{done * 100 // total}%", end="")

qk80.upload(qk80.encode_image(Image.open("cover.png")),
            progress_cb=on_progress)
```

### Constants

Everything tunable lives in `qk80.constants` (re-exported from `qk80`), so a
fork can change the board it targets without touching logic:

| Constant | Value | Meaning |
|----------|-------|---------|
| `SCREEN_W` / `SCREEN_H` | `320` / `172` | LCD resolution; images are scaled to this |
| `MATRIX_ROWS` / `MATRIX_COLS` | `7` / `7` | Matrix LED grid size |
| `VENDOR_ID` / `PRODUCT_ID` | `0x514B` / `0x4D02` | QK80 MK2 USB IDs (env `QK80_VID` / `QK80_PID`) |
| `DEVICE_NAME` | `"QK80 MK2"` | shown in messages (env `QK80_NAME`) |
| `VIA_USAGE_PAGE` | `0xFF60` | the HID raw endpoint the HID transport uses |
| `ANIM_TRANS_NONE` / `_DOWN` / `_UP` / `_RIGHT` / `_LEFT` | `1..5` | slider transition enum |
| `MATRIX_LED_EFFECTS` | `("off", "typewriter", "terminal", "raindrop", "custom")` | matrix mode names |
| `MATRIX_LED_CHANNEL` | `26` | VIA Lighting → MATRIX LED subsystem |
| `BAUD` / `CDC_CHUNK` / `HID_CHUNK` | `115200` / `56` / `25` | transport framing |

The protocol constants (command bytes `0xC0/0xC1/0xE0/0xE1/0xE2`, `0xD1` blocks,
the 0x07/0x08/0x09 LED values, `ERR_FLAG`) are documented in PROTOCOL.md and
defined verbatim in `qk80/constants.py`.

The pattern for any "feed this display" program is: **produce an image →
encode → upload**. See [Examples](#8-examples) for starting points.

## 8. Examples

Both examples are templates — extend them for your own feeds.

**`current_game.py`** — shows the focused game's Steam header on the Themes
screen (Windows). Maintain a `GAMES` dict of window-title fragment → Steam
appid, put the game in the foreground, run:

```powershell
.venv\Scripts\python examples\current_game.py
```

**`now_playing.py`** — shows album art on the Themes screen. Fill in
`get_cover_url()` with your music player's integration (mpd/mopidy, Spotify,
etc.), or pass a file/URL directly:

```powershell
.venv\Scripts\python examples\now_playing.py cover.jpg
.venv\Scripts\python examples\now_playing.py https://example.com/cover.png
```

Both are Ctrl+C-safe — the keyboard receives a cancel command.

## 9. Architecture

| Path | Purpose |
|------|---------|
| `qk80/` | The library package: `constants` (protocol), `encoders` (byte formats), `matrix` (7x7 helpers), `transport` (CDC/HID), `api` (high-level), `cli` (`python -m qk80`) |
| `examples/` | Starting points for building your own feeds |
| `tests/` | Sample media for trying the tool |
| `pyproject.toml` / `uv.lock` | Installable package (`hatchling`): deps, the `qk80` console entry point, locked versions (`uv`) |
| `PROTOCOL.md` | Reverse-engineered wire protocol + file formats |
| `LICENSE` | MIT license |

The pipeline: **encode** (scale → RGB565/HSV → header + magic) → **upload**
(CDC `0xE0`/`0xE1`/`0xC0`/`0xC1` or HID `0xD1` fallback) → done. The 4-byte
*magic* in the file header decides which screen the firmware uses; there is no
extra "which screen" command, so a byte-identical upload from this tool is
indistinguishable from one done in the browser.

## 10. Troubleshooting / FAQ

**"could not open port"** — `cfg.qwertykeys.com` is open in a browser and holds
the serial port. Close the tab (or unplug/replug the keyboard), then retry.

**"QK80 MK2 serial port not found"** — the keyboard isn't detected. Plug it in,
or pass `--port COMx` (`python -m qk80 devices` shows the port).

**"bad HID echo" / transport errors** — the `hid` transport needs the VIA raw
endpoint (`usage_page 0xFF60`); `python -m qk80 devices` flags it.

**Uploads land on the wrong screen** — magic-based per-screen routing needs
firmware >= v1.1.0. If everything lands on one screen, flash
`qk80mk2_master_v1.1.1.uf2` + PLC v1.1.1 (both on the QK80 MK2 product page)
via the bootloader.

**Matrix brightness looks wrong below ~16%** — the firmware clamps to a
hardware floor; the matrix physically cannot go darker.

**`matrix color cyan` looks blue?** — the firmware quantizes hue onto a coarse
wheel; the tool pre-compensates, so it should show cyan. If a custom color
round-trips oddly, it's the same quantization.

**Ctrl+C mid-upload** — safe. The tool sends a cancel command (`0xE2` / `0xD1
0x22`) before releasing the port; the screen keeps the last successful upload
and you can retry. It never bricks the device.

## 11. Using with another keyboard / forking

Nothing about the *device* is hardcoded. The protocol this tool speaks is the
one used by the `tabkb/cc` open-source configurator; any board that speaks it
can be driven by a fork of this repo. To point it at a different board:

* **Different vendor/product IDs** — set `QK80_VID` / `QK80_PID` (hex or
  decimal) before running, or edit `VENDOR_ID` / `PRODUCT_ID` in
  `qk80/constants.py`:

  ```powershell
  $env:QK80_VID = "0x514B"; $env:QK80_PID = "0x4D02"
  .venv\Scripts\python -m qk80 devices
  ```

* **Different product name in messages** — `QK80_NAME` env var or the
  `DEVICE_NAME` constant.

* **Detection** — `python -m qk80 devices` lists the CDC port and every HID interface
  of your device; the HID transport needs the VIA raw endpoint
  (`usage_page 0xFF60`, flagged `<-- VIA raw (HID transport)`). Boards whose
  firmware is based on the same `tabkb/cc` code will have it.

* **Screen size / layout** — `SCREEN_W` / `SCREEN_H` in `qk80/constants.py`
  scale images to the panel; change them for a different resolution.

## 12. Protocol reference

The wire protocol and on-disk file formats were reverse-engineered from the
deployed `cfg.qwertykeys.com` bundle and cross-checked with the open-source
`tabkb/cc` configurator. See **PROTOCOL.md** for the full low-level details:
command bytes, packet layouts, magic routing table, and the Matrix LED HID
subsystem.
