"""Inondation après le retrait du zonage PPRN_ZONE_INOND (#510), sans réseau."""
import asyncio

import httpx

import app.main as main

SECHERESSE = {"lib_ppr": "PPR  Sécheresse - Territoire 2", "modelesProcedures": "PPRN-RGA",
              "codesAlea": "MVT", "libelle_sous_etat": "Approuvé", "dat_approbation": "22/12/2008"}
PPRI_PRESCRIT = {"lib_ppr": "PPRI révision", "modelesProcedures": "PPRN-I", "codesAlea": "INOND",
                 "libelle_sous_etat": "Prescrit", "dat_approbation": ""}
PPRI = {"lib_ppr": "PPRI_Lez_Mosson", "modelesProcedures": "PPRN-I", "codesAlea": "INOND",
        "libelle_sous_etat": "Approuvé", "dat_approbation": "13/01/2004", "id_gaspar": "34DDTM20040012"}


def _avec(monkeypatch, feats):
    vus = []

    async def get(url, params, ttl=0):
        vus.append(params)
        return {"features": [{"properties": p} for p in feats]}
    monkeypatch.setattr(main, "_cached_get_json", get)
    return vus


def test_seuls_les_ppr_inondation_comptent(monkeypatch):
    vus = _avec(monkeypatch, [SECHERESSE])
    assert asyncio.run(main._ppri_zone(1.338, 43.607)) is None
    assert vus[0]["LAYERS"] == "SUP_INOND"


def test_un_ppri_approuve_passe_avant_un_prescrit(monkeypatch):
    _avec(monkeypatch, [SECHERESSE, PPRI_PRESCRIT, PPRI])
    z = asyncio.run(main._ppri_zone(3.8925, 43.606))
    assert z["perimetre"] is True and z["couleur"] is None
    assert z["nom_ppr"] == "PPRI_Lez_Mosson" and z["date_approbation"] == "13/01/2004"
    assert z["code"] == "Périmètre PPRI"          # lu tel quel par les apps publiées


def test_une_exception_wms_compte_comme_une_panne(monkeypatch):
    comptes = []
    monkeypatch.setattr(main.M_UPSTREAM, "add", lambda n, attrs: comptes.append(attrs["outcome"]))

    class Faux(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, headers={"content-type": "application/vnd.ogc.se_xml"},
                                  content=b"<ServiceExceptionReport/>")

    async def go():
        async with httpx.AsyncClient(transport=main._TransportCompte(Faux())) as c:
            await c.get("https://www.georisques.gouv.fr/services")
    asyncio.run(go())
    assert comptes == ["error"]
