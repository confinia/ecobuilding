"""Ventes autour, médiane du quartier et tendance (#426), sans réseau."""
import asyncio

import app.main as main
from app import report

AUTOUR = {
    "radius_m": 250, "n": 20,
    "sales": [{"date": "2025-12-05", "type_local": "Maison", "surface_m2": 160, "pieces": 7,
               "valeur_fonciere": 355000, "eur_m2": 2219, "distance_m": 40}],
    "area_eur_m2": {"Maison": {"n": 17, "median": 2988}},
    "trend": {"area": {}, "commune": {"Maison": [
        {"year": 2021, "median": 3149, "n": 237}, {"year": 2025, "median": 3100, "n": 191}]}},
    "source": "DVF (DGFiP) / Etalab — Licence Ouverte 2.0",
}
PARCELLE = {"available": True, "sales": [], "commune_code": "31149",
            "commune_eur_m2": {"Maison": {"n": 982, "median": 3150}}}


def test_le_bloc_prix_ajoute_quartier_et_tendance(monkeypatch):
    appels = []

    async def prix(bid):
        return PARCELLE

    async def get(url, params, ttl=0):
        appels.append((url, params))
        return AUTOUR

    monkeypatch.setattr(main, "DVF_AROUND_URL", "http://dvf/rpc/prices_around")
    monkeypatch.setattr(main, "_dvf_prices", prix)
    monkeypatch.setattr(main, "_cached_get_json", get)
    out = asyncio.run(main._prix_complets("bdnb-bg-X", 1.3382331, 43.6070861, "31149"))
    assert out["commune_eur_m2"] == PARCELLE["commune_eur_m2"]          # inchangé : apps publiées
    assert out["around"]["area_eur_m2"]["Maison"]["median"] == 2988
    assert out["trend"]["commune"]["Maison"][-1]["year"] == 2025
    assert appels == [("http://dvf/rpc/prices_around",
                       {"lon": 1.33823, "lat": 43.60709, "commune": "31149"})]


def test_sans_service_autour_le_bloc_reste_celui_d_avant(monkeypatch):
    async def prix(bid):
        return PARCELLE
    monkeypatch.setattr(main, "DVF_AROUND_URL", "")
    monkeypatch.setattr(main, "_dvf_prices", prix)
    assert asyncio.run(main._prix_complets("bdnb-bg-X", 1.3, 43.6, "31149")) == PARCELLE


def test_sans_point_on_prend_le_centre_du_batiment(monkeypatch):
    vus = []

    async def prix(bid):
        return None

    async def point(bid):
        return (1.5, 43.5)

    async def get(url, params, ttl=0):
        vus.append(params)
        return AUTOUR
    monkeypatch.setattr(main, "DVF_AROUND_URL", "http://dvf/rpc/prices_around")
    monkeypatch.setattr(main, "_dvf_prices", prix)
    monkeypatch.setattr(main, "_building_point", point)
    monkeypatch.setattr(main, "_cached_get_json", get)
    out = asyncio.run(main._prix_complets("bdnb-bg-X", None, None, None))
    assert vus == [{"lon": 1.5, "lat": 43.5}]
    assert out["available"] is True and out["around"]["n"] == 20


def test_le_pdf_montre_quartier_tendance_et_ventes_autour():
    h = report._prices_html({**PARCELLE, "around": {k: AUTOUR[k] for k in ("radius_m", "n", "sales", "area_eur_m2")},
                             "trend": AUTOUR["trend"]})
    assert "rayon de 250 m" in h
    assert "2021 : 3 149 → 2025 : 3 100 €/m² (-2 %)" in h or "2021 : 3 149 → 2025 : 3 100 €/m² (-2 %)" in h
    assert "Ventes les plus récentes autour du bâtiment" in h and "40 m" in h


def test_pas_de_mediane_sous_dix_ventes_et_arrondissement_nomme():
    """#426 (Lyon 2e) : « Maison 5 529 €/m² (n=3) » n'est pas une médiane, et
    le code 69382 est un arrondissement, pas une commune."""
    h = report._prices_html({"available": True, "commune_code": "69382", "sales": [],
                             "commune_eur_m2": {"Maison": {"n": 3, "median": 5529},
                                                "Appartement": {"n": 2176, "median": 5661}}})
    assert "Prix médian dans l'arrondissement" in h
    assert "Maison : 3 ventes seulement, pas de médiane représentative" in h
    assert "5 529" not in h and "5 529" not in h
    assert "5 661" in h or "5 661" in h


ESTIMATION = {"type_local": "Maison", "surface_m2": 143.3, "radius_m": 600, "n": 18,
              "from": "2023-12-07", "eur_m2": {"p25": 2301, "p50": 3006, "p75": 3270},
              "price": {"low": 330000, "mid": 431000, "high": 469000},
              "comparables": [{"date": "2025-01-30", "surface_m2": 144, "pieces": 6,
                               "valeur_fonciere": 450000, "eur_m2": 3125, "distance_m": 567}]}


def test_la_fourchette_observee_dans_le_pdf():
    h = report._prices_html({**PARCELLE}, estimation=ESTIMATION, classe="G")
    assert "Fourchette de prix observée" in h
    assert "330 000 € – 469 000 €" in h or "330 000 € – 469 000 €" in h
    assert "pas une estimation de valeur" in h and "classe énergétique (G)" in h
    assert "567 m" in h


def test_le_bloc_estimation_maison_ou_appartement(monkeypatch):
    vus = []

    async def dpe(bid):
        return {"surface_habitable_m2": 143.3}

    async def get(url, params, ttl=0):
        vus.append(params)
        return ESTIMATION
    monkeypatch.setattr(main, "DVF_ESTIMATION_URL", "http://dvf/rpc/estimation")
    monkeypatch.setattr(main, "_official_dpe", dpe)
    monkeypatch.setattr(main, "_cached_get_json", get)
    assert asyncio.run(main._estimation("b", 1.3382331, 43.607, {"nb_log": 1}))["n"] == 18
    assert vus[-1] == {"lon": 1.33823, "lat": 43.607, "type_local": "Maison", "surface": 143.3}
    asyncio.run(main._estimation("b", 1.3, 43.6, {"nb_log": 12}))
    assert vus[-1]["type_local"] == "Appartement"
    assert asyncio.run(main._estimation("b", 1.3, 43.6, {"nb_log": None})) is None
