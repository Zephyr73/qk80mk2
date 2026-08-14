"""Regression checks for the Date & Time sync timestamp math (no framework).

Run:
    .venv\\Scripts\\python tests\\test_time.py

Covers the conversion in ``qk80.transport._wall_seconds``, which produces the
same value as the configurator's Time Sync button:
``floor(now/1000) - timezoneOffset*60`` (local wall-clock time as Unix seconds).

Verified against a real device, so the math here is the guarantee that what we
send the keyboard is exactly what the official app sends.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qk80.transport import _wall_seconds


def main():
    # 1. None -> the host's local wall-clock read encoded as if it were UTC.
    #    Cross-check against the JS formula `floor(now/1000) - tzOffset*60`
    #    = UTC epoch + local offset.
    import time as _t

    now = datetime.now()
    offset = int(now.astimezone().utcoffset().total_seconds())
    assert abs((_wall_seconds(None) - (int(_t.time()) + offset))) <= 1, \
        "None must equal the app's formula (UTC epoch + tz offset)"

    # 2. naive datetime -> that wall-clock read, taken verbatim (as-if-UTC)
    dt = datetime(2026, 8, 14, 14, 30, 0)
    assert _wall_seconds(dt) == int(dt.replace(tzinfo=timezone.utc).timestamp())

    # 3. tz-aware datetime -> that instant's local wall-clock read
    aware = datetime(2026, 8, 14, 6, 30, 0, tzinfo=timezone.utc)
    assert _wall_seconds(aware) == int(aware.astimezone().timestamp()) + offset

    # 4. number = UTC epoch seconds, converted to the local tz
    epoch_utc = 1784188800  # 2026-07-16 08:00:00 UTC
    assert _wall_seconds(epoch_utc) == epoch_utc + offset

    # 5. the wire value: big-endian 4 bytes, and it must round-trip
    import struct

    for ts in (_wall_seconds(None), _wall_seconds(dt)):
        raw = struct.pack(">I", ts)
        assert len(raw) == 4 and struct.unpack(">I", raw)[0] == ts

    print("time sync checks OK")


if __name__ == "__main__":
    main()
