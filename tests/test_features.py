"""Regression checks for Config -> Features (Light Power / Sleep Mode).

Run:
    .venv\\Scripts\\python tests\\test_features.py

Covers the exact wire bytes for the LED-power toggle and sleep-mode dropdown
(verified against the configurator bundle: VIA custom-value subsystem 17,
option 1 = Light Power, option 2 = Sleep Mode, 0x07-set + 0x09-save), plus the
``parse_sleep_mode`` value mapping. Uses a fake ``_send`` so no keyboard is
needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qk80.api import parse_sleep_mode
from qk80.transport import HIDTransport


class _FakeHID(HIDTransport):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _send(self, cmd: int, args: bytes) -> bytes:
        self.calls.append((cmd, args))
        return bytes([cmd]) + args + b"\x00" * 32  # echoed cmd+args, then 0s


def _wire(t, *expected):
    assert t.calls == [(c, a) for c, a in expected], t.calls


def main():
    t = _FakeHID()

    t.set_light_power(True)
    _wire(t, (0x07, bytes([17, 1, 1])), (0x09, bytes([17])))

    t.calls.clear()
    t.set_light_power(False)
    _wire(t, (0x07, bytes([17, 1, 0])), (0x09, bytes([17])))

    t.calls.clear()
    t.set_sleep_mode(4)  # 1 hour
    _wire(t, (0x07, bytes([17, 2, 4])), (0x09, bytes([17])))

    t.calls.clear()
    t.set_sleep_mode(0)  # disable
    _wire(t, (0x07, bytes([17, 2, 0])), (0x09, bytes([17])))

    try:
        t.set_sleep_mode(7)
        raise AssertionError("set_sleep_mode accepted index 7")
    except ValueError:
        pass

    # get: response is [cmd, 17, option, value, ...] -> value at byte 3
    real_send = t._send
    t._send = lambda cmd, args: b"\x08\x11\x01\x01" + b"\x00" * 32
    assert t.get_light_power() is True
    t._send = lambda cmd, args: b"\x08\x11\x01\x00" + b"\x00" * 32
    assert t.get_light_power() is False
    t._send = lambda cmd, args: b"\x08\x11\x02\x05" + b"\x00" * 32
    assert t.get_sleep_mode() == 5
    t._send = real_send
    t.calls.clear()
    t.set_light_power(True)
    _wire(t, (0x07, bytes([17, 1, 1])), (0x09, bytes([17])))

    # parse_sleep_mode: indices, durations, and disable aliases
    assert parse_sleep_mode(0) == 0
    assert parse_sleep_mode(6) == 6
    assert parse_sleep_mode("disable") == 0
    assert parse_sleep_mode("off") == 0
    assert parse_sleep_mode("5min") == 1
    assert parse_sleep_mode("5 minutes") == 1
    assert parse_sleep_mode("15") == 2
    assert parse_sleep_mode("30min") == 3
    assert parse_sleep_mode("1h") == 4
    assert parse_sleep_mode("1 hour") == 4
    assert parse_sleep_mode("3 hours") == 5
    assert parse_sleep_mode("6h") == 6
    for bad in ("4h", "10min", "45min", "every so often", "banana"):
        try:
            parse_sleep_mode(bad)
            raise AssertionError(f"parse_sleep_mode accepted {bad!r}")
        except ValueError:
            pass

    print("features (light power / sleep mode) checks OK")


if __name__ == "__main__":
    main()
