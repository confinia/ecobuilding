"""Proxy + cache des tuiles bâtiments (/v1/tiles).

Contexte : api.bdnb.io est anonyme, plafonné à 120 req/min et 10 000 req/MOIS
par IP. MapLibre, au-dessus du maxzoom d'une source, redemande la MÊME tuile une
fois par identifiant sur-zoomé (~15 fois à z18 avec du pitch) : sans ce proxy,
quelques rechargements suffisaient à déclencher un 429 et la carte 3D se vidait
en silence. Ces tests verrouillent les trois propriétés qui rendent le correctif
efficace : cache disque, mutualisation des requêtes concurrentes, et repli sur
une tuile périmée quand l'amont est KO.
"""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)
TILE = "/v1/tiles/batiment_groupe/14/8297/5635.pbf"


@pytest.fixture(autouse=True)
def _tiles_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "TILES_DIR", str(tmp_path))
    monkeypatch.setattr(main, "TILE_TTL", 3600.0)
    main._TILE_LOCKS.clear()
    main._tile_hits.clear()
    yield


class _FakeResponse:
    def __init__(self, status_code=200, content=b"\x1a\x2b-tuile"):
        self.status_code, self.content = status_code, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def test_tile_is_cached_on_disk(monkeypatch):
    """Deuxième appel : plus rien ne part vers BDNB (le quota est mensuel)."""
    calls = []

    async def fake_get(url, *a, **kw):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(main._client, "get", fake_get)
    first = client.get(TILE)
    second = client.get(TILE)

    assert first.status_code == second.status_code == 200
    assert first.content == second.content == b"\x1a\x2b-tuile"
    assert len(calls) == 1, "la tuile en cache ne doit plus être redemandée"
    assert "max-age" in second.headers.get("cache-control", ""), \
        "sans Cache-Control le navigateur rejoue chaque tuile (BDNB n'en envoie pas)"


def test_concurrent_requests_hit_upstream_once(monkeypatch):
    """LE point du correctif : les ~15 requêtes simultanées d'un même affichage
    ne doivent produire qu'UN appel amont."""
    calls = []

    async def slow_get(url, *a, **kw):
        calls.append(url)
        await asyncio.sleep(0.05)          # laisse les autres arriver
        return _FakeResponse()

    monkeypatch.setattr(main._client, "get", slow_get)

    async def run():
        return await asyncio.gather(*[main.building_tile(14, 8297, 5635) for _ in range(15)])

    responses = asyncio.run(run())
    assert len(calls) == 1, f"{len(calls)} appels amont pour une seule tuile"
    assert all(r.body == b"\x1a\x2b-tuile" for r in responses)


def test_stale_tile_served_when_upstream_fails(monkeypatch):
    """Amont KO (429) : mieux vaut une tuile périmée qu'une carte vide."""
    async def ok_get(url, *a, **kw):
        return _FakeResponse()

    monkeypatch.setattr(main._client, "get", ok_get)
    assert client.get(TILE).status_code == 200          # remplit le cache

    monkeypatch.setattr(main, "TILE_TTL", 0.0)          # tout est périmé

    async def rate_limited(url, *a, **kw):
        return _FakeResponse(status_code=429, content=b"")

    monkeypatch.setattr(main._client, "get", rate_limited)
    stale = client.get(TILE)
    assert stale.status_code == 200 and stale.content == b"\x1a\x2b-tuile"


def test_503_when_upstream_fails_without_cache(monkeypatch):
    """Sans rien en cache, on renvoie une vraie erreur : le front affiche le
    bandeau « bâtiments 3D indisponibles » au lieu d'une carte nue muette."""
    async def rate_limited(url, *a, **kw):
        return _FakeResponse(status_code=429, content=b"")

    monkeypatch.setattr(main._client, "get", rate_limited)
    r = client.get(TILE)
    assert r.status_code == 503
    assert r.headers.get("cache-control") == "no-store", "un 503 ne se met pas en cache"


def test_upstream_budget_protects_data_calls(monkeypatch):
    """Les tuiles partagent l'IP (donc le quota) avec les appels de données :
    un balayage de carte ne doit pas pouvoir tout consommer."""
    monkeypatch.setattr(main, "TILE_UPSTREAM_RPM", 2)
    calls = []

    async def fake_get(url, *a, **kw):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(main._client, "get", fake_get)
    codes = [client.get(f"/v1/tiles/batiment_groupe/14/8297/{5635 + i}.pbf").status_code
             for i in range(4)]
    assert len(calls) == 2, "le budget amont n'a pas été respecté"
    assert codes[:2] == [200, 200] and codes[2:] == [503, 503]


def test_out_of_range_coordinates_are_rejected():
    assert client.get("/v1/tiles/batiment_groupe/14/99999999/1.pbf").status_code == 404
    assert client.get("/v1/tiles/batiment_groupe/99/1/1.pbf").status_code == 404


def test_map_uses_our_tiles_not_bdnb_directly():
    """Le front et le renderer PDF doivent passer par le cache, pas par
    api.bdnb.io (dont le quota est par IP : celle du visiteur, celle de la VM)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    app_js = (root / "frontend/site/app.js").read_text()
    render = (root / "render_stack/render.html").read_text()

    assert "/v1/tiles/batiment_groupe/" in app_js
    assert "api.bdnb.io/v1/bdnb/tuiles" not in app_js
    assert "api.bdnb.io/v1/bdnb/tuiles" not in render
    # BDNB ne publie que le z14 : demander z13 ne ramène rien et coûte du quota.
    assert "minzoom: 14" in app_js and "minzoom: 14, maxzoom: 14" in render
    # L'échec des tuiles doit être DIT à l'utilisateur (il était muet).
    assert "showTileNotice" in app_js
