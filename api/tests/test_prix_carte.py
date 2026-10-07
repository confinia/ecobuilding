"""Prix sur la carte (#319) : routes par tuile, sans réseau."""
import httpx
import pytest

import app.main as main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def test_bornes_d_une_tuile():
    w, s, e, n = main._tuile_bbox(14, 8252, 5982)          # Colomiers
    assert w < 1.338233 < e and s < 43.607086 < n
    assert round(e - w, 4) == round(360 / 2 ** 14, 4)


@pytest.fixture
def faux_amont(monkeypatch, tmp_path):
    appels = []

    class Faux(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            appels.append(str(request.url))
            if "prix_cellules_large" in str(request.url):
                return httpx.Response(200, content=b'[[1.336, 43.606, 120, 2980, 7, "M"]]')
            if "prix_cellules" in str(request.url):
                return httpx.Response(503)
            return httpx.Response(200, content=b'[[1.3383, 43.6071, 3, 3066, "2024", 3100, "M"]]')

    monkeypatch.setattr(main, "TILES_DIR", str(tmp_path))
    monkeypatch.setattr(main, "_client", httpx.AsyncClient(transport=Faux()))
    monkeypatch.setattr(main, "DVF_PRIX_POINTS_URL", "http://dvf/rpc/prix_points")
    monkeypatch.setattr(main, "DVF_PRIX_CELLULES_URL", "http://dvf/rpc/prix_cellules")
    monkeypatch.setattr(main, "DVF_PRIX_LARGE_URL", "http://dvf/rpc/prix_cellules_large")
    return appels


def test_une_tuile_de_points_est_servie_puis_gardee(faux_amont):
    r = client.get("/v1/prices/points/8252/5982.json")
    assert r.status_code == 200 and r.json()[0][3] == 3066
    assert "public" in r.headers["cache-control"]
    assert client.get("/v1/prices/points/8252/5982.json").status_code == 200
    assert len(faux_amont) == 1                              # la seconde vient du cache disque
    assert "minlon=" in faux_amont[0] and "maxlat=" in faux_amont[0]


def test_hors_grille_404_et_source_indisponible_503(faux_amont):
    assert client.get("/v1/prices/points/99999/1.json").status_code == 404
    r = client.get("/v1/prices/cells/2063/1495.json")
    assert r.status_code == 503 and r.headers["retry-after"] == "600"


def test_une_tuile_de_grandes_cellules_couvre_un_demi_degre(faux_amont):
    """#530: z9 tiles (~50 km), cached like the others; the bbox sent upstream
    is a z9 tile, not a z12 one."""
    r = client.get("/v1/prices/large/258/373.json")             # Toulouse area
    assert r.status_code == 200 and r.json()[0][4] == 7
    w, s, e, n = main._tuile_bbox(9, 258, 373)
    assert round(e - w, 4) == round(360 / 2 ** 9, 4)
    assert f"minlon={w}" in faux_amont[0]
    assert client.get("/v1/prices/large/99999/1.json").status_code == 404
