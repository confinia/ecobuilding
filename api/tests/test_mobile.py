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
    monkeypatch.setattr(main, "DAILY_PATH", str(tmp_path / "daily.json"))
    yield


def _gate(headers, endpoint="report", subject="bdnb-bg-A"):
    """Appelle la porte de quota comme le ferait la route fiche."""
    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/v1/report/x.pdf",
             "headers": Headers(headers).raw, "query_string": b""}
    return main._quota_gate(Request(scope), endpoint, subject=subject)


def test_daily_limit_counts_distinct_buildings():
    """La limite est quotidienne et porte sur des bâtiments DIFFÉRENTS."""
    n = main.MOBILE_DAILY_REPORTS
    assert n >= 10, "sous 10 par jour, l'usage de terrain n'a pas la place"
    for i in range(n):
        assert _gate(DEV, subject=f"bdnb-bg-{i}") == "mobile_free"
    with pytest.raises(main.HTTPException) as e:
        _gate(DEV, subject="bdnb-bg-TROP")
    assert e.value.status_code == 429
    # Le mur doit dire quand ça repart, sinon il ressemble à une panne.
    assert "demain" in e.value.detail


def test_same_building_again_is_free():
    """Redemander la MÊME fiche ne coûte rien : c'est le même document, et le
    refuser au motif d'un quota passerait pour une panne."""
    assert _gate(DEV, subject="bdnb-bg-X") == "mobile_free"
    for _ in range(50):
        assert _gate(DEV, subject="bdnb-bg-X") == "mobile_repeat"
    # Et cela n'a pas entamé le quota du jour.
    for i in range(main.MOBILE_DAILY_REPORTS - 1):
        assert _gate(DEV, subject=f"bdnb-bg-autre-{i}") == "mobile_free"


def test_free_quota_is_per_installation_not_shared():
    """Sur réseau mobile, l'IP est partagée par des milliers d'abonnés : le
    compteur doit suivre l'installation, sinon les fiches offertes d'un
    utilisateur sont consommées par des inconnus."""
    for i in range(main.MOBILE_DAILY_REPORTS):
        _gate(DEV, subject=f"b{i}")
    assert _gate(OTHER, subject="b0") == "mobile_free", \
        "une autre installation doit repartir à zéro"


def test_daily_limit_resets_the_next_day(monkeypatch):
    """« Par jour » doit vraiment repartir le lendemain."""
    import datetime
    for i in range(main.MOBILE_DAILY_REPORTS):
        _gate(DEV, subject=f"b{i}")
    with pytest.raises(main.HTTPException):
        _gate(DEV, subject="bZ")

    class Tomorrow(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date(2099, 12, 31)
    monkeypatch.setattr(main, "date", Tomorrow)
    assert _gate(DEV, subject="bZ") == "mobile_free"


def test_unit_purchase_is_consumed_one_by_one():
    for i in range(main.MOBILE_DAILY_REPORTS):
        _gate(DEV, subject=f"b{i}")
    bucket = main._device_bucket(type("R", (), {"headers": {"x-install-id": DEV["X-Install-Id"]}})())
    main._credits_add(bucket, units=2)
    assert _gate(DEV, subject="bX") == "mobile_unit"
    assert _gate(DEV, subject="bY") == "mobile_unit"
    with pytest.raises(main.HTTPException):
        _gate(DEV, subject="bZ")       # les 2 crédits sont épuisés


def test_subscription_quota_is_monthly_and_upsells(monkeypatch):
    bucket = main._device_bucket(type("R", (), {"headers": {"x-install-id": DEV["X-Install-Id"]}})())
    main._credits_add(bucket, tier="m30")
    assert _gate(DEV, subject="bA") == "mobile_sub"
    # Quota du palier atteint -> proposition du palier supérieur, pas un refus sec.
    monkeypatch.setattr(main, "_usage_load",
                        lambda: {main._month_key(): {bucket: 30 * main.CREDIT_COST["report"]}})
    with pytest.raises(main.HTTPException) as e:
        _gate(DEV, subject="bB")
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


def test_quota_preflight_knows_the_installation():
    """L'app mobile n'a ni clé ni session : sans cette reconnaissance, le
    pré-vol lui renvoyait le quota ANONYME par IP — un chiffre faux, et sur
    réseau mobile partagé avec des milliers d'inconnus."""
    r = client.get("/v1/quota", headers=DEV)
    assert r.status_code == 200
    q = r.json()
    assert q["plan"] == "mobile_free"
    assert q["reports_included"] == main.MOBILE_DAILY_REPORTS
    assert q["reports_left"] == main.MOBILE_DAILY_REPORTS
    assert q["period"] == "day"
    assert q["units"] == 0

    _gate(DEV, subject="bdnb-bg-Q")             # une fiche consommée
    q = client.get("/v1/quota", headers=DEV).json()
    assert q["reports_used"] == 1
    assert q["reports_left"] == main.MOBILE_DAILY_REPORTS - 1
    assert q["free_again"] == ["bdnb-bg-Q"], "on doit savoir ce qui est déjà obtenu"

    # Un abonnement bascule le décompte sur le quota MENSUEL du palier.
    bucket = main._device_bucket(type("R", (), {"headers": {"x-install-id": DEV["X-Install-Id"]}})())
    main._credits_add(bucket, units=3, tier="m30")
    q = client.get("/v1/quota", headers=DEV).json()
    assert q["plan"] == "mobile_sub" and q["tier"] == "m30"
    assert q["reports_included"] == main.MOBILE_TIERS["m30"]["fiches"]
    assert q["units"] == 3, "les fiches achetées à l'unité ne disparaissent pas"


def test_quota_preflight_unchanged_for_the_web():
    """Sans en-tête d'installation, le web garde exactement son comportement."""
    q = client.get("/v1/quota").json()
    assert q["plan"] == "anonymous"
    assert "units" not in q


def test_quota_says_when_it_reopens():
    """« Demain » ne dit rien à 23 h 50 : le serveur donne l'instant exact, et
    le client en tire une durée."""
    from datetime import datetime
    q = client.get("/v1/quota", headers=DEV).json()
    reset = datetime.fromisoformat(q["resets_at"])
    assert reset > datetime.now().astimezone(), "la réouverture doit être future"
    assert reset.hour == 0 and reset.minute == 0, "minuit, pas une heure arbitraire"
