# QK80 MK2 Firmware Reverse Engineering Notes

> Status: early reverse engineering. Findings below were extracted with `uf2_extract.py`
> and `fw_analyze.py` from the vendor firmware images the user supplied.
> Everything is marked with the flash addresses where it was found so it can be
> re-verified and used as a reference for building a fork.

## Images

| Image | File (user-supplied) | App flash base | Size |
|---|---|---|---|
| Mainboard (master) | `qk80mk2_master_v1.1.1_20250321_b525ad55-*.uf2` | `0x00027000` | 113,920 B |
| Screen (PLC) | `qk80mk2_plc_v1.1.1_20250321_da133fbf-*.uf2` | `0x08008000` | 714,752 B |

Both firmware images are shipped in the **UF2** format, but it is a *vendor variant*
of UF2, not the standard format. Details in `uf2_extract.py`.

### UF2 variant (both images)
- Two start magics: `0x0A324655` at +0 and `0x9E5D5157` at +4.
- Header: flags +8, target addr +12, payload size +16 (**256 B**, not 476), blockNo +20,
  numBlocks +24, familyID +28, payload +32.
- Stride = 512 bytes; no end magic. `numBlocks` is authoritative.
- Family IDs: master `0x514B4D02` (`"\x02QMK"`), PLC `0x514B4D50` (`"PQMK"`).

## MCUs

### Screen (PLC) — `fw_analyze.py::load_plc`
- **ARM Cortex-M4F** (MemManage/BusFault/UsageFault vectors present; M0 has none).
- Vendor layout consistent with **Artery AT32F435/AT32F437** class:
  - 512 KB SRAM at `0x20000000..0x20080000` (MSP `0x20080000`; reset handler zeroes
    .bss up to `0x2001EAA0`).
  - ~1 MB flash at `0x08000000` (code references flash-end `0x08100000`).
  - OTG/USB at `0x50000000`, F4-style peripheral bases (RCC `0x40023800`,
    GPIOA `0x40020000`, USART3 `0x40004800`).
- Vector table: real handlers for the core exceptions (`0x08040B5D` etc.); every
  IRQ slot points to the shared default handler `0x080449B0`. So no interesting
  IRQ hooks besides the core ones.
- Reset handler `0x08044968`: copies `.data` from `0x080B5E38`, zeroes `.bss`
  `0x20000920..0x2001EAA0`, then `SystemInit 0x08041450` → `crt 0x08008240` → `main 0x080161B4`.

### Mainboard (master) — `fw_analyze.py::load_master`
- **ARM Cortex-M0 class** (words 4..10 of the vector table are zero), consistent with
  the Sonix SN32F26x keyboard controller found in earlier research.
- App at `0x00027000`, MSP `0x20040000`, reset `0x0003A890` (standard startup,
  `.data` from `0x00042710` to RAM `0x2000BC70..0x2000C1B8`).

## Toolchain
- **ARM GCC + newlib** (image contains the path string
  `../../../../../../../../newlib/libc/stdlib/rand.c`).
- Standard startup, standard C library — the firmware is a normal
  `arm-none-eabi-gcc` ELF (symbols stripped), so it is disassemblable and, in
  principle, rebuildable.

## The screen UI framework

The PLC firmware implements a small **object-oriented UI toolkit shaped like
LVGL 8.x** (symbol names stripped, but the class/vtable layout matches
`lv_obj_class_t` exactly) plus a vendor layer on top that uses `wxa_` (pages /
apps) and `xwa_` (trace/log function names) identifiers.

### Class descriptor layout (`lv_obj_class_t`-style), 36 B / 0x24
```
+0x00  base_class *      (e.g. 0x080488CC = the base "obj" class)
+0x04  constructor_cb *
+0x08  destructor_cb *
+0x0C  event_cb *
+0x10  user_data *
+0x14  name (char *)
+0x18  width_def
+0x1C  height_def
+0x20  flags/size word
```

### Base class `obj` — descriptor at `0x080488CC`
`{0, ctor 0x0801C9D1, dtor 0x0801F975, event 0x0801E9A5, 0, "obj", ...}`.
Every widget and page class points back to it. (0x080488CC appears ~30 times in
the image.)

### Built-in widget classes — table at `0x080491E8` (0x24 stride)
| name | base | ctor | dtor | event |
|---|---|---|---|---|
| `arc` | obj | 0x08027AE5 | 0 | 0x0802AC85 |
| `bar` | obj | 0x0802A45F | 0x080285F7 | 0x08028D1D |
| `btn` | obj | 0x08027AA7 | 0 | 0 |
| `btnmatrix` | obj | 0x08029285 | 0x080292B5 | 0x080298E1 |
| `slider` | bar | 0x08027D61 | 0 | 0x0802A4B9 |
| `spinner` | arc | 0x08028EB1 | 0 | 0 |
| `switch` | obj | 0x08027ABF | 0x08028611 | 0x0802A289 |

Inheritance: `obj` ← `arc` ← `spinner`, `obj` ← `bar` ← `slider`.
All classes are registered at framework init by a function around `0x0802188C`.

### Vendor page/app layer
Pages are stored in a **page descriptor table at `0x0804D4E0`** (0x24 stride),
with a different field order from the widget classes:
```
+0x00  ctor_cb       +0x08  (0)          +0x10  state/width
+0x04  dtor_cb       +0x0C  name         +0x14  state/height
+0x18  size          +0x1C  obj base     +0x20  event_cb
```

| # | name | ctor | dtor | event | size |
|---|---|---|---|---|---|
| 0 | `wxa_help_page` | 0x080356FC | 0x08036D48 | 0x08037680 | 0x644 |
| 1 | `wxa_main_page_blur` | 0x08035708 | 0x0803B8B8 | 0x08038A64 | 0x18C4 |
| 2 | `wxa_main_page_catyping` | 0x08035748 | 0x08037A08 | 0x0803907C | 0x36C4 |
| 3 | `wxa_main_page_blur` (2nd) | 0x0803919C | 0x0803A84C | 0x0803DAC0 | 0x1204 |
| 4 | `wxa_main_page_hacker` | 0x0803DA2C | 0x08043A30 | 0x0803E37C | 0x2804 |
| 5 | `wxa_menu_main_page` | 0x0803E560 | 0x0803E5A8 | 0x0803FD40 | 0x844 |
| 6 | `wxa_menu_sub_page` | 0x0803E57E | 0x0803EE6C | 0x08031918 | 0x944 |
| 7 | `wxa_time_page` | 0x0802FDAC | 0x08034E70 | 0x08030714 | 0x9C4 |
| 8 | `wxa_waitop_page` | 0x080303B8 | 0x080302C8 | — | 0x644 |

(The entries marked `blur` twice are two different main-page theme variants; the
`hacker`/`catyping`/`blur` pages are the built-in main-screen themes.)

The `size` field is the **malloc'd instance size** for the page object —
`page_create` (`0x0801A92C`) extracts it (`ubfx r0, r0, #4, #0x10`) and calls
`0x080245C0` (malloc) with it. Every page record references the same `obj` base
at `0x080488CC`.

Pages are instantiated through a common helper at `0x0801A92C` (takes a
descriptor field pointer, e.g. `0x0804D5B0`, creates the page object); the page
walker/creator code sits around `0x08030D10`.

### Apps as classes (the "apps" the menu runs)
App classes live near `0x0804F1A0` (they are registered like widget classes):

| name | base | ctor | dtor | event | extra |
|---|---|---|---|---|---|
| `wxa_anim` | obj | 0x0803658C | 0x080356F0 | 0x08036B54 | 0x200007D1, 0x200007D1, 0x984 |
| `wxa_fbird` | obj | 0x08036EA4 | 0x08036E94 | 0x0803702C | 0x140, 0xAC, 0x1704 |

`wxa_ow_screen` (0x08045248) is another screen/app descriptor in the same family.

### Trace facility
Functions emit log strings like `xwa_flappy_bird_constructor() ......\n`.
The variadic trace entry is at `0x080114AA` (pushes arg regs, calls the real
formatter at `0x08011440`). Page/app handlers are wrapped by these traces, which
is why the `xwa_*` names survive in a stripped binary.

## The menu / app system

### App IDs and dispatch
At `0x0804D4A0` is the **app ID table** (4-char codes → entry functions):

| ID | entry | meaning |
|---|---|---|
| `HELP` | 0x08030E7A | help page |
| `CHDT` | 0x08030E86 | date page |
| `CHTM` | 0x08030E92 | time page |
| `THEM` | 0x080308F8 | theme selection |
| `BIRD` | 0x08030ABC | Flappy Bird |
| `ANIM` | 0x08030ACC | custom animation |

`BIRD`/`ANIM` entry functions just load their 4-char ID and call the generic
**app launcher at `0x08030A44`** (validates via `0x080309BC`, then launches
through a slot table at `[dev + 0x30 + n*0x10]`). `HELP`/`CHDT`/`CHTM` call
`0x08030E20(dev, page_index, flags)` (page switch by index).

### Menu display strings (0x080493C0..0x08049520)
- **Apps:** `Flappy Bird`, `Custom Animation`, `HELP`, `SETTING`, `Date`, `Time`
- **Themes:** `Default`, `Code`, `Meow`, `Eva`
  (the four built-in main-page themes; internal class names are
  `wxa_main_page_hacker` / `wxa_main_page_catyping` / `wxa_main_page_blur` / 2nd blur)
- **RGB effects:** `Typewriter`, `Terminal`, `Raindrop`, `Custom`, `Disable`
  (exactly the effects the host protocol supports: off/typewriter/terminal/raindrop/custom)
- **Settings:** `Sleep Time` with options `15m/30m/1h/3h/6h`, `RGB Switch`,
  `LED`, `Type`, `Loading...`
- **Image formats:** `BGRA`, `LVHX`, `LVHA`, `LVA0` (screen upload formats)
- **Time:** `%02d`, `:`, `/`, `label`

The effects menu builder (creates each effect item from the name strings) is
around `0x08031400`.

## Example: how the Flappy Bird app is built

- Class descriptor `0x0804F1D8`: base `obj`, ctor `0x08036EA4`, dtor `0x08036E94`,
  event `0x0803702C`, name `wxa_fbird`, then `{0x140, 0xAC, 0x1704}`.
- `0x08036EA4` ctor: logs `xwa_flappy_bird_constructor`, initializes a state block
  on the stack, registers a 1000 ms (`0x3E8`) timer via `0x080267C0`, and fills
  the page state (`[r4+0x38] = 0x140`).
- `0x0803702C` event: the game loop. It checks the event belongs to the class
  (`0x0801AA2A`), reads the event code from `[r5+8] & 0x7FFF`, switches on it
  (0x18 = periodic tick), then does game math (modulo wraps, collision/position
  updates on the state struct at `r4`).
- The pattern for adding a new app = define a class descriptor in the same
  table, give it ctor/dtor/event callbacks + a `wxa_*` name.

## Theme data (open area)
The main-page theme pages (`hacker`/`catyping`/`blur`) carry per-theme `size`
values in their descriptors. Locating and parsing the actual theme resource
blobs (images/animations) is the next step for swapping in custom themes. Note
the host tool already uploads user themes over the QK protocol (ABKT/ANPS/
tabml), so the built-in ones are only defaults.

## Open questions / next steps
1. **Theme resource data**: the four built-in themes (Default/Code/Meow/Eva)
   render animated backgrounds, but no ANIM/ABKT/GIF magics exist in the PLC
   image — their data lives in a custom (probably LVGL-native or compressed)
   format and has not been located yet. This is the key to swapping themes in
   flash. The host tool already uploads themes over the protocol, so the
   built-ins are only defaults.
2. Exact page-lifecycle / app-manager flow (menu → page switch) — the walker at
   `0x08030D10`, the app launcher `0x08030A44`, and the instantiator `0x0801A92C`
   are the entry points; the RAM app registry lives at `0x20001F54`.
3. Bootloader: `0x08000000..0x08008000` (32 KB) is not in the supplied UF2; the
   AT32 ROM/stock bootloader handles it. The app image itself is a plain
   flash-at-address image (no obvious self-checksum).
4. Whether the master/mainboard firmware has anything to add (it owns the USB
   CDC host side and the file-upload handler for the screen).
