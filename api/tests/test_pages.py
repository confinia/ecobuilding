"""Pages indexables d'un bâtiment (#495), sans réseau."""
import app.main as main
from fastapi.testclient import TestClient

client = TestClient(main.app)

ROW = {"batiment_groupe_id": "bdnb-bg-M5W1-T6DV-GUBP", "code_commune_insee": "31149",
       "libelle_adr_principale_ban": "13 Rue François Larrieu 31770 Colomiers",
       "annee_construction": 1977, "nb_log": 1, "classe_bilan_dpe": "G",
       "date_reception_dpe": "2021-11-14", "usage_principal_bdnb_open": "Résidentiel individuel"}


def _sources(monkeypatch, row=ROW):
    main._CACHE.clear()

    async def fake_get(url, params, ttl=0):
        if "geo.api.gouv.fr" in url:
            return [{"code": "31149"}, {"code": "31555"}]
        if url == main.BDNB_DPE_COMMUNE_URL:
            return [{"batiment_groupe_id": "bdnb-bg-M5W1-T6DV-GUBP"}, {"batiment_groupe_id": "<script>"}]
        return [row] if row else []

    async def fake_point(_):
        return (1.338233, 43.607086)

    async def prix(_):
        return {"commune_eur_m2": {"Maison": {"n": 982, "median": 3150}},
                "sales": [{"date": "2024-12-20", "type_local": "Maison", "surface_m2": 137,
                           "valeur_fonciere": 420000, "eur_m2": 3066}]}

    async def taxes(_):
        return {"property_tax_mean_eur": 2970, "rei_year": 2025}

    async def dpe(_):
        return {"dpe_number": "2131E0682889E", "annual_cost_eur": 6372}

    async def plu(lon, lat):
        raise RuntimeError("GPU en panne")      # une source KO retire sa ligne, pas la page

    vues = []
    monkeypatch.setattr(main, "_cached_get_json", fake_get)
    monkeypatch.setattr(main, "_building_point", fake_point)
    monkeypatch.setattr(main, "_dvf_prices", prix)
    monkeypatch.setattr(main, "_local_taxes", taxes)
    monkeypatch.setattr(main, "_official_dpe", dpe)
    monkeypatch.setattr(main, "_plu_zone", plu)
    monkeypatch.setattr(main, "_noter_la_vue", lambda *a, **k: vues.append(a))
    return vues


def test_page_porte_les_faits_et_l_url_canonique(monkeypatch):
    vues = _sources(monkeypatch)
    r = client.get("/batiment/bdnb-bg-M5W1-T6DV-GUBP", headers={"host": "ecobuilding.confinia.io"})
    assert r.status_code == 200
    h = r.text
    assert "<title>DPE G — 13 Rue François Larrieu, Colomiers | EcoBuilding</title>" in h
    assert '<link rel="canonical" href="https://ecobuilding.confinia.io/batiment/bdnb-bg-M5W1-T6DV-GUBP">' in h
    assert 'content="index,follow"' in h
    assert "Location interdite à partir du 1ᵉʳ janvier 2025" in h
    assert "3 150 €/m²" in h and "6 372 €" in h and "2 970 €" in h
    assert "Zone d'urbanisme" not in h                      # source en panne : ligne absente
    assert "/?b=bdnb-bg-M5W1-T6DV-GUBP#18/43.607086/1.338233" in h
    assert "pas le diagnostic de performance énergétique officiel" in h   # #418
    assert len(vues) == 1


def test_hors_production_la_page_ne_s_indexe_pas(monkeypatch):
    _sources(monkeypatch)
    r = client.get("/batiment/bdnb-bg-M5W1-T6DV-GUBP", headers={"host": "sandbox.ecobuilding.confinia.io"})
    assert 'content="noindex,nofollow"' in r.text


def test_identifiant_invalide_ou_inconnu(monkeypatch):
    _sources(monkeypatch, row=None)
    assert client.get("/batiment/pas-un-id").status_code == 404
    assert client.get("/batiment/bdnb-bg-AAAA-BBBB-CCCC").status_code == 404


def test_plans_du_site(monkeypatch):
    _sources(monkeypatch)
    idx = client.get("/batiment/sitemap.xml").text
    assert "<loc>https://ecobuilding.confinia.io/batiment/sitemap-31555.xml</loc>" in idx
    plan = client.get("/batiment/sitemap-31149.xml").text
    assert "<loc>https://ecobuilding.confinia.io/batiment/bdnb-bg-M5W1-T6DV-GUBP</loc>" in plan
    assert "<script>" not in plan                           # rien d'inattendu ne passe
    assert client.get("/batiment/sitemap-xx.xml").status_code == 404


def test_plan_de_commune_indisponible_repond_503(monkeypatch):
    _sources(monkeypatch)

    async def panne(url, params, ttl=0):
        raise RuntimeError("vue absente")
    monkeypatch.setattr(main, "_cached_get_json", panne)
    r = client.get("/batiment/sitemap-31149.xml")
    assert r.status_code == 503 and r.headers["retry-after"] == "3600"
