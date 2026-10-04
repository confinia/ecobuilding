"""Attente de la fiche PDF : pré-rendu (#507), progression (#506), rendus
mutualisés — sans réseau."""
import asyncio
import time

import app.main as main
from fastapi.testclient import TestClient

client = TestClient(main.app)
NAV = {"user-agent": "Mozilla/5.0 (iPhone) Safari/605.1"}


def _fiche_chargee(bid, lon, lat, schools=None):
    main._CACHE[f"building:{bid}:{round(lon, 4)}:{round(lat, 4)}:fr"] = (
        time.monotonic(), {"schools": schools or {"nearest": []}})


def test_pre_rendu_seulement_pour_une_fiche_chargee(monkeypatch):
    main._CACHE.clear()
    vus = []

    async def rendu3d(lon, lat, bid, bearing=-30.0):
        vus.append(("3d", bid))

    async def quartier(lon, lat, bid, schools):
        vus.append(("quartier", bid))
    monkeypatch.setattr(main, "RENDER_URL", "http://render/shot")
    monkeypatch.setattr(main, "_building_map_png", rendu3d)
    monkeypatch.setattr(main, "_quartier_map_png", quartier)
    url = "/v1/report/bdnb-bg-X/prepare?lon=1.3382&lat=43.6071"
    assert client.post(url, headers=NAV).json() == {"started": False, "reason": "fiche not loaded"}
    assert client.post(url, headers={"user-agent": "curl/8"}).json()["started"] is False
    _fiche_chargee("bdnb-bg-X", 1.3382, 43.6071)
    assert client.post(url, headers=NAV).json() == {"started": True}
    assert vus == [("3d", "bdnb-bg-X"), ("quartier", "bdnb-bg-X")]
    assert main._PREPARATION_EN_COURS["actif"] is False


def test_une_seule_preparation_a_la_fois(monkeypatch):
    main._CACHE.clear()
    monkeypatch.setattr(main, "RENDER_URL", "http://render/shot")
    _fiche_chargee("bdnb-bg-Y", 1.0, 43.0)
    monkeypatch.setitem(main._PREPARATION_EN_COURS, "actif", True)
    r = client.post("/v1/report/bdnb-bg-Y/prepare?lon=1.0&lat=43.0", headers=NAV)
    assert r.json() == {"started": False, "reason": "busy"}


def test_deux_demandes_du_meme_rendu_ne_font_qu_un_appel():
    appels = []

    async def faire():
        appels.append(1)
        await asyncio.sleep(0.05)
        return b"png"

    async def deux():
        return await asyncio.gather(main._rendu_mutualise("k", faire),
                                    main._rendu_mutualise("k", faire))
    assert asyncio.run(deux()) == [b"png", b"png"]
    assert appels == [1] and "k" not in main._RENDUS_EN_VOL


def test_la_progression_suit_les_etapes():
    main._PROGRESSION.clear()
    tok = main._SUIVI.set("abc123")
    try:
        with main._chrono("data"):
            pass
        with main._chrono("render_3d"):
            pass
        main._progression_note("done")
    finally:
        main._SUIVI.reset(tok)
    assert client.get("/v1/report/progress/abc123").json() == {"done": ["data", "render_3d", "done"]}
    assert client.get("/v1/report/progress/inconnu").json() == {"done": []}
