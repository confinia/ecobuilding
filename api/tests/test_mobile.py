"""Échelle d'accès mobile (MOBILE.md §5.2), validée par l'opérateur le 2026-08-20 :

    10 fiches offertes par INSTALLATION, puis 0,99 € la fiche à l'unité
    (consommable), ou 4,99 €/mois pour 30 fiches, ou 12,99 €/mois pour 150.

Deux propriétés y sont moins évidentes qu'il n'y paraît, et ces tests les
verrouillent :

  - les fiches offertes se comptent **par installation et à vie**, pas par IP ni
    par mois. Par IP, des milliers d'abonnés d'un même opérateur mobile se
    partageraient les fiches offertes ; par mois, ce serait un robinet et non un essai.
  - le consommable **crédite un compteur** et ne confère aucun statut : une
    fiche achetée à l'unité survit à la fin d'un abonnement.
"""
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)
DEV = {"X-Install-Id": "install-0123456789abcdef"}
OTHER = {"X-Install-Id": "install-fedcba9876543210"}


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "USAGE_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(main, "CREDITS_PATH", str(tmp_path / "credits.json"))
    yield


def _gate(headers, endpoint="report"):
    """Appelle la porte de quota comme le ferait la route fiche."""
    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/v1/report/x.pdf",
             "headers": Headers(headers).raw, "query_string": b""}
    return main._quota_gate(Request(scope), endpoint)


def test_free_reports_then_the_wall():
    free = main.MOBILE_FREE_REPORTS
    assert free >= 10, "sous 10 essais, l'usage n'a pas le temps de s'installer"
    assert [_gate(DEV) for _ in range(free)] == ["mobile_free"] * free
    with pytest.raises(main.HTTPException) as e:
        _gate(DEV)
    assert e.value.status_code == 429
    # Le mur doit dire le prix, pas seulement refuser (auto-dépannage, #212).
    assert "0.99" in e.value.detail or "0,99" in e.value.detail
    assert "4.99" in e.value.detail or "4,99" in e.value.detail


def test_free_quota_is_per_installation_not_shared():
    """Sur réseau mobile, l'IP est partagée par des milliers d'abonnés : le
    compteur doit suivre l'installation, sinon les fiches offertes d'un
    utilisateur sont consommées par des inconnus."""
    for _ in range(main.MOBILE_FREE_REPORTS):
        _gate(DEV)
    assert _gate(OTHER) == "mobile_free", "une autre installation doit repartir à zéro"


def test_free_quota_is_lifetime_not_monthly(monkeypatch):
    """Les fiches offertes sont un ESSAI : le mois suivant ne les recharge pas."""
    for _ in range(main.MOBILE_FREE_REPORTS):
        _gate(DEV)
    monkeypatch.setattr(main, "_month_key", lambda: "2099-12")
    with pytest.raises(main.HTTPException):
        _gate(DEV)


def test_unit_purchase_is_consumed_one_by_one():
    for _ in range(main.MOBILE_FREE_REPORTS):
        _gate(DEV)
    bucket = main._device_bucket(type("R", (), {"headers": {"x-install-id": DEV["X-Install-Id"]}})())
    main._credits_add(bucket, units=2)
    assert _gate(DEV) == "mobile_unit"
    assert _gate(DEV) == "mobile_unit"
    with pytest.raises(main.HTTPException):
        _gate(DEV)                     # les 2 crédits sont épuisés


def test_subscription_quota_is_monthly_and_upsells(monkeypatch):
    bucket = main._device_bucket(type("R", (), {"headers": {"x-install-id": DEV["X-Install-Id"]}})())
    main._credits_add(bucket, tier="m30")
    assert _gate(DEV) == "mobile_sub"
    # Quota du palier atteint -> proposition du palier supérieur, pas un refus sec.
    monkeypatch.setattr(main, "_usage_load",
                        lambda: {main._month_key(): {bucket: 30 * main.CREDIT_COST["report"]}})
    with pytest.raises(main.HTTPException) as e:
        _gate(DEV)
    assert e.value.status_code == 429
    assert MOBILE_LABEL_150 in e.value.detail


MOBILE_LABEL_150 = "Terrain 150"


def test_units_survive_the_end_of_a_subscription():
    """Le consommable ne confère aucun statut : il ne doit pas disparaître avec
    l'abonnement qui l'a précédé."""
    bucket = main._device_bucket(type("R", (), {"headers": {"x-install-id": DEV["X-Install-Id"]}})())
    main._credits_add(bucket, units=1, tier="m30")
    main._credits_add(bucket, tier=None)          # fin d'abonnement
    ent = main._credits_get(bucket)
    assert ent["units"] == 1


def test_web_offers_do_not_show_mobile_prices():
    """Deux clientèles, deux promesses : les prix des magasins n'ont rien à
    faire dans les paliers web, et inversement."""
    cfg = client.get("/v1/config").json()
    assert set(cfg["pro_tiers"]) == {"s", "m", "l"}
    assert set(cfg["mobile"]["tiers"]) == {"m30", "m150"}
    assert cfg["mobile"]["unit_eur"] == 0.99
    assert cfg["mobile"]["free_reports"] == main.MOBILE_FREE_REPORTS
    assert cfg["mobile"]["tiers"]["m30"]["eur"] == 4.99
    assert cfg["mobile"]["tiers"]["m150"]["fiches_month"] == 150


def test_grid_is_internally_coherent():
    """La grille exposée aux apps doit rester cohérente avec les constantes.

    Elle était comparée à MOBILE.md, désormais dans le dépôt privé de
    monétisation : ce test doit passer sur un clone public, donc il compare les
    surfaces publiques entre elles."""
    cfg = client.get("/v1/config").json()["mobile"]
    assert cfg["free_reports"] == main.MOBILE_FREE_REPORTS
    assert cfg["unit_eur"] == main.MOBILE_UNIT_EUR
    for key, tier in main.MOBILE_TIERS.items():
        assert cfg["tiers"][key]["eur"] == tier["eur"]
        assert cfg["tiers"][key]["fiches_month"] == tier["fiches"]
        assert tier["fiches"] is None or tier["fiches"] > 0
    # Un palier plus cher doit donner PLUS de fiches, sinon la grille ment.
    paid = sorted(main.MOBILE_TIERS.values(), key=lambda t: t["eur"])
    assert all(a["fiches"] < b["fiches"] for a, b in zip(paid, paid[1:]))


def test_a_browser_call_is_unaffected():
    """Sans en-tête d'installation, rien ne change pour le web."""
    assert _gate({}, endpoint="lookup") == "anon"
