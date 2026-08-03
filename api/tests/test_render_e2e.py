"""End-to-end check for the headless map render service (issue #88, MapLibre 6.1.0).

Guards the failure mode behind the 6.1.0 migration: MapLibre 6.x is ESM-only and
its tile-worker chunk must be served same-origin. If the worker ever stops
loading (e.g. a future change points the map at a CDN again), the map fires
`styledata` but never `load`/`idle`, and `/shot` returns a blank frame instead
of hanging — a blank PNG is only a few KB, a real 3D DPE render is 300KB-1MB.
So we assert a decodable PNG of the expected size that is well above the blank
floor. See maplibre/maplibre-gl-js#8074.

Opt-in (talks to the live render service); skipped, never faked, otherwise:

    RENDER_E2E=1 ./deploy/test.sh
"""

import io
import os

import httpx
import pytest
from PIL import Image

# The API reaches the render service via the host gateway (same as in prod);
# override for a different host/port.
RENDER = os.environ.get("RENDER_E2E_URL", "http://host.containers.internal:8040")

pytestmark = pytest.mark.skipif(
    not os.environ.get("RENDER_E2E"), reason="set RENDER_E2E to run the render e2e check"
)

# Île de la Cité / Notre-Dame — dense BDNB coverage, so the frame is full of
# extruded DPE-coloured buildings (a good signal that tiles actually rendered).
SHOT = {"lon": 2.3488, "lat": 48.8534, "zoom": 18, "pitch": 60, "bearing": -25}
BLANK_FLOOR = 50_000  # bytes; blank/failed renders are ~4.5KB, real ones >300KB


def test_render_healthz():
    r = httpx.get(f"{RENDER}/healthz", timeout=20)
    assert r.status_code == 200 and r.text.strip() == "ok"


def test_shot_returns_real_png():
    r = httpx.get(f"{RENDER}/shot", params=SHOT, timeout=60)
    assert r.status_code == 200, r.text[:200]
    assert r.headers.get("content-type", "").startswith("image/png")
    body = r.content
    # A blank frame (worker never ran) is a few KB; a real render is much larger.
    assert len(body) > BLANK_FLOOR, f"render too small ({len(body)}B) — worker may not be rendering"
    img = Image.open(io.BytesIO(body))
    img.verify()  # decodable PNG
    assert img.format == "PNG"
    # #map is 960x540 CSS at deviceScaleFactor 2 -> 1920x1080.
    assert img.size == (1920, 1080), img.size
