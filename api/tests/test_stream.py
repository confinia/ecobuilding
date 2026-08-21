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


def test_subscriber_hitting_quota_is_offered_an_upgrade_not_a_signup():
    """Vécu sur sandbox : quota Pro S épuisé -> le panneau annonçait « votre
    compte gratuit » à un abonné et proposait « Passer Pro » ; le clic sur un
    palier supérieur appelait /pro/checkout, que l'API refuse en 409 (un second
    abonnement s'additionnerait), et le front affichait « momentanément
    indisponible ». Impasse complète pour un client qui paie."""
    import pathlib
    app_js = (pathlib.Path(__file__).resolve().parents[2] / "frontend/site/app.js").read_text()
    # 409 sur le checkout -> changement d'offre, pas message d'erreur.
    assert "r.status === 409" in app_js
    assert "/api/v1/pro/upgrade?tier=" in app_js
    # Le panneau de quota distingue l'abonné du compte gratuit.
    assert "Quota de votre offre atteint" in app_js
    assert "NEXT_TIER" in app_js


def test_auth_base_is_absolute_not_relative():
    """Keycloak est partagé par blue/green avec un KC_HOSTNAME figé sur le
    domaine de production. Appeler « /auth » en relatif depuis staging posait le
    cookie de session sur le domaine staging puis postait le formulaire vers
    prod : « Cookie introuvable », connexion impossible sur staging (jamais vu
    par l'e2e, qui tourne sur le sandbox et son Keycloak dédié)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    app_js = (root / "frontend/site/app.js").read_text()
    env_js = (root / "frontend/site/env.js").read_text()
    sbx_js = (root / "sandbox_stack/env.sandbox.js").read_text()

    assert 'url: "/auth"' not in app_js, "l'adaptateur doit utiliser la base absolue"
    assert "authBase" in app_js
    assert '`/auth/realms/' not in app_js, "le repli direct doit aussi être absolu"
    # Chaque environnement déclare l'hôte de SON Keycloak.
    assert 'window.ECO_AUTH_URL = "https://ecobuilding.confinia.io/auth"' in env_js
    assert 'window.ECO_AUTH_URL = "https://sandbox.ecobuilding.confinia.io/auth"' in sbx_js


def test_privacy_policy_is_published_and_accurate():
    """Apple exige une URL de politique de confidentialité dès TestFlight, et
    ce texte engage : il doit décrire ce que le code fait RÉELLEMENT."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    page = (root / "frontend/site/confidentialite.html").read_text()
    api = (root / "api/app/main.py").read_text()
    app_swift = (root / "mobile/ios/EcoBuilding/Sources/API.swift").read_text()

    # La page est bien reliée depuis la carte, sinon personne ne la trouve.
    assert "/confidentialite.html" in (root / "frontend/site/index.html").read_text()
    # Promesses vérifiables dans le code :
    assert "ne quitte pas votre téléphone" in page
    assert "X-Install-Id" in app_swift        # seul identifiant transmis
    assert "events" not in app_swift.split("MARK: - Offre")[0].replace("StreamEvent", "")
    assert "never stored nor logged" in api            # cf. bloc GeoIP
