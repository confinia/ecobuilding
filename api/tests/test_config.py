"""Config-as-code assertions (#128): the email/alerting setup must live entirely
in versioned files — compose env, Grafana provisioning, kcadm script. These
tests pin the wiring so a UI-only or hand-edited config can't silently replace
it. They need the repo root (deploy/test.sh mounts it; skipped otherwise)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
needs_repo = pytest.mark.skipif(
    not (ROOT / "monitoring_stack").is_dir(),
    reason="repo root not available (api-only checkout)",
)


@needs_repo
def test_grafana_smtp_is_code():
    compose = (ROOT / "monitoring_stack/docker-compose.yml").read_text()
    for key in ("GF_SMTP_ENABLED", "GF_SMTP_HOST", "GF_SMTP_USER",
                "GF_SMTP_PASSWORD", "GF_SMTP_FROM_ADDRESS"):
        assert key in compose, f"{key} missing from monitoring compose"
    # Secrets stay in secrets.env: compose only substitutes, never hardcodes.
    assert "${SMTP_PASSWORD" in compose


@needs_repo
def test_grafana_alerting_provisioned_as_code():
    y = (ROOT / "monitoring/grafana-shared/provisioning/alerting/ops-email.yaml").read_text()
    assert "contactPoints:" in y and "type: email" in y
    assert "contact@confinia.io" in y          # ops recipient (redirect-managed)
    assert "policies:" in y and "receiver: ops-email" in y
    assert "datasourceUid: prometheus" in y    # rule pinned to the stable uid
    ds = (ROOT / "monitoring/grafana-shared/provisioning/datasources/prometheus.yaml").read_text()
    assert "uid: prometheus" in ds


@needs_repo
def test_keycloak_email_is_code():
    """Keycloak email as code, two versioned layers: realm-confinia.json is the
    SAFE bootstrap (SMTP sans password, verifyEmail off — a fresh import can
    never strand registrations), kc-smtp.sh is the reconciler that injects the
    secret and flips verifyEmail once the relay accepts the creds."""
    import json
    realm = json.loads((ROOT / "auth_stack/realm-confinia.json").read_text())
    smtp = realm.get("smtpServer") or {}
    assert smtp.get("host") == "ssl0.ovh.net" and smtp.get("from") == "alert@confinia.io"
    assert "password" not in smtp              # secrets never in git
    assert realm.get("verifyEmail") is False   # safe bootstrap; script promotes
    assert realm.get("registrationAllowed") is True
    sh = (ROOT / "deploy/kc-smtp.sh").read_text()
    assert "verifyEmail=true" in sh            # registration confirmation flow
    assert "smtpServer.password=$SMTP_PASSWORD" in sh  # creds from secrets.env
    assert "pre-flight" in sh.lower()          # never enabled with bad creds
    stack = (ROOT / "deploy/stack-up.sh").read_text()
    assert "kc-smtp.sh" in stack               # applied on every deploy
    assert "set -a; . deploy/secrets.env" in stack  # compose substitution source


@needs_repo
def test_keycloak_client_uris_are_code():
    """The live client's URI surface is replayed from realm-confinia.json on
    every deploy (kc-client.sh) — pre-prod is staging., next. must not exist
    anywhere (rule 12)."""
    import json
    realm = json.loads((ROOT / "auth_stack/realm-confinia.json").read_text())
    client = next(c for c in realm["clients"] if c["clientId"] == "ecobuilding-web")
    assert any("staging.ecobuilding" in u for u in client["redirectUris"])
    assert not any("next.ecobuilding" in u for u in client["redirectUris"])
    sh = (ROOT / "deploy/kc-client.sh").read_text()
    assert "realm-confinia.json" in sh and "redirectUris" in sh
    assert "kc-client.sh" in (ROOT / "deploy/stack-up.sh").read_text()


@needs_repo
def test_cicd_pipeline_is_code():
    """Rule 14: the pipeline mirrors code state — PR→sandbox, main→staging,
    dispatch→promote — on the VM's own runner; the wrappers stay break-glass."""
    wf = ROOT / ".github/workflows"
    sandbox = (wf / "sandbox.yml").read_text()
    staging = (wf / "staging.yml").read_text()
    promote = (wf / "promote.yml").read_text()
    assert "pull_request" in sandbox and "deploy/sandbox.sh" in sandbox
    assert "main" in staging and "deploy/stack-up.sh" in staging and "deploy/test.sh" in staging
    assert "workflow_dispatch" in promote and "deploy/promote-up.sh" in promote
    for y in (sandbox, staging, promote):
        assert "self-hosted" in y and "ecobuilding" in y
        assert "group: vm-deploy" in y          # one VM: deploys serialized
    assert "stack-up.sh" in (ROOT / "deploy/deploy.sh").read_text()      # wrapper
    assert "promote-up.sh" in (ROOT / "deploy/promote.sh").read_text()   # wrapper
    sandbox_sh = (ROOT / "deploy/sandbox.sh").read_text()
    # The sandbox script must never hand-edit the platform edge again
    # (reverted-on-redeploy + duplicate-site-block footgun).
    assert ">> ~/projects/platform" not in sandbox_sh
    # ...and must force-recreate: podman-compose keeps a running container on
    # a rebuilt image, silently serving stale code otherwise.
    assert "--force-recreate" in sandbox_sh


@needs_repo
def test_frontend_loading_feedback_is_wired():
    """#150: every loading path shows a spinner, and the PDF button walks the
    staged labels in order (honest staging — no fake percent for a single
    server-side render)."""
    app = (ROOT / "frontend/site/app.js").read_text()
    css = (ROOT / "frontend/site/style.css").read_text()
    # All loading paths use the narrated panel (rotating source labels).
    assert app.count("showLoadingPanel(") >= 3     # geolocate + search + click + def
    assert "LOADING_SOURCES" in app and "DGFiP" in app
    order = [app.index(s) for s in
             ("Collecte des données", "Rendu de la carte 3D", "Mise en page du PDF")]
    assert order == sorted(order)
    assert "downloadReport" in app and 'id="report-btn"' in app
    assert "window.open" in app                     # popup-safe: opened in-gesture
    assert ".hint.loading::before" in css and "@keyframes spin" in css


@needs_repo
def test_social_cards_and_favicon():
    """#169: shares must render as branded cards, tabs must carry the favicon."""
    idx = (ROOT / "frontend/site/index.html").read_text()
    for frag in ('rel="icon"', 'property="og:image"', 'og-image.png',
                 'name="twitter:card"', 'property="og:title"'):
        assert frag in idx, f"{frag} missing from index.html"
    assert (ROOT / "frontend/site/assets/og-image.png").stat().st_size > 10_000
    for page in ("apropos.html", "offres.html"):
        assert 'rel="icon"' in (ROOT / f"frontend/site/{page}").read_text()


@needs_repo
def test_dvf_prices_wired_everywhere():
    """#162: the self-hosted DVF RPC is wired in BOTH compose files (prod
    blue/green + sandbox) and the web panel renders the price block."""
    assert "DVF_RPC_URL" in (ROOT / "docker-compose.yml").read_text()
    assert (ROOT / "sandbox_stack/docker-compose.yml").read_text().count("DVF_RPC_URL") == 1
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "Prix de vente (DVF)" in app and "commune_eur_m2" in app


@needs_repo
def test_1pesi_port_migration():
    """#173: 13xxx band dual-published; loopback binds for the old 0.0.0.0
    exceptions; east-west traffic on the shared network (bridged containers
    cannot reach loopback host ports — verified empirically)."""
    root = (ROOT / "docker-compose.yml").read_text()
    assert "http://keycloak:8080/auth" in root and "http://render:8040/shot" in root
    assert "http://bdnb-rest:3005/rpc" in root and "ecobuilding-internal" in root
    assert "host.containers.internal:8181" not in root
    assert "127.0.0.1:13100:80" in (ROOT / "deploy/blue.override.yml").read_text()
    assert "127.0.0.1:13200:80" in (ROOT / "deploy/green.override.yml").read_text()
    assert "127.0.0.1:13070:8080" in (ROOT / "auth_stack/docker-compose.yml").read_text()
    assert "127.0.0.1:13080:8040" in (ROOT / "render_stack/docker-compose.yml").read_text()
    assert "127.0.0.1:13020:3005" in (ROOT / "bdnb_stack/docker-compose.yml").read_text()
    assert "127.0.0.1:13400:8030" in (ROOT / "sandbox_stack/docker-compose.yml").read_text()
    for f, frag in (("caddy_server/Caddyfile.blue", ":13000"),
                    ("caddy_server/Caddyfile.green", ":13000"),
                    # staging owns the 1PESI X300 listener (platform 2026-08-16)
                    ("caddy_server/Caddyfile.blue", ":13300"),
                    ("caddy_server/Caddyfile.green", ":13300"),
                    ("monitoring_stack/docker-compose.yml", "13040"),
                    ("monitoring_stack/docker-compose.yml", "13050"),
                    ("monitoring/grafana-shared/provisioning/datasources/prometheus.yaml", "13050"),
                    ("deploy/stack-up.sh", "13100"),
                    ("deploy/promote-up.sh", "13200"),
                    ("deploy/sandbox.sh", "ecobuilding-internal")):
        assert frag in (ROOT / f).read_text(), f"{frag} missing from {f}"
    # Legacy retired after the platform edge flip (2026-08-15).
    assert "127.0.0.1:8021:80" not in (ROOT / "deploy/blue.override.yml").read_text()
    assert "127.0.0.1:8030:8030" not in (ROOT / "sandbox_stack/docker-compose.yml").read_text()
    assert '"8181:8080"' not in (ROOT / "auth_stack/docker-compose.yml").read_text()
    assert '"8040:8040"' not in (ROOT / "render_stack/docker-compose.yml").read_text()
    assert '"3005:3005"' not in (ROOT / "bdnb_stack/docker-compose.yml").read_text()
    assert "8891" not in (ROOT / "monitoring/prometheus-shared.yml").read_text()
    assert ":8020" not in (ROOT / "caddy_server/Caddyfile.blue").read_text()
    # No CI/CD script may still address a legacy HOST port (audit 2026-08-15):
    # container-internal ports (:8030 inside sandbox caddy, :3005 PostgREST,
    # :8040 render) are fine — only host publishes were migrated.
    sandbox_sh2 = (ROOT / "deploy/sandbox.sh").read_text()
    assert "127.0.0.1:8030" not in sandbox_sh2 and "127.0.0.1:13400" in sandbox_sh2
    assert not (ROOT / "monitoring/prometheus.yml").exists()   # dead pre-shared config
    assert "caddy_server/Caddyfile" in (ROOT / ".gitignore").read_text()


@pytest.mark.skip(reason="e2e email delivery: needs live SMTP creds + a mailbox check")
def test_registration_email_delivered_e2e():
    """Register a throwaway user on sandbox -> a verification email arrives
    from alert@confinia.io. Manual/e2e only; never faked (rule 9)."""

@needs_repo
def test_account_tier_is_wired_in_the_app():
    """#206: the web app must carry the session into the fiche request (so the
    account allowance applies) and show what is left."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "refreshQuota" in app and "/usage" in app
    assert 'Authorization: "Bearer " + window.ecoToken()' in app
    assert "fiche" in app and "gopro" in app        # allowance + upsell


@needs_repo
def test_payg_pricing_is_consistent_everywhere():
    """#201: the offres page, the server formula and the Polar setup script
    must quote the SAME numbers — a pricing mismatch is a trust bug."""
    html = (ROOT / "frontend/site/offres.html").read_text()
    assert "9 €" in html and "0,49 €" in html and "99 €" in html
    assert "10 fiches" in html and "30 fiches" in html and "50 fiches" in html
    assert "234 fiches" in html                       # where the cap lands
    assert "500 crédits" not in html                   # the giveaway draft is gone
    assert 'id="sim-range"' in html                    # simulator present
    main_py = (ROOT / "api/app/main.py").read_text()
    assert 'BASE_FEE_EUR", "9"' in main_py             # the subscription base
    assert 'INCLUDED_FICHES", "50"' in main_py
    assert 'ANON_MONTHLY_REPORTS", "10"' in main_py
    assert 'FREE_ACCOUNT_REPORTS", "30"' in main_py
    assert 'PRICE_PER_CREDIT_EUR", "0.01"' in main_py
    assert 'MONTHLY_CAP_EUR", "99"' in main_py
    assert '"report": 49' in main_py                   # 49 credits = 0,49 EUR
    setup = (ROOT / "deploy/polar-setup.sh").read_text()
    assert "UNIT_CENTS:-1}" in setup and "CAP_CENTS:-9900}" in setup
    assert "BASE_CENTS:-900}" in setup                # the 9 EUR subscription base
    assert "cap_amount" in setup                       # Polar enforces the cap too
    assert (ROOT / "deploy/polar-sim.sh").exists()
