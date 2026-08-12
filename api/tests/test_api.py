"""Hermetic tests for the existing public API (no network calls)."""

import asyncio
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


# --- Groundwater + solar PV (issue #119) --------------------------------------
GW_FIXTURE = {
    "available": True, "station_code_bss": "01837A0096/F2",
    "station_commune": "Paris 13e Arrondissement", "station_distance_m": 740,
    "water_table_depth_m": 0.39, "level_masl": 38.06, "measured_on": "2026-08-01",
    "note": "Profondeur mesurée au piézomètre le plus proche, pas sur la parcelle.",
    "well_regulation": "Déclaration en mairie (décret n° 2008-652).",
}
PV_FIXTURE = {
    "yield_kwh_per_kwc_y": 1146.21, "irradiation_kwh_m2_y": 1432.37,
    "optimal_tilt_deg": 39,
    "assumptions": "1 kWc, pertes système 14 %, inclinaison fixe optimale (PVGIS v5.2)",
}


def _route_fake(routes, calls=None):
    """Fake _cached_get_json dispatching on URL substring."""
    async def fake(url, params, ttl):
        if calls is not None:
            calls.append((url, params))
        for frag, resp in routes.items():
            if frag in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected upstream call: {url}")
    return fake


def test_groundwater_picks_nearest_active_station(monkeypatch):
    stations = {"data": [
        {"code_bss": "FAR/1", "x": 2.45, "y": 48.95, "nom_commune": "Loin"},
        {"code_bss": "NEAR/1", "x": 2.351, "y": 48.851, "nom_commune": "Près"},
    ]}
    chron = {"data": [{"profondeur_nappe": 3.2, "niveau_nappe_eau": 30.1,
                       "date_mesure": "2026-08-01"}]}
    calls = []
    monkeypatch.setattr(main, "_cached_get_json", _route_fake({
        "niveaux_nappes/stations": stations, "niveaux_nappes/chroniques": chron}, calls))
    gw = asyncio.run(main._groundwater(2.35, 48.85))
    # Hub'Eau's "in service at date" lags weeks behind reality: asking for
    # today's date returns zero stations everywhere — the filter must look back.
    import time as _time
    asked = [p["date_recherche"] for u, p in calls if "stations" in u][0]
    assert asked < _time.strftime("%Y-%m-%d", _time.gmtime(_time.time() - 30 * 86400))
    assert gw["available"] is True
    assert gw["station_code_bss"] == "NEAR/1"       # nearest wins
    assert gw["water_table_depth_m"] == 3.2
    assert gw["station_distance_m"] < 200            # honest distance, in metres


def test_groundwater_honest_when_no_active_station(monkeypatch):
    monkeypatch.setattr(main, "_cached_get_json",
                        _route_fake({"niveaux_nappes/stations": {"data": []}}))
    gw = asyncio.run(main._groundwater(2.35, 48.85))
    assert gw["available"] is False and "piézomètre" in gw["note"]


def test_solar_pv_block(monkeypatch):
    pvgis = {"inputs": {"mounting_system": {"fixed": {"slope": {"value": 39, "optimal": True}}}},
             "outputs": {"totals": {"fixed": {"E_y": 1146.21, "H(i)_y": 1432.37}}}}
    monkeypatch.setattr(main, "_cached_get_json", _route_fake({"PVcalc": pvgis}))
    pv = asyncio.run(main._solar_pv(2.35, 48.85))
    assert pv["yield_kwh_per_kwc_y"] == 1146.21 and pv["optimal_tilt_deg"] == 39


def test_building_includes_water_and_pv_and_degrades(monkeypatch):
    """A Hub'Eau/PVGIS failure never breaks the building record (#119)."""
    async def fake(url, params, ttl):
        if "PVcalc" in url or "niveaux_nappes" in url:
            raise RuntimeError("upstream down")
        return [{"batiment_groupe_id": "bdnb-bg-X", "libelle_adr_principale_ban": "1 rue X"}]
    async def fake_risks(lon, lat): return {}
    monkeypatch.setattr(main, "_cached_get_json", fake)
    monkeypatch.setattr(main, "_area_risks", fake_risks)
    monkeypatch.setattr(main, "DVF_RPC_URL", "")
    body = client.get("/v1/buildings/bdnb-bg-X", params={"lon": 2.35, "lat": 48.85}).json()
    assert body["buildings"][0]["bdnb_id"] == "bdnb-bg-X"
    assert body["groundwater"] is None and body["solar_pv"] is None
    assert not any("Hub'Eau" in s or "PVGIS" in s for s in body["sources"])


def test_groundwater_html_honest_wording():
    from app.report import _groundwater_html
    h = _groundwater_html(GW_FIXTURE)
    assert "0.39" in h and "740" in h and "pas sur la parcelle" in h
    assert _groundwater_html({}) == ""


def test_report_pdf_with_water_and_pv():
    from app.report import build_report_pdf
    pdf = build_report_pdf({**BUILDING_FIXTURE, "groundwater": GW_FIXTURE,
                            "solar_pv": PV_FIXTURE})
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


def test_building_titles_with_click_address_when_group_member(monkeypatch):
    """#152: a map click reverse-geocodes to the address at the click point;
    it is used ONLY when it belongs to the clicked bâtiment groupe."""
    def fakes(member: bool):
        async def fake(url, params, ttl):
            if "reverse" in url:
                return {"features": [{"properties": {
                    "id": "78575_0505_00002",
                    "label": "2 Allée des Peupliers 78470 Saint-Rémy-lès-Chevreuse"}}]}
            if "rel_batiment_groupe_adresse" in url:
                return [{"cle_interop_adr": "78575_0505_00002" if member else "OTHER"}]
            return [{"batiment_groupe_id": "bdnb-bg-X",
                     "libelle_adr_principale_ban": "5 Allée des Marronniers"}]
        return fake
    async def none2(*a, **k): return None
    for h in ("_area_risks", "_groundwater", "_solar_pv"):
        monkeypatch.setattr(main, h, none2)
    monkeypatch.setattr(main, "DVF_RPC_URL", "")

    monkeypatch.setattr(main, "_cached_get_json", fakes(member=True))
    body = client.get("/v1/buildings/bdnb-bg-X", params={"lon": 2.08, "lat": 48.70}).json()
    assert body["query"]["address"].startswith("2 Allée des Peupliers")
    assert body["buildings"][0]["address"] == "5 Allée des Marronniers"  # kept

    monkeypatch.setattr(main, "_cached_get_json", fakes(member=False))
    body = client.get("/v1/buildings/bdnb-bg-X", params={"lon": 2.08, "lat": 48.70}).json()
    assert body["query"]["address"] == "5 Allée des Marronniers"  # fallback


def test_l93_to_wgs84_against_ban_reference():
    """BDNB rel point for '1 Allée des Châtaigniers' (Lambert-93) must land on
    BAN's WGS84 coords for the same address (±~30 m)."""
    lon, lat = main._l93_to_wgs84(632314.41, 6844868.25)
    assert abs(lon - 2.080259) < 0.0005 and abs(lat - 48.700411) < 0.0005


def test_click_address_falls_back_to_nearest_group_address(monkeypatch):
    """#152 step 2: reverse hits a non-member (misleading street label case) ->
    title with the group's OWN nearest address instead."""
    async def fake(url, params, ttl):
        if "reverse" in url:
            return {"features": [{"properties": {"id": "NOT_A_MEMBER",
                                                 "label": "8 Allée des Peupliers"}}]}
        return [{"cle_interop_adr": "78575_0142_00001",
                 "libelle_adresse": "1 Allée des Châtaigniers 78470 Saint-Rémy-lès-Chevreuse",
                 "geom_adresse": {"coordinates": [632314.41, 6844868.25]}}]
    monkeypatch.setattr(main, "_cached_get_json", fake)
    got = asyncio.run(main._click_address("bdnb-bg-X", 2.0805, 48.7005))
    assert got == "1 Allée des Châtaigniers 78470 Saint-Rémy-lès-Chevreuse"
    # Too far away (> 150 m) -> no label rather than a wrong one.
    far = asyncio.run(main._click_address("bdnb-bg-X", 2.09, 48.71))
    assert far is None


def test_report_titles_with_searched_address_and_keeps_principal():
    """#146: a bâtiment groupe can span several streets. The fiche titles with
    the searched address and keeps BDNB's principal address visible."""
    from app.report import _report_html
    data = {**BUILDING_FIXTURE,
            "query": {**BUILDING_FIXTURE["query"], "address": "2 Allée des Peupliers 78470 X"}}
    html = _report_html(data)
    assert "<h1>2 Allée des Peupliers 78470 X</h1>" in html
    assert "adresse principale : 1 Rue de Test 75001 Paris" in html
    # Same address on both sides -> no redundant note.
    html2 = _report_html(BUILDING_FIXTURE)
    assert "adresse principale" not in html2


def test_report_endpoint_accepts_searched_address(monkeypatch):
    async def fake_upstream(url, params, ttl):
        if "api-adresse" in url:
            return {"features": []}
        return [{"batiment_groupe_id": "bdnb-bg-X",
                 "libelle_adr_principale_ban": "5 Allée des Marronniers"}]
    async def none3(*a, **k): return None
    monkeypatch.setattr(main, "_cached_get_json", fake_upstream)
    for h in ("_area_risks", "_groundwater", "_solar_pv", "_dvf_prices",
              "_building_map_png"):
        monkeypatch.setattr(main, h, none3)
    monkeypatch.setattr(main, "_nearby_photos", none3)
    r = client.get("/v1/report/bdnb-bg-X.pdf",
                   params={"address": "2 Allée des Peupliers"})
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"


def test_report_tables_wrap_long_values():
    """Long unbroken values (Géorisques URL, risk lists) must wrap, not run off
    the page edge (reported on the prod fiche, Tournefeuille)."""
    from app.report import _report_html
    long_url = "https://www.georisques.gouv.fr/mes-risques/connaitre?" + "x" * 300
    html = _report_html({**BUILDING_FIXTURE,
                         "area_risks": {**BUILDING_FIXTURE["area_risks"], "report_url": long_url}})
    style = html.split("</style>")[0]
    assert "table-layout: fixed" in style and "overflow-wrap" in style
    assert long_url in html


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


def test_building_map_enabled_returns_datauri(monkeypatch):
    # When RENDER_URL is wired (as in prod), the render bytes are returned as a
    # PNG data URI for embedding in the report's context page (#88).
    import asyncio
    import base64
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(buf, "PNG")
    png = buf.getvalue()

    class _Resp:
        content = png

        def raise_for_status(self):
            pass

    async def _fake_get(url, params=None, timeout=None):
        assert url == "http://render/shot" and params["bdnb_id"] == "bdnb-bg-X"
        return _Resp()

    monkeypatch.setattr(main, "RENDER_URL", "http://render/shot")
    monkeypatch.setattr(main._client, "get", _fake_get)
    out = asyncio.run(main._building_map_png(2.3, 48.8, "bdnb-bg-X"))
    assert out.startswith("data:image/png;base64,")
    assert base64.b64decode(out.split(",", 1)[1]) == png
