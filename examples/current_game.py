"""Show the currently focused game's Steam header image on the QK80 MK2 Themes screen.

Template for the "which game are you playing" idea (like Discord): on Windows,
reads the foreground window title and looks it up in GAMES to get a Steam
appid, fetches the horizontal header image, encodes it as ABKT and uploads it.

Ctrl+C is safe at any point (the keyboard receives a cancel command).
"""

import ctypes
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import qk80

# Window-title fragment -> Steam appid. Extend with your own games.
GAMES = {
    "Counter-Strike 2": 730,
    "Dota 2": 570,
    "PUBG": 578080,
    "Elden Ring": 1245620,
    "Baldur's Gate 3": 1086940,
}


def focused_game_appid():
    """Return the Steam appid of the focused window, or None."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
    user32.GetWindowTextW(hwnd, title, len(title))
    for name, appid in GAMES.items():
        if name.lower() in title.value.lower():
            return appid
    return None


def fetch_header(appid: int) -> Image.Image:
    url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return Image.open(BytesIO(resp.read()))


def main() -> int:
    appid = focused_game_appid()
    if appid is None:
        print("no known game focused; put the game in the foreground and retry")
        return 1
    data = qk80.encode_image(fetch_header(appid))
    print(f"game appid {appid}: encoded ABKT ({len(data)} bytes)")
    qk80.upload(data)
    print("shown on the Themes screen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
