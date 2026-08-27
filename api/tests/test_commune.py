"""Bloc commune (#275) — Confinia.

`INTEGRATION.md` pose une règle : « un consommateur qui reprend nos chiffres
sans nos réserves affirme PLUS que nous ». Trois champs matérialisent cette
règle, et ces tests les verrouillent :

- `declined` distingue « Confinia ne calcule jamais ce fait » de « ce fait n'a
  pas pu être établi ICI ». Sans lui, une absence de rang se lit comme une
  absence de méthode ;
- `limitations` borne ce que les faits soutiennent ;
- `attribution` crédite : la donnée est ouverte, pas anonyme.

Et une exigence à nous : la fiche ne doit JAMAIS dépendre d'un tiers. Clé
absente ou API muette, le bloc disparaît, le reste est servi.
"""
import pytest

import app.main as main

FAITS = {
    "unit": {"code": "31471", "name": "Saint-Béat-Lez", "country": "FR",
             "valid_from": "2019-01-01", "valid_to": None},
    "as_known_on": "2026-01-01",
    "summary": ["Elle est née le 2019-01-01 de la fusion de 2 communes."],
    "versions": [
        {"name": "Saint-Béat", "valid_from": "1870-01-01", "valid_to": "1943-01-01"},
        {"name": "Saint-Béat", "valid_from": "1943-01-01", "valid_to": "2019-01-01"},
        {"name": "Saint-Béat-Lez", "valid_from": "2019-01-01", "valid_to": None},
    ],
    "declined": [{"reason": "rank:not-comparable",
                  "text": "rang : cette version n'existe plus"}],
    "limitations": ["Notre image s'arrête au 2026-01-01."],
    "attribution": [{"attribution": "INSEE, Code officiel géographique",
                     "license": "Licence Ouverte 2.0"}],
}


# Le lieu tel qu'il était la VEILLE du changement — c'est ce que l'API rend
# quand on l'interroge par point et par date.
AVANT = {"type": "Feature",
         "properties": {"code": "31298", "nom": "Lez", "valid_to": "2019-01-01"}}


@pytest.fixture
def confinia(monkeypatch):
    monkeypatch.setattr(main, "CONFINIA_API_KEY", "clé-de-test")
    vus = []

    async def faux(url, params, ttl=0, headers=None):
        vus.append((url, params))
        if "/facts" in url:
            assert headers and headers.get("X-API-Key"), \
                "la clé doit voyager en en-tête"
            return FAITS
        # Le lookup par point ne demande PAS de clé : on vérifie qu'on n'en
        # dépense pas une pour rien.
        assert not headers, "le lookup par point ne consomme pas la clé"
        assert params["at"] == "2018-12-31", \
            f"on doit interroger la veille du changement, pas {params['at']}"
        return AVANT

    monkeypatch.setattr(main, "_cached_get_json", faux)
    return vus


async def _bloc(commune="31471", lon=0.70517, lat=42.90902):
    return await main._commune_history(commune, lon, lat)


@pytest.mark.anyio
async def test_le_nom_d_avant_est_nomme_avec_sa_date(confinia):
    b = await _bloc()
    assert b["nom"] == "Saint-Béat-Lez"
    assert b["code"] == "31471"
    # « Lez », pas « Saint-Béat » : le code 31471 s'appelait bien Saint-Béat,
    # mais un bâtiment qui était à Lez n'a jamais été à Saint-Béat. Seul le
    # POINT tranche, et c'est lui qu'on interroge.
    assert b["precedent"]["nom"] == "Lez"
    assert b["precedent"]["code"] == "31298"
    # La date vient du CHAMP, pas de la phrase : on l'écrit dans notre forme.
    assert b["precedent"]["jusqu_au_fr"] == "1ᵉʳ janvier 2019"


@pytest.mark.anyio
async def test_les_trois_champs_interdits_de_perte_sont_la(confinia):
    b = await _bloc()
    assert b["non_etablis"][0]["raison"] == "rank:not-comparable", \
        "sans la raison, on ne distingue pas « jamais calculé » de « pas établi ici »"
    assert b["limites"], "les limites bornent ce que les faits soutiennent"
    assert b["attribution"][0]["attribution"] == "INSEE, Code officiel géographique"


@pytest.mark.anyio
async def test_une_date_iso_egaree_dans_une_phrase_se_lit_quand_meme(confinia):
    """Filet. Confinia a corrigé sa prose le 2026-08-26 : ses phrases n'ont
    plus de dates ISO, dans aucune des deux langues. Ce test garde le
    comportement au cas où l'une réapparaîtrait — ces phrases finissent dans
    une fiche remise à un acheteur."""
    b = await _bloc()
    limite = b["limites"][0]
    assert "2026-01-01" not in limite, "une date ISO dans une phrase française"
    assert "1ᵉʳ janvier 2026" in limite
    # Reformuler, jamais amputer : la phrase garde tout son sens.
    assert limite.startswith("Notre image s'arrête au ")


@pytest.mark.anyio
async def test_sans_cle_le_bloc_disparait_et_rien_ne_casse(monkeypatch):
    monkeypatch.setattr(main, "CONFINIA_API_KEY", "")
    assert await _bloc() is None


@pytest.mark.anyio
async def test_api_muette_le_bloc_disparait(monkeypatch):
    monkeypatch.setattr(main, "CONFINIA_API_KEY", "clé-de-test")

    async def tombe(url, params, ttl=0, headers=None):
        raise RuntimeError("Confinia injoignable")

    monkeypatch.setattr(main, "_cached_get_json", tombe)
    assert await _bloc() is None, "la fiche ne doit jamais dépendre d'un tiers"


def test_le_credit_ne_double_pas_une_source_deja_citee():
    hist = {"attribution": [{"attribution": "INSEE, Code officiel géographique",
                             "license": "Licence Ouverte 2.0"}]}
    deja = ["INSEE, Code officiel géographique — Licence Ouverte 2.0"]
    assert main._credits_confinia(hist, deja) == []
    assert main._credits_confinia(hist, []) == \
        ["INSEE, Code officiel géographique — Licence Ouverte 2.0"]


def test_une_date_du_premier_du_mois_prend_l_ordinal():
    assert main._date_fr("2019-01-01") == "1ᵉʳ janvier 2019"
    assert main._date_fr("2019-03-14") == "14 mars 2019"
    assert main._date_fr("pas une date") == "pas une date"
    assert main._date_fr(None) is None


@pytest.mark.anyio
async def test_sans_coordonnees_aucun_nom_d_avant_n_est_affirme(confinia):
    """Mieux vaut se taire que nommer le prédécesseur du CODE : il peut n'avoir
    jamais contenu ce bâtiment."""
    b = await main._commune_history("31471", None, None)
    assert b["nom"] == "Saint-Béat-Lez"
    assert b["precedent"] is None


@pytest.mark.anyio
async def test_le_lookup_par_point_qui_echoue_ne_perd_pas_le_bloc(monkeypatch):
    monkeypatch.setattr(main, "CONFINIA_API_KEY", "clé-de-test")

    async def faux(url, params, ttl=0, headers=None):
        if "/facts" in url:
            return FAITS
        raise RuntimeError("lookup par point indisponible")

    monkeypatch.setattr(main, "_cached_get_json", faux)
    b = await main._commune_history("31471", 0.70517, 42.90902)
    assert b is not None, "la commune reste connue même sans son nom d'avant"
    assert b["precedent"] is None


# --- Éventail des DPE (#287) -------------------------------------------------
#
# « Tu raisonnes en DPE par bâtiment. Mais il arrive que les apparts d'une même
# résidence aient des DPE différents. » Mesuré sur 1 000 diagnostics : dès
# qu'une adresse en porte plusieurs, deux fois sur trois les classes diffèrent.

def test_l_eventail_se_lit_de_A_vers_G_et_non_par_ordre_alphabetique():
    import app.main as main

    assert main._classe_min_max(["G", "C", "E"]) == ("C", "G")
    assert main._classe_min_max(["D"]) == ("D", "D")
    assert main._classe_min_max([]) == (None, None)
    assert main._classe_min_max(["?", "X"]) == (None, None)


@pytest.mark.anyio
async def test_un_seul_diagnostic_ne_produit_aucun_bloc(monkeypatch):
    """La fiche a déjà raison dans ce cas : elle ne doit pas changer."""
    import app.main as main

    async def faux(url, params, ttl=0, headers=None):
        if "rel_batiment" in url:
            return [{"cle_interop_adr": "34172_0001_00001"}]
        return {"results": [{"etiquette_dpe": "D", "surface_habitable_logement": 50}]}

    monkeypatch.setattr(main, "_cached_get_json", faux)
    assert await main._dpe_spread("bdnb-bg-X", None, None) is None


@pytest.mark.anyio
async def test_plusieurs_classes_donnent_l_eventail_et_sa_repartition(monkeypatch):
    import app.main as main

    async def faux(url, params, ttl=0, headers=None):
        if "rel_batiment" in url:
            return [{"cle_interop_adr": "34172_4725_00002_bis"}]
        return {"results": [
            {"etiquette_dpe": "C", "surface_habitable_logement": 77,
             "numero_etage_appartement": 0},
            {"etiquette_dpe": "G", "surface_habitable_logement": 31.7},
            {"etiquette_dpe": "C", "surface_habitable_logement": 58.9},
        ]}

    monkeypatch.setattr(main, "_cached_get_json", faux)
    r = await main._dpe_spread("bdnb-bg-X", None, None)
    assert r["diagnostics"] == 3
    assert (r["classe_min"], r["classe_max"]) == ("C", "G")
    assert r["identiques"] is False
    assert r["repartition"] == {"C": 2, "G": 1}
    # Trié par surface décroissante : c'est le critère qu'un acheteur reconnaît,
    # pas l'étage, renseigné dans 17 % des cas seulement.
    assert [x["surface_m2"] for x in r["logements"]] == [77, 58.9, 31.7]


@pytest.mark.anyio
async def test_l_ademe_muette_ne_casse_pas_la_fiche(monkeypatch):
    import app.main as main

    async def faux(url, params, ttl=0, headers=None):
        if "rel_batiment" in url:
            return [{"cle_interop_adr": "x"}]
        raise RuntimeError("ADEME injoignable")

    monkeypatch.setattr(main, "_cached_get_json", faux)
    assert await main._dpe_spread("bdnb-bg-X", None, None) is None


@pytest.mark.anyio
async def test_le_point_prime_sur_le_code_de_la_bdnb(monkeypatch):
    """Paris, Lyon et Marseille : la BDNB donne le code de l'ARRONDISSEMENT, et
    Confinia tient les arrondissements pour des unités historiques.

    Interroger `75101` rendait « Paris-01, 1870 → 1941 » : une commune
    présentée comme disparue sous un immeuble bien vivant. Le point, lui, rend
    Paris (75056). `INTEGRATION.md` le dit sans ambiguïté — « pass the
    coordinates »."""
    import app.main as main

    monkeypatch.setattr(main, "CONFINIA_API_KEY", "clé")
    vus = []

    async def faux(url, params, ttl=0, headers=None):
        vus.append(url)
        if url.endswith("/communes"):                    # résolution par point
            return {"type": "Feature",
                    "properties": {"code": "75056", "nom": "Paris"}}
        if "/facts" in url:
            assert "/75056/" in url, f"le code de l'arrondissement a été utilisé : {url}"
            return {"unit": {"code": "75056", "name": "Paris",
                             "valid_from": "1943-01-01", "valid_to": None},
                    "as_known_on": "2026-01-01", "versions": [],
                    "declined": [], "limitations": [], "attribution": []}
        return {}

    monkeypatch.setattr(main, "_cached_get_json", faux)
    r = await main._commune_history("75101", 2.33, 48.866)
    assert r["code"] == "75056" and r["nom"] == "Paris"
    assert r["existe_encore"] is True


@pytest.mark.anyio
async def test_une_commune_eteinte_montre_sa_date_de_FIN(monkeypatch):
    """La fiche annonçait « a cessé d'exister le 1ᵉʳ janvier 1870 » en
    affichant le commencement de la version."""
    import app.main as main

    monkeypatch.setattr(main, "CONFINIA_API_KEY", "clé")

    async def faux(url, params, ttl=0, headers=None):
        if url.endswith("/communes"):
            return {}
        return {"unit": {"code": "31298", "name": "Lez",
                         "valid_from": "1943-01-01", "valid_to": "2019-01-01"},
                "as_known_on": "2026-01-01", "versions": [],
                "declined": [], "limitations": [], "attribution": []}

    monkeypatch.setattr(main, "_cached_get_json", faux)
    r = await main._commune_history("31298", None, None)
    assert r["existe_encore"] is False
    assert r["jusqu_au_fr"] == "1ᵉʳ janvier 2019"        # la fin
    assert r["depuis_fr"] == "1ᵉʳ janvier 1943"          # le début, distinct


@pytest.mark.anyio
async def test_sans_coordonnees_on_les_tire_de_l_emprise(monkeypatch):
    """Une fiche ouverte par identifiant seul — un lien partagé — n'a pas de
    position. Sans elle, le code de la BDNB reprenait la main et Paris
    redevenait « éteinte ». L'emprise du bâtiment donne le point."""
    import app.main as main

    monkeypatch.setattr(main, "CONFINIA_API_KEY", "clé")
    demande = {}

    async def anneau(bid):
        return [(2.3250, 48.8660), (2.3258, 48.8660), (2.3258, 48.8670)]

    async def faux(url, params, ttl=0, headers=None):
        if url.endswith("/communes"):
            demande.update(params)
            return {"properties": {"code": "75056", "nom": "Paris"}}
        return {"unit": {"code": "75056", "name": "Paris",
                         "valid_from": "1943-01-01", "valid_to": None},
                "as_known_on": "2026-01-01", "versions": [],
                "declined": [], "limitations": [], "attribution": []}

    monkeypatch.setattr(main, "_building_ring", anneau)
    monkeypatch.setattr(main, "_cached_get_json", faux)
    r = await main._commune_history("75101", None, None, bdnb_id="bdnb-bg-X")
    assert r["code"] == "75056"
    # Le point interrogé est bien le centre de l'emprise.
    assert abs(demande["lon"] - 2.32553) < 1e-4
    assert abs(demande["lat"] - 48.86633) < 1e-4
