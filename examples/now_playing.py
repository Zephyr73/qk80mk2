"""Show the album art of the currently playing track on the QK80 MK2 Themes screen.

Template for the "now playing" idea: fill in `get_cover_url()` with your music
player's integration and this script does the rest. It fetches the cover art,
encodes it as an ABKT image and uploads it (Themes -> Default Theme).

Integration ideas for get_cover_url():
  * mpd/mopidy:  ``http://127.0.0.1:6600`` commands ``currentsong`` + ``find cover``
  * Spotify:     GET https://api.spotify.com/v1/me/player/currently-playing
  * Web-based:   any URL that serves the cover (e.g. Deezer API by track name)

You can also pass a local file or URL directly:
  python now_playing.py cover.jpg
  python now_playing.py https://example.com/cover.png

Ctrl+C is safe at any point (the keyboard receives a cancel command).
"""

import sys
import urllib.request
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import qk80


def get_cover_url() -> str:
    """Return a URL (or local path) for the currently playing track's art."""
    # TODO: replace with your music player integration.
    return "https://upload.wikimedia.org/wikipedia/en/thumb/8/8f/Pink_Floyd_-_The_Dark_Side_of_the_Moon.png/220px-Pink_Floyd_-_The_Dark_Side_of_the_Moon.png"


def load_image(source: str) -> Image.Image:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=10) as resp:
            return Image.open(BytesIO(resp.read()))
    return Image.open(source)


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else get_cover_url()
    img = load_image(src)
    data = qk80.encode_abkg(img)  # ABKT -> Themes -> Default Theme
    print(f"encoded ABKT ({len(data)} bytes)")
    qk80.upload(data)
    print("album art shown on the Themes screen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
