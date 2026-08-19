"""Affichage au fil de l'eau (/v1/buildings/{id}/stream, /v1/lookup/stream).

Demande opérateur : « display the data dynamically, while they arrive » et
« load only once, rather twice ». Neuf sources ouvertes sont interrogées par
bâtiment ; attendre la plus lente (Géorisques, mesuré à 5,7 s quand tout le
reste est là en moins d'une seconde) laissait l'utilisateur devant un panneau
vide. Ces tests verrouillent : le bâtiment part en premier, chaque bloc suit à
son arrivée, et l'agrégat final atterrit dans le MÊME cache que
/v1/buildings — donc la fiche PDF qui suit ne rejoue rien.
"""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)

ROW = {"batiment_groupe_id": "bdnb-bg-STREAM",
       "libelle_adr_principale_ban": "14 rue de la Loge 34000 Montpellier",
       "code_commune_insee": "34172"}


@pytest.fixture
def stubbed(monkeypatch):
    """Sources neutralisées : on teste le PROTOCOLE du flux, pas les données."""
    calls = []

    async def fake_get(url, params, ttl=0):
        calls.append(url)
        if "adresse.data.gouv" in url:
            return {"features": [{"properties": {"id": "34172_1234_00014",
                                                 "label": "14 rue de la Loge 34000 Montpellier"},
                                  "geometry": {"coordinates": [3.8767, 43.6108]}}]}
        return [ROW]

    monkeypatch.setattr(main, "_cached_get_json", fake_get)
    for name in ("_area_risks", "_groundwater", "_solar_pv", "_water_network",
                 "_official_dpe", "_local_taxes", "_nearby_schools",
                 "_dvf_prices", "_rnb_lookup", "_click_address"):
        async def none(*a, _n=name, **k):
            calls.append(_n)
            return None
        monkeypatch.setattr(main, name, none)
    return calls


def _events(path):
    with client.stream("GET", path) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        return [json.loads(l) for l in r.iter_lines() if l.strip()]


def test_stream_sends_the_building_before_the_slow_sources(stubbed):
    evs = _events("/v1/buildings/bdnb-bg-STREAM/stream?lon=3.8767&lat=43.6108")
    assert evs[0]["type"] == "core", "le bâtiment doit partir en premier"
    assert evs[0]["buildings"][0]["bdnb_id"] == "bdnb-bg-STREAM"
    assert evs[-1]["type"] == "done"
    names = [e["name"] for e in evs if e["type"] == "block"]
    # click_addr sert à titrer, ce n'est pas un bloc affichable.
    assert "click_addr" not in names
    assert set(names) == {"prices", "area_risks", "groundwater", "solar_pv",
                          "water_network", "official_dpe", "local_taxes",
                          "schools", "rnb"}


def test_stream_fills_the_cache_so_the_pdf_replays_nothing(stubbed):
    _events("/v1/buildings/bdnb-bg-STREAM/stream?lon=3.8767&lat=43.6108")
    after_stream = len(stubbed)
    # Ce que fait la route PDF juste après :
    r = client.get("/v1/buildings/bdnb-bg-STREAM?lon=3.8767&lat=43.6108")
    assert r.status_code == 200
    assert len(stubbed) == after_stream, "la fiche PDF a rejoué l'orchestration"


def test_cached_building_streams_in_one_go(stubbed):
    client.get("/v1/buildings/bdnb-bg-STREAM?lon=3.8767&lat=43.6108")   # remplit
    after = len(stubbed)
    evs = _events("/v1/buildings/bdnb-bg-STREAM/stream?lon=3.8767&lat=43.6108")
    assert len(stubbed) == after, "cache chaud : aucune source ne doit être rappelée"
    assert evs[0]["type"] == "core" and evs[-1]["type"] == "done"


def test_lookup_stream_titles_with_the_searched_address(stubbed):
    evs = _events("/v1/lookup/stream?q=14+rue+de+la+Loge+Montpellier")
    assert evs[0]["type"] == "core"
    q = evs[-1]["query"]
    assert q["q"] == "14 rue de la Loge Montpellier"
    assert q["address"] == "14 rue de la Loge 34000 Montpellier"
    assert evs[-1]["buildings"][0]["bdnb_id"] == "bdnb-bg-STREAM"


def test_stream_reports_unknown_building_without_crashing(monkeypatch):
    async def empty(url, params, ttl=0):
        return []
    monkeypatch.setattr(main, "_cached_get_json", empty)
    evs = _events("/v1/buildings/bdnb-bg-NOPE/stream?lon=1&lat=1")
    assert evs == [{"type": "error", "status": 404, "detail": "Unknown building id"}]


def test_front_consumes_the_stream():
    import pathlib
    app_js = (pathlib.Path(__file__).resolve().parents[2] / "frontend/site/app.js").read_text()
    assert "consumeBuildingStream" in app_js
    assert "/stream?lon=" in app_js and "lookup/stream" in app_js
    # Le panneau doit dire ce qui manque encore, sans masquer ce qui est là.
    assert "STREAM_PENDING" in app_js and "Encore en cours" in app_js


def test_streetview_is_fetched_once_per_position():
    """Le panneau est re-rendu à chaque bloc du flux : la vue au sol ne doit
    pas être redemandée neuf fois par clic."""
    import pathlib
    app_js = (pathlib.Path(__file__).resolve().parents[2] / "frontend/site/app.js").read_text()
    assert "streetviewAt" in app_js and "streetviewCache" in app_js
