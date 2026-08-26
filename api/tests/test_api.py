"""Hermetic tests for the existing public API (no network calls)."""

import asyncio
import json

import pytest
from fastapi import HTTPException
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


def test_lead_email_skips_without_creds(monkeypatch):
    """#196: no SMTP env (CI/dev) -> quietly skipped, never raises."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert main._send_lead_email({"email": "x@y.z"}) is False


def test_lead_persisted_even_when_email_fails(tmp_path, monkeypatch):
    """#196: the lead is saved first; a failing relay never breaks the form."""
    path = tmp_path / "leads.jsonl"
    monkeypatch.setattr(main, "LEADS_PATH", str(path))
    def boom(rec):
        raise RuntimeError("relay down")
    monkeypatch.setattr(main, "_send_lead_email", boom)
    r = client.post("/v1/leads", json={"email": "e2e@test.io", "org": "X", "need": "y"})
    assert r.status_code == 204
    assert "e2e@test.io" in path.read_text()


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


def test_dia_market_block(tmp_path, monkeypatch):
    """DIA (#246) : sous-quartier par point-in-polygon, commune par INSEE en
    repli, None hors métropole ou sans fichier — et le libellé dit bien
    « mise en vente », pas prix final."""
    import json
    f = tmp_path / "dia.json"
    f.write_text(json.dumps({"updated": "2026-08-19", "source": "test", "zones": [
        {"name": "Centre", "commune": "Montpellier", "n_12m": 40, "n_3m": 9,
         "median_asking_eur": 250000, "median_asking_eur_m2": 4200,
         "types": {"Appartement": 30},
         "polygon": {"type": "Polygon",
                     "coordinates": [[[3.86, 43.60], [3.88, 43.60],
                                      [3.88, 43.62], [3.86, 43.62], [3.86, 43.60]]]}},
        {"name": "Lattes", "commune_insee": "34129", "n_12m": 12, "n_3m": 2,
         "median_asking_eur": 300000, "median_asking_eur_m2": None,
         "types": {"Maison": 10}},
    ]}))
    monkeypatch.setattr(main, "DIA_PATH", str(f))
    monkeypatch.setattr(main, "_dia_state", {"mtime": None, "data": None})
    m = main._dia_market(3.87, 43.61, None)          # dans le polygone
    assert m["zone"] == "Centre" and m["scope"] == "sous-quartier"
    assert "mise en vente" in m["note"]
    m = main._dia_market(4.5, 44.0, "34129")          # hors polygone -> commune
    assert m["zone"] == "Lattes" and m["scope"] == "commune"
    assert main._dia_market(2.0, 48.0, "75056") is None   # hors métropole
    monkeypatch.setattr(main, "DIA_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setattr(main, "_dia_state", {"mtime": None, "data": None})
    assert main._dia_market(3.87, 43.61, "34172") is None  # fichier absent


def test_building_includes_rnb_id(monkeypatch):
    """ID-RNB : la clé pivot (cadastre/BAN/BDNB/ADEME) est jointe au bâtiment
    et à la liste des sources ; son absence ne casse rien."""
    async def fake_bdnb(url, params, ttl):
        if "rnb" in url:
            return {"results": [
                {"rnb_id": "LOIN12345678", "point": {"coordinates": [2.2, 48.9]}},
                {"rnb_id": "ABCD1234EFGH", "point": {"coordinates": [2.0816, 48.7021]}}]}
        return [{"batiment_groupe_id": "bdnb-bg-R", "libelle_adr_principale_ban": "1 rue R"}]
    async def none1(*a, **k): return None
    async def norisk(lon, lat): return {}
    monkeypatch.setattr(main, "_cached_get_json", fake_bdnb)
    monkeypatch.setattr(main, "_dvf_prices", none1)
    monkeypatch.setattr(main, "_area_risks", norisk)
    body = client.get("/v1/buildings/bdnb-bg-R", params={"lon": 2.0815, "lat": 48.7020}).json()
    assert body["rnb"]["rnb_id"] == "ABCD1234EFGH"       # le PLUS PROCHE, pas le premier
    assert body["buildings"][0]["rnb_id"] == "ABCD1234EFGH"
    assert any("RNB" in x for x in body["sources"])
    main._CACHE.clear()
    async def rnb_down(url, params, ttl):
        if "rnb" in url:
            raise RuntimeError("down")
        return [{"batiment_groupe_id": "bdnb-bg-R", "libelle_adr_principale_ban": "1 rue R"}]
    monkeypatch.setattr(main, "_cached_get_json", rnb_down)
    body = client.get("/v1/buildings/bdnb-bg-R", params={"lon": 2.0815, "lat": 48.7020}).json()
    assert body["rnb"] is None and "rnb_id" not in body["buildings"][0]


def test_building_aggregate_is_cached(monkeypatch):
    """Cache de l'agrégat (demande opérateur) : recharger la même fiche ne
    refait PAS l'orchestration ; et muter la réponse servie ne contamine pas
    l'entrée (le route PDF réécrit query.address)."""
    calls = {"n": 0}
    async def fake_bdnb(url, params, ttl):
        calls["n"] += 1
        return [{"batiment_groupe_id": "bdnb-bg-C", "libelle_adr_principale_ban": "1 rue C"}]
    async def fake_prices(bid): return None
    async def fake_risks(lon, lat): return {}
    monkeypatch.setattr(main, "_cached_get_json", fake_bdnb)
    monkeypatch.setattr(main, "_dvf_prices", fake_prices)
    monkeypatch.setattr(main, "_area_risks", fake_risks)
    b1 = client.get("/v1/buildings/bdnb-bg-C").json()
    n_after_first = calls["n"]
    b1["query"]["address"] = "MUTATION"          # ce que fait la route PDF
    b2 = client.get("/v1/buildings/bdnb-bg-C").json()
    assert calls["n"] == n_after_first            # aucun appel amont de plus
    assert b2["query"]["address"] != "MUTATION"   # copie défensive
    # une position différente = une autre clé (l'arbitrage d'adresse en dépend)
    client.get("/v1/buildings/bdnb-bg-C", params={"lon": 2.1, "lat": 48.7})
    assert calls["n"] > n_after_first


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

    main._CACHE.clear()   # même bâtiment, même position : purger l'agrégat
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
    def fake_with(dist):
        async def fake(url, params, ttl):
            if "reverse" in url:
                return {"features": [{"properties": {"id": "NOT_A_MEMBER",
                                                     "label": "8 Allée des Peupliers",
                                                     "distance": dist}}]}
            return [{"cle_interop_adr": "78575_0142_00001",
                     "libelle_adresse": "1 Allée des Châtaigniers 78470 Saint-Rémy-lès-Chevreuse",
                     "geom_adresse": {"coordinates": [632314.41, 6844868.25]}}]
        return fake
    # Reverse ON the building (9 m) beats an unreliable BDNB relation.
    monkeypatch.setattr(main, "_cached_get_json", fake_with(9))
    assert asyncio.run(main._click_address("bdnb-bg-X", 2.0805, 48.7005)) == "8 Allée des Peupliers"
    # Reverse 80 m off -> fall back to the group's own nearest address.
    monkeypatch.setattr(main, "_cached_get_json", fake_with(80))
    got = asyncio.run(main._click_address("bdnb-bg-X", 2.0805, 48.7005))
    assert got == "1 Allée des Châtaigniers 78470 Saint-Rémy-lès-Chevreuse"
    # Everything far away -> no label rather than a wrong one.
    far = asyncio.run(main._click_address("bdnb-bg-X", 2.12, 48.75))
    assert far is None


def test_water_network_picks_latest_year_with_indicator(monkeypatch):
    """#171: SISPEA years are sporadic — take the LATEST row carrying P104.3."""
    async def fake(url, params, ttl):
        return {"data": [
            {"annee": 2015, "nom_commune": "X", "indicateurs": {"P104.3": 85.8, "D102.0": 3.27}},
            {"annee": 2021, "nom_commune": "X", "indicateurs": {"P104.3": None}},
            {"annee": 2019, "nom_commune": "X", "indicateurs": {"P104.3": 79.4}},
        ]}
    monkeypatch.setattr(main, "_cached_get_json", fake)
    wn = asyncio.run(main._water_network("78575"))
    assert wn["year"] == 2019 and wn["efficiency_pct"] == 79.4
    assert wn["losses_pct"] == 20.6 and wn["commune_insee"] == "78575"
    assert asyncio.run(main._water_network(None)) is None


def test_water_network_html_renders():
    from app.report import _water_network_html
    h = _water_network_html({"efficiency_pct": 70.0, "losses_pct": 30.0,
                             "year": 2019, "price_eur_m3": 4.1})
    assert "70.0 %" in h and "30.0 %" in h and "(2019)" in h and "4.1 €/m³" in h
    assert _water_network_html({}) == ""


def test_official_dpe_chain(monkeypatch):
    """#189: BDNB rep-logement -> ADEME observatoire, 10-year validity."""
    async def fake(url, params, ttl):
        if "dpe_representatif" in url:
            return [{"identifiant_dpe": "2678E0726918P",
                     "date_etablissement_dpe": "2026-03-12T23:00:00",
                     "surface_habitable_logement": 106.17,
                     "conso_5_usages_ef_m2": 215.0}]
        if "data.ademe.fr" in url:
            assert params["qs"] == 'numero_dpe:"2678E0726918P"'
            return {"results": [{"cout_total_5_usages": 2573.2,
                                 "cout_chauffage": 2093.1,
                                 "qualite_isolation_enveloppe": "insuffisante",
                                 "description_installation_chauffage_n1": "Chaudière gaz",
                                 "type_energie_n1": "Gaz naturel"}]}
        raise AssertionError(url)
    monkeypatch.setattr(main, "_cached_get_json", fake)
    od = asyncio.run(main._official_dpe("bdnb-bg-X"))
    assert od["dpe_number"] == "2678E0726918P"
    assert od["valid_until"] == "2036-03-12"      # legal 10-year validity
    assert od["annual_cost_eur"] == 2573.2
    assert od["insulation"]["enveloppe"] == "insuffisante"
    assert od["energies"] == ["Gaz naturel"]


def test_official_dpe_absent_is_none(monkeypatch):
    async def fake(url, params, ttl): return []
    monkeypatch.setattr(main, "_cached_get_json", fake)
    assert asyncio.run(main._official_dpe("bdnb-bg-X")) is None


def test_official_dpe_html_and_pdf():
    from app.report import _official_dpe_html, build_report_pdf
    od = {"dpe_number": "2678E0726918P", "established_on": "2026-03-12",
          "valid_until": "2036-03-12", "surface_habitable_m2": 106.17,
          "annual_cost_eur": 2573.2, "heating": "Chaudière gaz",
          "insulation": {"enveloppe": "insuffisante"}, "energies": ["Gaz naturel"]}
    h = _official_dpe_html(od)
    assert "2678E0726918P" in h and "2 573 €/an" in h and "logement représentatif" in h
    assert _official_dpe_html({}) == ""
    pdf = build_report_pdf({**BUILDING_FIXTURE, "official_dpe": od})
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


def test_local_taxes_block(monkeypatch):
    async def fake(url, params, ttl):
        assert 'insee_com="78575"' in params["where"]
        return {"results": [{"exercice": "2025", "taux_global_tfb": 29.58,
                             "taux_global_tfnb": 89.91, "taux_plein_teom": 5.51,
                             "q03": "CC de la Haute Vallée de Chevreuse"}]}
    monkeypatch.setattr(main, "_cached_get_json", fake)
    t = asyncio.run(main._local_taxes("78575"))
    assert t["property_tax_built_pct"] == 29.58 and t["waste_tax_pct"] == 5.51
    assert asyncio.run(main._local_taxes(None)) is None


def test_nearby_schools_sorted(monkeypatch):
    async def fake(url, params, ttl):
        return {"results": [
            {"nom_etablissement": "Loin", "type_etablissement": "Ecole",
             "statut_public_prive": "Public", "position": {"lon": 2.10, "lat": 48.71}},
            {"nom_etablissement": "Près", "type_etablissement": "Collège",
             "statut_public_prive": "Public", "position": {"lon": 2.082, "lat": 48.702}},
        ]}
    monkeypatch.setattr(main, "_cached_get_json", fake)
    sc = asyncio.run(main._nearby_schools(2.0815, 48.7020))
    assert sc["within_2km"] == 2
    assert sc["nearest"][0]["name"] == "Près"          # sorted by distance
    assert sc["nearest"][0]["distance_m"] < sc["nearest"][1]["distance_m"]


def test_taxes_and_schools_html():
    from app.report import _local_taxes_html, _schools_html
    h = _local_taxes_html({"year": "2025", "property_tax_built_pct": 29.58,
                           "waste_tax_pct": 5.51, "intercommunalite": "CC X"})
    assert "29.58 %" in h and "TEOM" in h and "(2025)" in h
    assert _local_taxes_html({}) == ""
    h2 = _schools_html({"within_2km": 8, "nearest": [
        {"name": "Jean Moulin", "type": "Ecole", "statut": "Public", "distance_m": 240}]})
    assert "Jean Moulin" in h2 and "240 m" in h2 and "sectorisation" in h2
    assert _schools_html({}) == ""


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

# --- Pay-as-you-go metering (#201) -------------------------------------------
def test_pro_tier_grid_v4():
    """Pricing v4 (bascule Creem, 2026-08-17) : paliers fixes, plus de metering.
    Pro S 9 € (30 fiches) · Pro M 29 € (100) · Pro L 99 € (illimité fair-use).
    Le simulateur recommande le plus petit palier couvrant le volume."""
    from app.main import _usage_cost, _tier_for, CREDIT_COST, PRO_TIERS
    assert CREDIT_COST["report"] == 1 and CREDIT_COST["lookup"] == 0
    assert PRO_TIERS["s"]["eur"] == 9 and PRO_TIERS["s"]["fiches"] == 30
    assert PRO_TIERS["m"]["eur"] == 29 and PRO_TIERS["m"]["fiches"] == 100
    assert PRO_TIERS["l"]["eur"] == 99 and PRO_TIERS["l"]["fiches"] is None
    assert _usage_cost(0)["cost_eur"] == 0.0        # rien consommé, rien dû
    assert _usage_cost(10)["cost_eur"] == 0.0       # couvert par le compte gratuit
    assert _tier_for(30) == "s" and _usage_cost(30)["cost_eur"] == 9.0
    assert _tier_for(31) == "m" and _usage_cost(100)["cost_eur"] == 29.0
    assert _tier_for(101) == "l" and _usage_cost(10_000)["cost_eur"] == 99.0
    tiers = _usage_cost(0)["free_tiers"]
    assert tiers["anonymous_reports_month"] == 10
    assert tiers["free_account_reports_month"] == 10


def test_quota_preflight_reads_without_consuming(tmp_path, monkeypatch):
    """/v1/quota (pré-vol) : mêmes seaux que la barrière, AUCUNE consommation —
    deux lectures successives rendent le même reste."""
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    import hashlib
    ip_bucket = "ip:" + hashlib.sha256(b"1.2.3.4").hexdigest()[:16]
    main._usage_add(ip_bucket, 2)                    # 2 fiches déjà prises
    h = {"X-Forwarded-For": "1.2.3.4"}
    q1 = client.get("/v1/quota", headers=h).json()
    q2 = client.get("/v1/quota", headers=h).json()
    assert q1 == q2                                   # lecture seule
    assert q1["plan"] == "anonymous"
    assert q1["reports_used"] == 2
    assert q1["reports_left"] == main.ANON_MONTHLY_REPORTS - 2
    # compte gratuit par clé
    monkeypatch.setattr(main, "_load_keys", lambda: {"K1"})
    kq = client.get("/v1/quota", headers={"X-API-Key": "K1"}).json()
    assert kq["plan"] == "free" and kq["reports_included"] == 10


def test_usage_counter_accumulates_per_month(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    assert main._usage_add("key1", 1) == 1
    assert main._usage_add("key1", 5) == 6         # a PDF fiche costs 5
    assert main._usage_add("key2", 2) == 2         # per-customer isolation
    month = main._month_key()
    assert main._usage_load()[month] == {"key1": 6, "key2": 2}


def test_usage_endpoint_requires_key_and_reports_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(main, "_load_keys", lambda: {"K1"})
    assert client.get("/v1/usage").status_code == 401
    import hashlib
    kid = hashlib.sha256(b"K1").hexdigest()[:16]
    main._usage_add(kid, 20)                       # 20 fiches this month
    body = client.get("/v1/usage", headers={"X-API-Key": "K1"}).json()
    # A FREE account sees its allowance, not a bill (#206).
    assert body["plan"] == "free" and body["cost_eur"] == 0.0
    assert body["reports_used"] == 20 and body["reports_left"] == 0
    # A PRO subscriber sees the fixed tier price and the tier allowance (v4).
    monkeypatch.setattr(main, "_key_plans", lambda: {"K1": "pro"})
    monkeypatch.setattr(main, "_key_owners", lambda: {"K1": "sub-1"})
    monkeypatch.setattr(main, "_pro_tier", lambda sub: "s")
    pro = client.get("/v1/usage", headers={"X-API-Key": "K1"}).json()
    assert pro["plan"] == "pro" and pro["tier"] == "s"
    assert pro["cost_eur"] == 9.0
    assert pro["reports_used"] == 20 and pro["reports_left"] == 10   # sur 30


def test_pricing_simulator_matches_frontend_formula():
    """The public simulator and the offres.html script must agree: both
    recommend the smallest tier covering the monthly volume (v4)."""
    body = client.get("/v1/pricing", params={"credits": 100}).json()
    assert body["recommended_tier"] == "m" and body["cost_eur"] == 29.0
    assert body["credit_costs"]["report"] == 1        # one unit = one fiche
    assert body["tiers"]["l"]["fiches_month"] is None  # illimité fair-use
    assert client.get("/v1/pricing", params={"credits": 8}).json()["cost_eur"] == 0.0


def test_keyed_call_consumes_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(main, "_load_keys", lambda: {"K1"})
    async def fake(url, params, ttl):
        if "api-adresse" in url:
            return {"features": [{"properties": {"id": "1", "label": "X"},
                                  "geometry": {"coordinates": [2.0, 48.0]}}]}
        return []
    async def none2(*a, **k): return None
    monkeypatch.setattr(main, "_cached_get_json", fake)
    for h in ("_area_risks", "_groundwater", "_solar_pv", "_water_network",
              "_local_taxes", "_nearby_schools", "_official_dpe"):
        monkeypatch.setattr(main, h, none2)
    client.get("/v1/lookup", params={"q": "x"}, headers={"X-API-Key": "K1"})
    import hashlib
    kid = hashlib.sha256(b"K1").hexdigest()[:16]
    # Raw API calls are FREE in v3: only fiches are billed (#224).
    assert (main._usage_load().get(main._month_key()) or {}).get(kid) is None

def test_free_tiers_enforced(tmp_path, monkeypatch):
    """#206: anonymous 10 fiches/month per IP, free account 30/month, pro
    never blocked (metered + capped instead)."""
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(main, "_load_keys", lambda: {"FREEKEY", "PROKEY"})
    monkeypatch.setattr(main, "_key_plans", lambda: {"FREEKEY": "free", "PROKEY": "pro"})

    class Req:
        def __init__(self, key=None, ip="10.0.0.1"):
            self.headers = {"x-forwarded-for": ip} | ({"x-api-key": key} if key else {})
            self.query_params = {}

    for _ in range(main.ANON_MONTHLY_REPORTS):          # 10 allowed
        assert main._quota_gate(Req(), "report") == "anon"
    with pytest.raises(HTTPException) as e:             # the 11th converts
        main._quota_gate(Req(), "report")
    assert "compte gratuit" in e.value.detail.lower()

    import hashlib
    kid = hashlib.sha256(b"FREEKEY").hexdigest()[:16]
    main._usage_add(kid, main.FREE_ACCOUNT_REPORTS)
    with pytest.raises(HTTPException) as e2:            # free account exhausted
        main._quota_gate(Req("FREEKEY"), "report")
    assert "Pro" in e2.value.detail

    pid = hashlib.sha256(b"PROKEY").hexdigest()[:16]
    main._usage_add(pid, 10_000)                        # way past any allowance
    assert main._quota_gate(Req("PROKEY"), "report") == "key"   # never blocked

def test_registered_user_gets_the_free_account_ladder(tmp_path, monkeypatch):
    """#206: a signed-in browser user (no API key) consumes the free-account
    allowance, and a subscriber is never blocked."""
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(main, "_load_keys", lambda: set())
    monkeypatch.setattr(main, "_decode_token", lambda t: {"sub": "user-1"})
    monkeypatch.setattr(main, "_pro_active", lambda sub: False)

    class Req:
        headers = {"authorization": "Bearer x", "x-forwarded-for": "10.0.0.9"}
        query_params: dict = {}

    for _ in range(main.FREE_ACCOUNT_REPORTS):
        assert main._quota_gate(Req(), "report") == "user_free"
    with pytest.raises(HTTPException) as e:
        main._quota_gate(Req(), "report")
    assert "Pro" in e.value.detail                    # upsell, not a dead end

    monkeypatch.setattr(main, "_pro_active", lambda sub: True)
    assert main._quota_gate(Req(), "report") == "user_pro"   # never blocked


def test_key_plan_follows_the_account_subscription(tmp_path, monkeypatch):
    """A subscription attaches to the ACCOUNT: every key of that user turns pro
    (and back) without touching keys.jsonl (#206)."""
    monkeypatch.setattr(main, "_key_owners", lambda: {"K-A": "user-1", "K-B": "user-2"})
    monkeypatch.setattr(main, "_pro_active", lambda sub: sub == "user-1")
    plans = main._key_plans()
    assert plans == {"K-A": "pro", "K-B": "free"}

def test_keys_listing_is_scoped_and_masked(tmp_path, monkeypatch):
    """#220: a user sees THEIR keys, masked — the value is shown once at
    creation and can never be recovered from the listing."""
    import json as _json
    path = tmp_path / "keys.jsonl"
    path.write_text(
        _json.dumps({"key": "eco_MINE_abcdefgh", "sub": "me", "created": "2026-08-01T00:00:00Z"}) + "\n" +
        _json.dumps({"key": "eco_THEIRS_zzzzzz", "sub": "other", "created": "2026-08-02T00:00:00Z"}) + "\n")
    monkeypatch.setattr(main, "KEYS_PATH", str(path))
    monkeypatch.setattr(main, "_decode_token", lambda t: {"sub": "me"})
    monkeypatch.setattr(main, "_pro_active", lambda sub: False)
    body = client.get("/v1/keys", headers={"Authorization": "Bearer x"}).json()
    assert body["count"] == 1                        # only mine
    masked = body["keys"][0]["masked"]
    assert "eco_MINE_abcdefgh" not in masked and masked.startswith("eco_")
    assert client.get("/v1/keys").status_code == 401  # session required


def test_config_exposes_payment_mode(monkeypatch):
    """#221: the UI must be able to warn that payments are in SANDBOX mode —
    provider-aware since the Creem switch (rule 21)."""
    monkeypatch.setattr(main, "PAYMENT_PROVIDER", "none")
    assert client.get("/v1/config").json()["payment_mode"] == "disabled"
    monkeypatch.setattr(main, "PAYMENT_PROVIDER", "creem")
    monkeypatch.setattr(main, "CREEM_API_BASE", "https://test-api.creem.io/v1")
    body = client.get("/v1/config").json()
    assert body["payment_mode"] == "sandbox" and body["payment_provider"] == "creem"
    assert body["pro_tiers"]["s"]["eur"] == 9          # la grille arrive au front
    monkeypatch.setattr(main, "CREEM_API_BASE", "https://api.creem.io/v1")
    assert client.get("/v1/config").json()["payment_mode"] == "live"
    monkeypatch.setattr(main, "PAYMENT_PROVIDER", "polar")
    monkeypatch.setattr(main, "POLAR_BASE_URL", "https://sandbox-api.polar.sh")
    assert client.get("/v1/config").json()["payment_mode"] == "sandbox"

def test_polar_checkout_omits_empty_metadata(monkeypatch):
    """Polar rejects empty metadata values (422): a user without an `org`
    claim must still be able to subscribe."""
    sent = {}
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"url": "https://sandbox.polar.sh/checkout/x", "id": "c1"}
    async def fake_post(url, json=None, headers=None):
        sent.update(json or {})
        return Resp()
    monkeypatch.setattr(main, "POLAR_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(main, "POLAR_PRODUCT_ID", "prod")
    monkeypatch.setattr(main._client, "post", fake_post)
    monkeypatch.setattr(main, "_decode_token",
                        lambda t: {"sub": "u-1", "email": "u@x.io"})   # no org claim
    r = client.get("/v1/pro/checkout", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200, r.text
    assert sent["metadata"] == {"kc_sub": "u-1"}          # no empty values
    assert "" not in sent["metadata"].values()

def test_pro_reconciles_without_webhook(tmp_path, monkeypatch):
    """#228: a paid subscription must activate even if the webhook never
    arrives — and the check must be cached and failure-safe."""
    monkeypatch.setattr(main, "PRO_PATH", str(tmp_path / "pro.json"))
    monkeypatch.setattr(main, "POLAR_ACCESS_TOKEN", "tok")
    main._pro_check.clear()
    calls = {"n": 0}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"items": [{"id": "sub_1"}]}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None, headers=None):
            calls["n"] += 1
            return Resp()
    monkeypatch.setattr(main.httpx, "Client", FakeClient)

    assert main._pro_active("user-9") is True        # reconciled from Polar
    assert calls["n"] == 1
    assert main._pro_active("user-9") is True        # served from pro.json now
    assert calls["n"] == 1                            # no second upstream call
    assert main._pro_load()["user-9"]["status"] == "active"


def test_pro_reconciliation_failure_never_grants_access(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PRO_PATH", str(tmp_path / "pro.json"))
    monkeypatch.setattr(main, "POLAR_ACCESS_TOKEN", "tok")
    main._pro_check.clear()
    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise RuntimeError("polar down")
    monkeypatch.setattr(main.httpx, "Client", Boom)
    assert main._pro_active("user-x") is False       # fails closed, no crash


def test_lookup_and_report_share_one_aggregate(monkeypatch):
    """Demande opérateur : « charger une fois, pas deux ».

    La recherche par adresse (/v1/lookup) faisait son propre éventail de
    sources, puis la fiche PDF — qui passe par building() — ne trouvait rien en
    cache et rejouait l'orchestration complète (mesuré en sandbox : 5,7 s de
    panneau, puis 15,2 s refaits). Les deux doivent désormais partager le même
    agrégat mis en cache : le second appel ne touche plus l'amont.
    """
    calls = []

    async def fake_get(url, params, ttl=0):
        calls.append(url)
        if "reverse" in url or "adresse.data.gouv" in url:
            return {"features": [{"properties": {"id": "34172_1234_00008",
                                                 "label": "8 rue de la Loge 34000 Montpellier"},
                                  "geometry": {"coordinates": [3.8767, 43.6108]}}]}
        return [{"batiment_groupe_id": "bdnb-bg-ONCE",
                 "libelle_adr_principale_ban": "8 rue de la Loge 34000 Montpellier",
                 "code_commune_insee": "34172"}]

    monkeypatch.setattr(main, "_cached_get_json", fake_get)
    for name in ("_area_risks", "_groundwater", "_solar_pv", "_water_network",
                 "_official_dpe", "_local_taxes", "_nearby_schools",
                 "_dvf_prices", "_rnb_lookup", "_click_address"):
        async def none(*a, _n=name, **k):
            calls.append(_n)
            return None
        monkeypatch.setattr(main, name, none)

    r1 = client.get("/v1/lookup?q=8+rue+de+la+Loge+Montpellier")
    assert r1.status_code == 200
    body = r1.json()
    # La recherche par adresse hérite du calcul canonique : elle expose
    # désormais les blocs qui lui manquaient (prix DVF, RNB).
    assert "prices" in body and "rnb" in body
    assert body["query"]["q"] == "8 rue de la Loge Montpellier"
    assert body["buildings"][0]["bdnb_id"] == "bdnb-bg-ONCE"

    after_lookup = len(calls)
    lon, lat = body["query"]["lon"], body["query"]["lat"]
    r2 = client.get(f"/v1/buildings/bdnb-bg-ONCE?lon={lon}&lat={lat}")
    assert r2.status_code == 200
    assert len(calls) == after_lookup, \
        "la fiche PDF a rejoué l'orchestration au lieu de lire le cache"


# --- Nom de la fiche PDF (#282) ----------------------------------------------
#
# Une fiche envoyée à une professionnelle de l'immobilier est arrivée nommée
# « 9e2a675e-ea29-4758-9761-bfbf31ad39d1.pdf ». Un document qui se classe, se
# transfère à un notaire ou à un client doit porter le nom sous lequel le bien
# existe : son adresse.

def test_la_fiche_porte_l_adresse_et_non_un_identifiant():
    import app.main as main

    nom = main._nom_de_fiche("21 Rue de l'Aiguillerie 34000 Montpellier", "bdnb-bg-X")
    assert nom == "EcoBuilding — 21 Rue de l'Aiguillerie 34000 Montpellier.pdf"
    assert "bdnb" not in nom


def test_sans_adresse_on_garde_l_identifiant_plutot_que_d_inventer():
    import app.main as main

    assert main._nom_de_fiche(None, "bdnb-bg-X") == "EcoBuilding — bdnb-bg-X.pdf"
    assert main._nom_de_fiche("   ", "bdnb-bg-X") == "EcoBuilding — bdnb-bg-X.pdf"


def test_les_caracteres_interdits_par_les_systemes_de_fichiers_tombent():
    import app.main as main

    nom = main._nom_de_fiche('A/B: rue "test" <x>|y', "bdnb-bg-X")
    assert not set(nom) & set('/\\:*?"<>|')


def test_un_nom_trop_long_est_tronque_sur_un_mot():
    import app.main as main

    nom = main._nom_de_fiche("rue " + "tres longue " * 20, "bdnb-bg-X")
    assert len(nom) < 140
    assert not nom.replace(".pdf", "").endswith(" ")


def test_l_entete_transporte_les_accents_sans_casser_les_clients_anciens():
    """`filename=` ne transporte que de l'ASCII : « Aiguillerie » y perdrait
    ses accents. `filename*` (RFC 5987) porte l'UTF-8, et l'ASCII reste là."""
    import app.main as main

    d = main._disposition("EcoBuilding — 3 rue de l'Église, Sète.pdf")
    assert d.startswith("inline; filename=\"")
    assert "filename*=UTF-8''" in d
    assert "%C3%89glise" in d          # É encodé, donc préservé
    ascii_part = d.split('"')[1]
    assert ascii_part.isascii() and "  " not in ascii_part
