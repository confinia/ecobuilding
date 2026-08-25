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
async def test_les_dates_iso_sont_reformulees_pas_supprimees(confinia):
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
