# QK80 MK2 / tabkb keyboard protocol

Reverse-engineered from the official configurator at `cfg.qwertykeys.com`
(the deployed JS bundle) and cross-checked against the open-source configurator
[`tabkb/cc`](https://github.com/tabkb/cc) (GPL-3.0). Verified on a physical
QK80 MK2 (`VID 0x514B, PID 0x4D02`).

Scope: talking to the keyboard, uploading LCD images/animations and Matrix LED
lighting, and the on-disk formats (`ABKT`/`ABKG`, `ANIT`/`ANIM`,
`ANPT`/`ANPS`, `tabml`). Firmware upload is described but the binary format of
the firmware image itself is unknown/private.

Reference implementation: the [`qk80`](qk80/) package (pure Python, no wasm);
run the CLI with `python -m qk80`.

---

## 1. Device identification

| Field      | Value    |
|------------|----------|
| Vendor ID  | `0x514B` (`QK`)  |
| Product ID | `0x4D02` (QK80 MK2) |
| Firmware   | `0x109` (from `GET_KEYBOARD_VALUE`, id 4) |
| Protocol   | 12 (from `GET_PROTOCOL_VERSION`) |

The keyboard exposes **two** USB interfaces:

1. **VIA raw HID** – usage page `0xFF60`, usage `0x61`. Handles keymap, macro,
   encoder, backlight (VIA-style), actuation (`0xD0`), date/time sync,
   Config -> Features (light power / sleep mode) and tab-block uploads.
2. **USB CDC (serial)** – 115200 baud, 64-byte packets. Used by the
   configurator for **tab files** (LCD image/animation, matrix lighting,
   firmware) when the device declares CDC support.

### Which transport does the configurator use?

`getTabFileAPI()`:

```js
return e.cdcSupport === undefined || e.cdcSupport === true
    ? new TabKeyboardAPI(e)          // CDC (WebSerial)
    : new KeyboardAPI(e.path)        // HID (WebHID)
```

`cdcSupport` comes from HID command `0xBF` (`TAB_CDC_SUPPORT`):
response byte after echo is `0xFF` ⇒ supported. QK80 MK2 answers `0x00 BF → 0x00 FF`,
so **the official app uploads LCD/matrix data over the serial port**.
The HID `0xD1` path is still implemented and works as a fallback.

---

## 2. Transport framing

### HID (VIA raw, 0xFF60)

* Reports are **33 bytes** on Windows (`report ID 0x00` + 32 payload);
  hidapi `write()` includes the report-ID byte.
* Command framing inside the 32-byte payload:

```
  byte 0   : command
  bytes 1..: arguments
  rest     : zero padding
```

* Response (read back 33 bytes, report ID again first):
  payload `[0]` echoes the command and `[1..]` echoes the arguments before any
  data/status bytes. Exception: tab-block responses (`0xD1`) echo `[0xFF, ...]`
  with the `0xD1` byte dropped (the two layout styles are handled in
  `qk80/transport.py`'s `HIDTransport._send`).
* Tab file chunk payload: 25 bytes per packet (inside the 32-byte payload).

### CDC (serial)

* 115200 baud, 8N1, 64-byte packets (padded).
* Command framing: `byte 0 = command, then arguments, zero-padded to 64`.
* Response: 64 bytes, same echo layout (`resp[0]` = command, `resp[1..]` =
  echoed arguments), with the first data byte carrying an error flag `0xEE`.
* Data chunks: **56 bytes** per packet (64 − 8 bytes of envelope).
* Flow control: some packets return a flag telling the host to wait for the
  response after **every** chunk (`resp[6]` for matrix, `resp[22]` for files).
  If set, read and verify the echo per chunk before sending the next one.

All multi-byte offsets/numbers are big-endian:
`numIntoBytes(n) = [n>>24, n>>16, n>>8, n]`.

---

## 3. HID command reference (VIA raw, 0xFF60)

### VIA standard commands

| Cmd  | Name                   | Request              | Response                    |
|------|------------------------|----------------------|-----------------------------|
| `0x01` | GET_PROTOCOL_VERSION | `[0x01]`             | `[0x01, 0x00, 0x0C]` (12)  |
| `0x02` | GET_KEYBOARD_VALUE  | `[0x02, id]`         | `[0x02, id, ...]` (id 4 → fw 0x0109) |
| `0x07` | CUSTOM_SET_VALUE    | `[0x07, ...]`        | VIA lighting / matrix-LED values |
| `0x08` | CUSTOM_GET_VALUE    | `[0x08, ...]`        | VIA lighting / matrix-LED values |
| `0x09` | CUSTOM_SAVE         | `[0x09, subsystem]`  | persist subsystem (e.g. `[0x09, 0x1A]`) |
| `0x0A` | EEPROM_RESET        | `[0x0A]`             |                             |
| `0x0B` | BOOTLOADER_JUMP     | `[0x0B]`             |                             |
| `0x0C` | GET_MACRO_COUNT     | `[0x0C]`             | `[0x0C, 0x10]` (16 macros) |
| `0x0D` | GET_MACRO_BUFFER_SIZE | `[0x0D]`           | `[0x0D, 0x0C, 0x07]` (3079 B) |
| `0x0E` | GET_MACRO_BUFFER    | `[0x0E, ...]`        | macro data (NOT display!)   |
| `0x0F` | SET_MACRO_BUFFER    | `[0x0F, ...]`        |                             |
| `0x10` | MACRO_RESET         | `[0x10]`             |                             |
| `0x11` | GET_LAYER_COUNT     | `[0x11]`             | `[0x11, 0x04]` (4 layers)  |
| `0x12` | GET_KEYMAP_BUFFER   | `[0x12, ...]`        | keymap data (NOT display!) |
| `0x13` | SET_KEYMAP_BUFFER   | `[0x13, ...]`        |                             |
| `0x14` | GET_ENCODER_BUFFER  | `[0x14, ...]`        |                             |
| `0x15` | SET_ENCODER_BUFFER  | `[0x15, ...]`        |                             |
| `0xBF` | TAB_CDC_SUPPORT     | `[0xBF]`             | `[0xBF, 0xFF]` ⇒ CDC supported |
| `0xD0` | TAB_ACTUATION       | `[0xD0, ...]`        | actuation settings          |
| `0xD1` | TAB_BLOCKS          | `[0xD1, sub, ...]`   | see below                   |

> Note: `0x0E`/`0x12` are macro/keymap buffers — they have **nothing** to do
> with the LCD. Sending image data there corrupts keyboard settings.

### `0xD1` TAB_BLOCKS (HID)

Upload a "tab block" in three phases: info, then buffer chunks, cancel at will.

**File (LCD image/animation):**

| Phase  | Payload                                    |
|--------|--------------------------------------------|
| info   | `[0xD1, 0x20, <first 20 bytes of file>]`   |
| buffer | `[0xD1, 0x21, offset(4 BE), len, chunk]`   |
| cancel | `[0xD1, 0x22]`                             |

`len` ≤ 25, `offset` = absolute byte offset of `chunk` in the file.
Response: last payload byte non-zero ⇒ error.

**Matrix LED:**

| Phase  | Payload                                          |
|--------|--------------------------------------------------|
| info   | `[0xD1, 0x30, frames, fps, rows, cols]`          |
| buffer | `[0xD1, 0x31, offset(4 BE), len, chunk]`         |
| cancel | `[0xD1, 0x22]`                                   |

`len` ≤ 25; `rows`/`cols` for QK80 MK2 = 7/7.

### Lighting / MATRIX LED values (`0x07`/`0x08`/`0x09`)

VIA custom values for backlighting and the Matrix LED. The QK80 MK2 Matrix
LED settings live in **subsystem `0x1A` (26)** — the exact values the
configurator's `Lighting -> MATRIX LED` Brightness slider, Effect dropdown
and Color picker use:

| Subsystem 26 sub | Meaning   | Set (`0x07`)                 | Get (`0x08`) returns        |
|------------------|-----------|------------------------------|-----------------------------|
| `0x01`           | Brightness| `[0x07, 0x1A, 0x01, value]`  | `[0x08, 0x1A, 0x01, value]` |
| `0x02`           | Effect    | `[0x07, 0x1A, 0x02, index]`  | `[0x08, 0x1A, 0x02, index]` |
| `0x04`           | Color     | `[0x07, 0x1A, 0x04, hue, sat]`| `[0x08, 0x1A, 0x04, hue, sat, 0]`|

Effect index (dropdown order): `0` All Off, `1` Typewriter, `2` Terminal,
`3` Raindrop, `4` Custom.

**Color is `[hue, sat]`, NOT RGB.** It is the same two bytes the
configurator's hue/sat color picker sends (`setColor(hue, sat)` where
`hue = round(255 * picker_hue_deg / 360)`, `sat = round(255 * picker_sat)`).
Both bytes are 0-255.

Firmware quirks (measured, uncompensated):

* **Hue wheel**: the mode color is stored on a coarse ~12-step wheel
  `{0, 21, 42, 64, 85, 106, 127, 149, 170, 192, 213, 234}` and any other hue
  byte is snapped UP to the next wheel step on readback; bytes above 234 pass
  through unchanged. `qk80/matrix.py` pre-compensates by rounding the hue to the
  nearest wheel step (`MATRIX_HUE_STEPS`), so setting e.g. cyan (hue 128)
  actually stores 127 and displays cyan instead of snapping to 149 (blue).
* **Brightness**: 0-255, but values below ~42 read back as 42 (a ~16 %
  hardware floor — the matrix cannot go darker), and values near the top read
  back 1-4 lower (e.g. 200 → 199, 220 → 216). The CLI takes 1-100 % and maps
  to `round(percent * 255 / 100)`.

After setting one or more values, persist them with `[0x09, 0x1A]`
(`CUSTOM_SAVE` for subsystem 26). The response echoes `[cmd, ...args]` then
the value bytes; `0x09` is the only way these settings survive a power
cycle.

These commands apply to the Letters / Typewriter / Rain modes. The Custom
mode's grid is set separately via the matrix transfer (CDC `0xC0`/`0xC1` or
HID `0xD1 0x30`/`0x31`) — see below.

### Date & Time sync (`0x07`/`0x09`, subsystem 25)

The configurator's `Config -> Date and Time -> Time Sync` button (`TimeSyncItem`
in the deployed bundle) sends two HID commands:

| Cmd  | Payload                                | Meaning |
|------|----------------------------------------|---------|
| `0x07` | `[0x07, 0x19, t0, t1, t2, t3]`      | set clock to Unix timestamp `t` (4 bytes BE) |
| `0x09` | `[0x09, 0x19]`                       | persist subsystem 25 (survives power cycle) |

The timestamp is the **local wall-clock time as Unix seconds** — the app
computes `floor(Date.now()/1000) - Date.getTimezoneOffset()*60` — because the
firmware clock has no timezone handling and displays the value it is given
directly. There is no read-back (`0x08` is never used for subsystem 25).

Same command path as the matrix-LED values above (VIA `0x07`/`0x09` over the
HID endpoint, regardless of CDC support), so it works with the identical
`_send` echo logic in `qk80/transport.py`'s `HIDTransport.sync_time`.

### Config -> Features (`0x07`/`0x08`/`0x09`, subsystem 17)

The QK80 MK2 definition (`def_qk80mk2.json`) lists a `Config -> Features`
menu backed by VIA custom-value subsystem `0x11` (17). Each control is an
`(option, value)` pair sent with the same `0x07`-set / `0x09`-save pattern as
subsystems 25/26; unlike time sync there **is** a read-back (`0x08`):

| Option | Control      | Set (`0x07`)                    | Get (`0x08`) returns   |
|--------|--------------|---------------------------------|------------------------|
| `0x01` | Light Power  | `[0x07, 0x11, 0x01, 0|1]`       | `[0x08, 0x11, 0x01, 0|1]` |
| `0x02` | Sleep Mode   | `[0x07, 0x11, 0x02, index]`     | `[0x08, 0x11, 0x02, index]` |

Sleep Mode index: `0` Disable, `1` 5 min, `2` 15 min, `3` 30 min, `4` 1 h,
`5` 3 h, `6` 6 h. Light Power is a toggle: `1` = on, `0` = off.

Both persist with `[0x09, 0x11]` (`CUSTOM_SAVE` for subsystem 17), the same as
the matrix-LED values and the clock. (The same subsystem also carries Debounce
Mode `0x06` / Debounce Delay `0x07`, not implemented here.)


**Firmware:**

| Phase  | Payload                                        |
|--------|------------------------------------------------|
| info   | `[0xD1, 0x10, size(4 BE), f12..15, f16..19, f24..27, f28..31]` |
| buffer | `[0xD1, 0x11, offset(4 BE), len, chunk]`       |

`len` ≤ 16. The info packet also validates the firmware file: two big-endian
magics at file offsets 0..3 and 4..7 (byte-reversed) must match constants in
the app, otherwise the upload is refused before it starts.

---

## 4. CDC command reference (USB serial)

Used for everything under "tab" when `0xBF` returns support.

| Cmd  | Name                   | Payload                          | Error flag |
|------|------------------------|----------------------------------|------------|
| `0xC0` | TAB_MATRIX_SET_INFO   | `[0xC0, frames, fps, rows, cols]` | `resp[5]` |
| `0xC1` | TAB_MATRIX_SET_BUFFER | `[0xC1, offset(4 BE), len, chunk]`| —          |
| `0xE0` | TAB_FILE_SET_INFO     | `[0xE0, <first 20 bytes of file>]`| `resp[21]` |
| `0xE1` | TAB_FILE_SET_BUFFER   | `[0xE1, offset(4 BE), len, chunk]`| —          |
| `0xE2` | TAB_FILE_SET_CANCEL   | `[0xE2]`                          | —          |
| `0xEF` | FIRMWARE_QUERY        | `[0xEF]`                          | —          |
| `0xF0` | FIRMWARE_SET_INFO     | `[0xF0, size(4 BE), <32-byte header>]` | `resp[size+1]` |
| `0xF1` | FIRMWARE_SET_BUFFER   | `[0xF1, offset(4 BE), len, chunk]` | —          |

* `chunk` ≤ 56 bytes. `offset` is absolute and big-endian.
* Flow control: if `resp[22]` (file) / `resp[6]` (matrix) is non-zero, wait for
  a response echo after every buffer chunk.
* First data byte is `0xEE` on error (see Error flag column).

Matrix buffer data is **HSV**, not RGB (see §6). File data is the raw file
bytes (`ABKG`/`ANIM`).

---

## 5. LCD file formats (verified byte-for-byte vs `kbres.wasm`)

Both formats are a small header followed by **raw RGB565** pixels, row-major,
top-down. RGB565 conversion uses truncation:

```
r5 = r >> 3, g6 = g >> 2, b5 = b >> 3
pixel = (r5 << 11) | (g6 << 5) | b5
```

### ABKG (static image) — 320×172, 110,100 bytes

```
offset  size  field
0       4     magic "ABKG"
4       2     u16 = 20
6       2     u16 = 20          (header size)
8       4     u32 total file size
12      2     u16 width  = 320
14      2     u16 height = 172
16      2     u16 = 0
18      2     u16 = 1           (frame count)
20      —     w*h*2 bytes RGB565
```

### ANIM (animation) — N frames of 320×172

```
offset  size  field
0       4     magic "ANIM"
4       2     u16 = 20
6       2     u16 = 20 + 2*N    (header size, 36 for 8 frames)
8       4     u32 total file size
12      2     u16 width
14      2     u16 height
16      2     u16 = 0
18      2     u16 = N           (frame count)
20      2*N   u16 durations (ms per frame)
20+2*N  —     N * (w*h*2) bytes RGB565 frames, concatenated
```

The official configurator limits `N` to the per-device `animFramesLimit`
(500 for QK80 MK2 ANIM). Encoding is done by `kbres.wasm` (`convert_image_ext`
/ `convert_video_ext`); the pure-Python encoder in `qk80/encoders.py` produces
byte-identical output.

### ANPS / ANPT (slider, album/slideshow) — N frames of 320×172

```
offset  size  field
0       4     magic "ANPS" (custom) or "ANPT" (theme)
4       2     u16 = 20
6       2     u16 = 24          (header size)
8       4     u32 total file size
12      2     u16 width
14      2     u16 height
16      2     u16 = 0
18      2     u16 = N           (frame count)
20      2     u16 interval      (seconds per slide: 5, 10, 15, 30)
22      2     u16 transition    (1 none, 2 down, 3 up, 4 right, 5 left)
24      —     N * (w*h*2) bytes RGB565 frames, concatenated
```

Generated by `convert_image_folder_ext`; each album image is scaled/cropped
to the output size. Verified byte-for-byte in `qk80/encoders.py` (`encode_slider`,
`album_to_slider`).

### QK80 MK2 import paths (Screen tab)

| UI menu                | Format   | `python -m qk80` command               |
|------------------------|----------|----------------------------------------|
| Video → Theme (default)| ANIT     | `python -m qk80 video anim.gif`        |
| Video → Custom Animation| ANIM    | `python -m qk80 video anim.gif --variant custom` |
| Image → Theme (default)| ABKT     | `python -m qk80 image photo.png`       |
| Image → Custom Image   | ABKG     | `python -m qk80 image photo.png --variant custom` |
| Slider → Custom Slider (default)| ANPS | `python -m qk80 slider 1.png 2.png ...` |
| Slider → Theme         | ANPT     | `python -m qk80 slider ... --format ANPT` |

Note (user-verified on device): the magic alone decides the destination screen.
The "Theme" variants (`ANIT`/`ABKT`/`ANPT`) populate the **Themes → Default
Theme** screen; the "Custom" variants (`ANIM`/`ABKG`/`ANPS`) populate the
**Apps → Custom Animation** screen. `image`/`video` therefore default to the
Theme variant and `slider` to the Custom variant so the CLI matches that
routing. All variants are uploaded the same way: the bytes are sent verbatim
through `setTabFile` (CDC `0xE0`/`0xE1`, HID `0xD1 0x20/0x21`).

---

## 6. Matrix LED file format & upload data

QK80 MK2 has a 7×7 Matrix LED zone (`matrixLighting: {rows:7, cols:7, cdc:true}`).

**The CLI (`python -m qk80`) controls two independent parts of the matrix:**

1. **Mode settings** — color, brightness and the active effect are the
   configurator's `Lighting -> MATRIX LED` settings (VIA custom values, HID
   subsystem `26`; see the `0x07`/`0x08`/`0x09` table in §3). They persist
   across power cycles after a `0x09` save:
   `python -m qk80 matrix color cyan`, `python -m qk80 matrix brightness 50`,
   `python -m qk80 matrix effect raindrop`, `python -m qk80 matrix get`.
   `matrix color` (and the bare-colorname shorthand `python -m qk80 matrix cyan`)
   sets only the Letters / Typewriter / Rain mode color — it never touches
   the Custom grid.
2. **Custom grid** — the 7×7 grid itself, uploaded as a frame over
   `0xC0`/`0xC1` (or HID `0xD1 0x30`/`0x31`): solid colors
   (`python -m qk80 matrix custom cyan`), manual patterns
   (`matrix custom --pattern ... --color red`), and a factory reset
   (`matrix custom reset` / `matrix reset` — a blank all-off grid).
   Image/video uploads to the matrix are **not** supported.

The two are independent: setting the mode color never touches the Custom grid,
and uploading a Custom grid never changes the Letters/Typewriter/Rain colors.

### `tabml` file (import/export)

32-byte header + raw **RGB888** per LED per frame:

```
offset  size  field
0       5     magic "tabml"
5       1     frames
6       1     fps
7       1     rows
8       1     cols
9       23    zero padding
32      —     frames * rows * cols * 3 bytes RGB
```

### Upload data (over 0xC0/0xC1)

For the keyboard upload path the configurator does **not** send RGB; it
converts each LED to HSV scaled to 0–255 and sends `[H, S, V]` per LED per
frame (`get256HSV`), matching the firmware's internal HSV colour handling:

```
H = round(255 * hue/360),  S = round(255 * sat),  V = round(255 * value)
```

---

## 7. Actuation (0xD0)

`0xD0` carries actuation parameters (Rapid Trigger-style config). Observed
pattern: `[0xD0, mode, ...]` over the HID endpoint. Exact parameter layout is
device-dependent and not needed for LCD/Matrix work.

---

## 8. Provenance & verification

* **Sources**: deployed bundle at `cfg.qwertykeys.com` (definitive for the
  current device) and `github.com/tabkb/cc` (`src/utils/hid-api.ts`,
  `cdc-api.ts`, `hid.ts`, `bit-pack.ts`, `color-math.ts`, `screenSlice.ts`,
  `matrixLightingSlice.ts`, `src/utils/kbres/*`). The firmware
  (`tabkb/qmk_firmware` fork) only contains `qk100`/`qk65` — **QK80 MK2
  firmware is not public**.
* **Format verification**: `kbres.wasm` from the repo is byte-identical to the
  deployed one (6,810,636 bytes). Running `convert_image_ext`/`convert_video_ext`
  in Node produced ABKG/ANIM files that `qk80/encoders.py` reproduces **byte-for-byte**,
  including the 320×172 gradient (110,100 B) and 8-frame animation (880,676 B).
* The 77×40 palette image model and HID commands `0x0E`/`0x12` in earlier
  drafts were incorrect (those are macro/keymap buffers).
