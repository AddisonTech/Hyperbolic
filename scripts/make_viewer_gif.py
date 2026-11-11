"""Record the published replay viewer playing its month, as docs/assets/viewer.gif for the README.

Serves docs/ on 127.0.0.1, opens it in headless Chromium, presses 60x and play, and captures about
8 seconds of the playback band: the timeline with the price strip, the running counters, the indoor
temperature, district grid draw and battery charts, and the agent's reason card. Pillow turns the
frames into a GIF 900 px wide. No model or simulator calls: the page replays docs/data/viewer.js.

Playwright, Chromium and Pillow are dev tools, not package dependencies. Chromium goes inside
.venv (PLAYWRIGHT_BROWSERS_PATH=0 puts it in the playwright package folder):

    .venv\\Scripts\\python -m pip install playwright pillow
    set PLAYWRIGHT_BROWSERS_PATH=0  (PowerShell: $env:PLAYWRIGHT_BROWSERS_PATH = "0")
    .venv\\Scripts\\python -m playwright install chromium
    .venv\\Scripts\\python scripts\\make_viewer_gif.py
"""

from __future__ import annotations

import argparse
import functools
import http.server
import io
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "assets" / "viewer.gif"

VIEWPORT = {"width": 1280, "height": 1400}
WIDTH = 900
MAX_BYTES = 5 * 1024 * 1024


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def serve(directory: Path) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(_Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def capture(url: str, seconds: float, fps: float) -> list[tuple[bytes, float]]:
    """PNG frames of the playback band with the time each was taken, while the month plays at 60x."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    from playwright.sync_api import sync_playwright

    frames: list[tuple[bytes, float]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(url)
        page.wait_for_function("document.getElementById('headline').textContent !== 'Loading replay'")
        page.wait_for_selector("#chart-grid svg")
        page.click('#speed button[data-speed="60"]')
        page.click("#play")
        # Playing scrolls the page to the district; put the playback band back in view, under the
        # sticky header, and clip to it.
        # The reason log fills up over the first hours played; measure it once it has.
        page.wait_for_timeout(1500)
        header = page.locator("header").first.bounding_box()["height"]
        page.evaluate("window.scrollTo(0, 0)")
        top = page.locator(".transport").bounding_box()["y"]
        bottom_box = page.locator("#reasons").bounding_box()
        bottom = bottom_box["y"] + bottom_box["height"]
        pad = 14
        page.evaluate(f"window.scrollTo(0, {top - header - pad})")
        page.wait_for_timeout(200)
        left = page.locator(".race").bounding_box()["x"] - pad
        clip = {"x": left, "y": header, "width": VIEWPORT["width"] - 2 * left,
                "height": min(VIEWPORT["height"] - header, bottom - top + pad + 8)}
        start = time.monotonic()
        step = 1.0 / fps
        while (now := time.monotonic()) - start < seconds:
            frames.append((page.screenshot(clip=clip), now - start))
            wait = step - (time.monotonic() - now)
            if wait > 0:
                page.wait_for_timeout(wait * 1000)
        browser.close()
    return frames


def build_gif(frames: list[tuple[bytes, float]], out: Path, width: int = WIDTH) -> int:
    from PIL import Image

    images = []
    for png, _ in frames:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        images.append(im)
    # One palette for every frame, taken from the middle of the run, so colors do not flicker.
    palette = images[len(images) // 2].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    paletted = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    times = [t for _, t in frames]
    durations = [max(20, round((b - a) * 1000)) for a, b in zip(times, times[1:])]
    durations.append(1500)  # rest on the last frame before the loop starts again
    out.parent.mkdir(parents=True, exist_ok=True)
    paletted[0].save(out, save_all=True, append_images=paletted[1:], duration=durations, loop=0,
                     optimize=True, disposal=1)
    return out.stat().st_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    server = serve(DOCS)
    try:
        frames = capture(f"http://127.0.0.1:{server.server_port}/index.html", args.seconds, args.fps)
    finally:
        server.shutdown()
    if len(frames) < 10:
        print(f"only {len(frames)} frames captured", file=sys.stderr)
        return 1
    size = build_gif(frames, args.out)
    span = frames[-1][1] - frames[0][1]
    print(f"wrote {args.out} ({size / 1024 / 1024:.2f} MB, {len(frames)} frames over {span:.1f} s, {WIDTH} px wide)")
    if size > MAX_BYTES:
        print("GIF is over 5 MB", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
