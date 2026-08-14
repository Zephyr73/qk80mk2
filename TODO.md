# TODO

- [ ] **Create git repo**
  - `git init`, add `.gitignore` (`.venv/`, `__pycache__/`, `*.tabml`, `.DS_Store`, etc.)
  - Initial commit; later tags for releases (`v1.0.0`, ...)
- [ ] **Make code usable for public, universal IDs**
  - Remove the hardcoded `VID 0x514B / PID 0x4D02` from `qk80/constants.py` (constants used by
    `CDCTransport.open`, `HIDTransport.open`, `probe_devices`).
  - Support a table of known boards (QK80 MK2, other tabkb/QK devices) and match
    against it; allow override via `--vid/--pid` flags / env vars / config file.
  - Update `probe_devices()` and the `devices` command to report by device.
- [ ] **Better code**
  - [x] Split `qk80.py` into the `qk80/` package (`constants` / `encoders` / `matrix` /
    `transport` / `api` / `cli`); CLI entry point is now `python -m qk80`.
  - De-duplicate the CDC vs HID transfer loops (shared chunk/fetch/cancel logic).
  - Full type hints, docstrings, and consistent error types (custom exception class).
  - Unit tests for encoders, color math, pattern parsing, echo validation.
- [ ] **Better documentation**
  - Expand README: install, quick-start, FAQ, troubleshooting, release notes/changelog.
  - Full API reference (autodoc-style) for every public function/class.
  - Clean up PROTOCOL.md into versioned sections; document device support matrix.
- [ ] **Remove risky features if there's any**
  - Audit: firmware-level writes (`0x09` persist/save, `0xC0` matrix uploads) — consider
    confirmation flags.
  - `--save` silently overwrites files; warn or require `--force`.
  - No upload size limits / sanity checks before transfer.
  - Document and gate any feature that can leave the device in a broken state.
- [ ] **Clean code**
  - Remove dead code and unused imports; `ruff`/`mypy` clean run.
  - Consistent naming, ordering, and style; drop the `# ---` banner comments in favor of
    module sections.
  - Delete stale files if any; keep `examples/` and `tests/` tidy.
