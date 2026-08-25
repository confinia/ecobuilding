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
                 "_dvf_prices", "_rnb_lookup", "_click_address",
                 "_commune_history"):
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
                          "schools", "rnb", "commune"}


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

    # La page est bien reliée depuis la carte, sinon personne ne la trouve.
    assert "/confidentialite.html" in (root / "frontend/site/index.html").read_text()
    # Promesses vérifiables ICI, côté serveur. Le code des apps vit dans un
    # dépôt privé : ce test doit passer sur un clone public, et de toute façon
    # ce qui engage la politique, c'est ce que le serveur reçoit et conserve.
    assert "ne quitte pas votre téléphone" in page
    assert main.DEVICE_HEADER == "x-install-id"   # seul identifiant transmis
    assert "never stored nor logged" in api       # cf. bloc GeoIP


def test_photos_merge_panoramax_then_commons(monkeypatch):
    """#200 : Panoramax couvre bien les villes et mal le reste ; sur beaucoup
    d'adresses la fiche n'affichait AUCUNE image, alors qu'un acheteur veut
    d'abord voir l'environnement du bien. Commons complète, sans clé.

    L'ordre compte : la vue au sol d'abord — ce qu'on verrait en arrivant —
    puis le contexte. Et chaque image porte sa licence : l'attribution est une
    obligation des licences CC-BY-SA, pas une politesse."""
    async def fake(url, params, ttl=0):
        if "panoramax" in url:
            return {"features": [{"id": "pano-1", "assets": {"thumb": {"href": "http://t/1.jpg"}},
                                  "geometry": {"coordinates": [3.0, 43.0]}, "properties": {}}]}
        return {"query": {"pages": {"42": {
            "pageid": 42, "title": "File:Mairie.jpg",
            "imageinfo": [{"thumburl": "http://c/m.jpg", "url": "http://c/full.jpg",
                           "descriptionurl": "http://commons/x",
                           "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                           "Artist": {"value": "<a href='#'>Jean</a>"}}}]}}}}
    monkeypatch.setattr(main, "_cached_get_json", fake)
    r = client.get("/v1/streetview?lon=3.0&lat=43.0").json()
    photos = r["photos"]
    assert len(photos) == 2
    assert photos[0]["source"] == "Panoramax", "la vue au sol vient en premier"
    assert photos[1]["source"] == "Wikimedia Commons"
    assert photos[1]["licence"] == "CC BY-SA 4.0"
    assert photos[1]["author"] == "Jean", "le HTML de l'auteur doit être nettoyé"


def test_commons_failure_never_breaks_the_photos(monkeypatch):
    """Une source tierce en panne ne doit pas priver l'utilisateur des autres."""
    async def fake(url, params, ttl=0):
        if "commons" in url:
            raise RuntimeError("commons down")
        return {"features": []}
    monkeypatch.setattr(main, "_cached_get_json", fake)
    assert client.get("/v1/streetview?lon=3.0&lat=43.0").json()["photos"] == []


def test_aerial_view_reaches_the_pdf(monkeypatch):
    """#200 : le rendu 3D dit la classe énergétique, la photo aérienne dit ce
    qu'on achète — terrain, arbres, annexes, accès. Elle doit atteindre la
    fiche, et son absence ne doit jamais empêcher de la produire."""
    from app.report import _report_html
    data = {"query": {"address": "1 rue de Test", "lon": 1.44, "lat": 43.61},
            "buildings": [{"bdnb_id": "b", "energy": {}}], "sources": []}
    html = _report_html(data, photos=[], map_img=None,
                        aerial_img="data:image/jpeg;base64,AAAA")
    assert "Vue aérienne" in html and "data:image/jpeg;base64,AAAA" in html
    assert "IGN" in html and "Licence Ouverte" in html      # attribution due
    # Sans photo aérienne, la fiche se produit quand même.
    assert "Vue aérienne" not in _report_html(data, photos=[], map_img=None)


# --- Adresse sans bâtiment : dire pourquoi, et servir ce qu'on a --------------
#
# Le panneau affichait « le bâtiment existe peut-être sous une adresse voisine »
# dans TOUS les cas, y compris outre-mer où c'est faux — la BDNB s'arrête à la
# métropole. Et le flux n'émettait aucun bloc : les applications mobiles, qui
# n'affichent que des blocs, restaient sur un écran vide alors que les risques
# de la zone étaient déjà arrivés.

@pytest.fixture
def sans_batiment(monkeypatch):
    """BDNB muette. `ban` fixe la commune, donc le motif attendu."""
    etat = {"ban": "97411_1060", "label": "Rue de Paris 97400 Saint-Denis",
            "point": [55.449705, -20.882172]}

    async def fake_get(url, params, ttl=0):
        if "adresse.data.gouv" in url:
            return {"features": [{"properties": {"id": etat["ban"],
                                                 "label": etat["label"]},
                                  "geometry": {"coordinates": etat["point"]}}]}
        return []                       # aucun bâtiment à cette adresse

    monkeypatch.setattr(main, "_cached_get_json", fake_get)

    async def risques(*a, **k):
        return {"commune": "Saint-Denis", "risques_naturels": ["cyclone"],
                "risques_technologiques": []}
    monkeypatch.setattr(main, "_area_risks", risques)
    for name in ("_groundwater", "_solar_pv", "_water_network", "_official_dpe",
                 "_local_taxes", "_nearby_schools", "_dvf_prices", "_rnb_lookup",
                 "_click_address"):
        async def none(*a, **k):
            return None
        monkeypatch.setattr(main, name, none)
    return etat


def test_outre_mer_dit_la_vraie_raison(sans_batiment):
    evs = _events("/v1/lookup/stream?q=rue+de+Paris+Saint-Denis")
    motif = evs[0]["no_building"]
    assert motif["reason"] == "outre_mer"
    # Ne JAMAIS inviter à chercher une adresse voisine là où il n'y en aura pas.
    assert "voisine" not in motif["text"]
    assert "métropole" in motif["text"]


def test_metropole_garde_la_piste_de_l_adresse_voisine(sans_batiment):
    sans_batiment["ban"] = "31557_2400_00012"
    sans_batiment["label"] = "12 Rue de la Licorne 31170 Tournefeuille"
    sans_batiment["point"] = [1.345887, 43.583127]
    evs = _events("/v1/lookup/stream?q=12+rue+de+la+Licorne")
    motif = evs[0]["no_building"]
    assert motif["reason"] == "absent_bdnb"
    assert "voisine" in motif["text"], "en métropole, la piste reste valable"


def test_le_contexte_part_en_blocs_meme_sans_batiment(sans_batiment):
    evs = _events("/v1/lookup/stream?q=rue+de+Paris+Saint-Denis")
    blocs = {e["name"]: e["value"] for e in evs if e["type"] == "block"}
    assert "area_risks" in blocs, "sans bloc, le mobile reste sur un écran vide"
    assert blocs["area_risks"]["risques_naturels"] == ["cyclone"]
    assert evs[-1]["type"] == "done"


def test_la_commune_vient_de_la_ban_quand_aucun_batiment_ne_la_porte(
        sans_batiment, monkeypatch):
    """Sans bâtiment, `code_commune_insee` n'existe pas : la fiscalité locale et
    le réseau d'eau étaient donc interrogés avec None, et vides sans raison."""
    vues = []

    async def taxes(commune):
        vues.append(commune)
        return None

    monkeypatch.setattr(main, "_local_taxes", taxes)
    _events("/v1/lookup/stream?q=rue+de+Paris+Saint-Denis")
    assert vues == ["97411"], f"commune transmise : {vues}"
