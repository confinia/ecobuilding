"""Risques : repli sur le registre communal GASPAR (#493), sans réseau."""
import asyncio

import httpx

import app.main as main
from app import report

GASPAR = {"data": [{"libelle_commune": "COLOMIERS", "risques_detail": [
    {"num_risque": "11", "libelle_risque_long": "Inondation"},
    {"num_risque": "112", "libelle_risque_long": "Par une crue à débordement lent de cours d'eau"},
    {"num_risque": "21", "libelle_risque_long": "Risque industriel"}]}]}


def _sources(monkeypatch, gaspar_ok=True):
    async def get(url, params, ttl=0):
        if url == main.GEORISQUES_URL:
            raise httpx.RemoteProtocolError("Server disconnected")     # blocage observé
        if url == main.GASPAR_RISQUES_URL and gaspar_ok:
            return GASPAR
        raise httpx.ConnectError("down")
    monkeypatch.setattr(main, "_cached_get_json", get)


def test_repli_communal_sans_affirmation_sur_la_parcelle(monkeypatch):
    _sources(monkeypatch)

    async def go():
        echecs = main._suivre_echecs()
        return await main._area_risks(1.338, 43.607, "31149"), echecs
    r, echecs = asyncio.run(go())
    assert r["scope"] == "commune" and r["commune"] == "Colomiers"
    assert r["risques_naturels"] == [] and r["risques_technologiques"] == []   # apps publiées : rien de faux
    assert r["commune_risques_naturels"] == ["Inondation"]                       # premier niveau seulement
    assert r["commune_risques_technologiques"] == ["Risque industriel"]
    assert echecs == set()                                                      # repli réussi : fiche gardée


def test_les_deux_sources_en_panne_comptent_comme_un_echec(monkeypatch):
    _sources(monkeypatch, gaspar_ok=False)

    async def go():
        echecs = main._suivre_echecs()
        return await main._area_risks(1.338, 43.607, "31149"), echecs
    r, echecs = asyncio.run(go())
    assert r is None and echecs == {"area_risks"}


def test_le_rapport_utilise_www():
    assert main.GEORISQUES_URL.startswith("https://www.georisques.gouv.fr/")
