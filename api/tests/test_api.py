"""Hermetic tests for the existing public API (no network calls)."""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)

BUILDING_FIXTURE = {
    "query": {"bdnb_id": "bdnb-bg-TEST", "address": "1 Rue de Test 75001 Paris", "lon": 2.3, "lat": 48.8},
    "buildings": [{
        "bdnb_id": "bdnb-bg-TEST", "address": "1 Rue de Test 75001 Paris",
        "construction_year": 1900, "height_m": 15, "floors": None, "dwellings": 8,
        "wall_material": "PIERRE", "roof_material": "ZINC",
        "energy": {"dpe_class": "F", "dpe_date": "2024-05-01", "consumption_kwh_m2y": 342.2,
                    "ghg_kgco2_m2y": 74.1, "dpe_class_counts": {},
                    "rental_ban": {"dpe_class": "F", "rental_ban_date": "2028-01-01", "note": "test"}},
        "risks": {"clay_shrink_swell": "Moyen"},
        "solar": {"thermal_favourable": True, "thermal_potential_kwh_y": 21.5},
        "consumption_2020": {},
    }],
    "area_risks": {"commune": "Paris", "report_url": "https://example.org",
                   "risques_naturels": ["inondation"], "risques_technologiques": []},
    "sources": [],
}


def test_healthz():
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_lookup_requires_params():
    assert client.get("/v1/lookup").status_code == 422


def test_suggest_normalizes_ban_features(monkeypatch):
    async def fake_get(url, params, ttl):
        return {"features": [{
            "properties": {"label": "Dreux", "id": "28134", "type": "municipality", "city": "Dreux"},
            "geometry": {"coordinates": [1.365, 48.737]},
        }]}
    monkeypatch.setattr(main, "_cached_get_json", fake_get)
    r = client.get("/v1/suggest", params={"q": "dreux"})
    assert r.status_code == 200
    s = r.json()["suggestions"][0]
    assert s["type"] == "municipality" and s["lon"] == 1.365


def test_events_beacon():
    r = client.post("/v1/events", json={"event": "ci_test"})
    assert r.status_code == 204


def test_leads_persisted(tmp_path, monkeypatch):
    path = tmp_path / "leads.jsonl"
    monkeypatch.setattr(main, "LEADS_PATH", str(path))
    r = client.post("/v1/leads", json={"email": "ci@test.io", "org": "CI", "need": "test"})
    assert r.status_code == 204
    rec = json.loads(path.read_text().strip())
    assert rec["email"] == "ci@test.io"


def test_report_pdf_bytes():
    from app.report import build_report_pdf
    pdf = build_report_pdf(BUILDING_FIXTURE)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000


# --- DVF home prices (issue #89) ---------------------------------------------
PRICES_FIXTURE = {
    "available": True, "commune_code": "75101",
    "sales": [{"date": "2023-05-01", "valeur_fonciere": 500000, "type_local": "Appartement",
               "surface_m2": 50, "pieces": 2, "eur_m2": 10000}],
    "commune_eur_m2": {"Appartement": {"median": 12828, "n": 1518}},
}


def test_prices_html_available():
    from app.report import _prices_html
    h = _prices_html(PRICES_FIXTURE)
    assert "Prix de vente (DVF)" in h and "12 828" in h and "10 000" in h


def test_prices_html_unavailable_is_honest():
    from app.report import _prices_html
    h = _prices_html({"available": False})
    assert "indisponibles" in h and "Alsace-Moselle" in h  # never a fake number


def test_prices_html_none_omits_section():
    from app.report import _prices_html
    assert _prices_html(None) == ""


def test_building_includes_prices(monkeypatch):
    async def fake_bdnb(url, params, ttl):
        return [{"batiment_groupe_id": "bdnb-bg-X", "libelle_adr_principale_ban": "1 rue X"}]
    async def fake_prices(bid): return PRICES_FIXTURE
    async def fake_risks(lon, lat): return {}
    monkeypatch.setattr(main, "_cached_get_json", fake_bdnb)
    monkeypatch.setattr(main, "_dvf_prices", fake_prices)
    monkeypatch.setattr(main, "_area_risks", fake_risks)
    body = client.get("/v1/buildings/bdnb-bg-X").json()
    assert body["prices"]["available"] is True
    assert any("DVF" in s for s in body["sources"])


def test_building_prices_none_when_dvf_disabled(monkeypatch):
    async def fake_bdnb(url, params, ttl):
        return [{"batiment_groupe_id": "bdnb-bg-X"}]
    async def fake_risks(lon, lat): return {}
    monkeypatch.setattr(main, "_cached_get_json", fake_bdnb)
    monkeypatch.setattr(main, "_area_risks", fake_risks)
    monkeypatch.setattr(main, "DVF_RPC_URL", "")  # real _dvf_prices short-circuits
    assert client.get("/v1/buildings/bdnb-bg-X").json()["prices"] is None


def test_report_pdf_with_prices():
    from app.report import build_report_pdf
    pdf = build_report_pdf({**BUILDING_FIXTURE, "prices": PRICES_FIXTURE})
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


# --- Traceability annex (issue #93) ------------------------------------------
def test_traceability_annex_exposes_source_key_date_link():
    from app.report import _traceability_annex
    data = {**BUILDING_FIXTURE, "prices": PRICES_FIXTURE}
    photos = [{"id": "pano-abc12345",
               "viewer": "https://api.panoramax.xyz/#focus=pic&pic=pano-abc12345",
               "date": "2023-04-01T10:00:00Z"}]
    h = _traceability_annex(data, photos)
    for src in ("BAN", "BDNB", "Géorisques", "DVF", "Panoramax"):
        assert src in h                       # every active source named
    assert "batiment_groupe_id = bdnb-bg-TEST" in h   # exact key
    assert "api.bdnb.io" in h                 # reproducible verify link
    assert "2024-05-01" in h                  # DPE reference date
    assert "pano-abc" in h                    # photo id


def test_traceability_annex_omits_absent_categories():
    from app.report import _traceability_annex
    data = {"query": {"bdnb_id": "bdnb-bg-X"}, "buildings": [{"bdnb_id": "bdnb-bg-X"}]}
    h = _traceability_annex(data, [])
    assert "BDNB" in h
    assert "DVF" not in h and "Géorisques" not in h and "Panoramax" not in h


def test_traceability_annex_dvf_unavailable_is_named_not_faked():
    from app.report import _traceability_annex
    data = {"query": {"bdnb_id": "bdnb-bg-X"}, "buildings": [{"bdnb_id": "bdnb-bg-X"}],
            "prices": {"available": False}}
    h = _traceability_annex(data, [])
    assert "DVF" in h and "indisponible" in h


def test_annex_dvf_link_is_a_deep_link(monkeypatch):
    from app.report import _traceability_annex
    data = {**BUILDING_FIXTURE, "prices": PRICES_FIXTURE}  # query has lon 2.3 / lat 48.8
    h = _traceability_annex(data, [])
    assert "explore.data.gouv.fr/fr/immobilier" in h
    assert "lat=48.8" in h and "lng=2.3" in h   # deep-linked to the property
    assert "app.dvf.etalab.gouv.fr" not in h    # not the bare app home


# --- 3D building map render on the context page (issue #88) -------------------
MAP_URI = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1Pe"
           "AAAADElEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")


def test_context_page_embeds_map_when_provided():
    from app.report import _context_page
    h = _context_page(BUILDING_FIXTURE, [], map_img=MAP_URI)
    assert 'class="map3d"' in h and MAP_URI in h and "Localisation" in h


def test_context_page_falls_back_to_osm_without_map():
    from app.report import _context_page
    h = _context_page(BUILDING_FIXTURE, [], map_img=None)
    assert "OpenStreetMap" in h and '<img class="map3d"' not in h


def test_report_pdf_with_map_render():
    import base64
    import io

    from PIL import Image

    from app.report import build_report_pdf
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    pdf = build_report_pdf(BUILDING_FIXTURE, map_img=uri)
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


def test_building_map_disabled_returns_none(monkeypatch):
    import asyncio
    monkeypatch.setattr(main, "RENDER_URL", "")   # not wired -> no map, no error
    assert asyncio.run(main._building_map_png(2.3, 48.8, "bdnb-bg-X")) is None
