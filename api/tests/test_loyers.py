"""Loyers d'annonce par commune (#518), sur l'extrait committé."""
import asyncio

import app.main as main
from app import report


def test_loyers_de_colomiers_et_de_lyon_2e():
    r = asyncio.run(main._loyers("31149"))
    assert r["year"] == 2025
    assert r["app"] == {"eur_m2": 13.1, "low": 11.5, "high": 15.0, "level": "commune", "listings": 8504}
    assert set(r) >= {"app", "app12", "app3", "mai"}
    lyon = asyncio.run(main._loyers("69382"))             # arrondissement, comme la BDNB
    assert lyon["mai"]["level"] == "maille"
    assert asyncio.run(main._loyers("00000")) is None


def test_le_pdf_donne_les_loyers_et_le_rendement_brut_d_une_maison():
    r = asyncio.run(main._loyers("31149"))
    e = {"type_local": "Maison", "surface_m2": 143.3, "price": {"mid": 431000}}
    h = report._loyers_html(r, e)
    assert "13,1 €/m² (11,5 – 15,0)" in h
    assert "Rendement brut indicatif (maison) : 4,8 %" in h          # 12,1 × 143,3 × 12 / 431 000
    assert "Rendement brut" not in report._loyers_html(r, None)
