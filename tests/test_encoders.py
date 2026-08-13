"""Regression checks for the encoders (no test framework required).

Run:
    .venv\\Scripts\\python tests\\test_encoders.py

Covers:
  * partial-frame GIF compositing (disposal=1 and disposal=2) through
    ``gif_to_video`` - guards against regressions in Pillow's disposal
    handling, which ``seek()`` relies on for correctly reconstructed frames
  * encoder magic defaults (ABKT/ANIT/ANPS) and the ``magic=`` override
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

import qk80


def _partial_gif(disposal: int, size=(10, 10), patch=(4, 4), pos=(2, 2)) -> str:
    """A partial-frame GIF: frame 0 is full red, frame 1 only a blue patch.

    Real-world optimized GIFs store just the changed region and rely on the
    disposal method to reconstruct the full frame.
    """
    f0 = Image.new("RGB", size, (255, 0, 0))
    f1 = f0.copy()
    f1.paste(Image.new("RGB", patch, (0, 0, 255)), pos)
    fd, path = tempfile.mkstemp(suffix=".gif")
    os.close(fd)
    f0.save(path, save_all=True, append_images=[f1],
            disposal=[0, disposal], duration=[100, 100], loop=0)
    return path


def _check_compositing(path: str, label: str):
    g = Image.open(path)
    try:
        assert g.n_frames == 2, label
        g.seek(1)
        frame = g.convert("RGB")
        assert frame.getpixel((3, 3)) == (0, 0, 255), f"{label}: patch missing"
        assert frame.getpixel((7, 7)) == (255, 0, 0), f"{label}: background lost"
        g.seek(0)
        data = qk80.gif_to_video(g)
        assert data[:4] == b"ANIT", f"{label}: wrong magic {data[:4]!r}"
    finally:
        g.close()
    os.remove(path)


def main():
    for disposal, label in ((1, "do-not-dispose"),
                            (2, "restore-background")):
        _check_compositing(_partial_gif(disposal), label)

    img = Image.new("RGB", (10, 10))
    assert qk80.encode_image(img)[:4] == b"ABKT"
    assert qk80.encode_image(img, magic=b"ABKG")[:4] == b"ABKG"
    assert qk80.encode_video([img], [100])[:4] == b"ANIT"
    assert qk80.encode_slider([img], 5, 1)[:4] == b"ANPS"
    assert qk80.encode_tabml([img], 1, 7, 7)[:5] == b"tabml"

    try:
        qk80.encode_tabml([img] * 256, 1, 7, 7)
        raise AssertionError("encode_tabml accepted 256 frames")
    except ValueError as e:
        assert "frames" in str(e)

    print("encoder regression checks OK")


if __name__ == "__main__":
    main()
