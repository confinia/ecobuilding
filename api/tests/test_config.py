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
    # Admin address inside the band and unique per caddy (1PESI, VM rule 2).
    for f in ("caddy_server/Caddyfile.blue", "caddy_server/Caddyfile.green"):
        assert "admin 127.0.0.1:13090" in (ROOT / f).read_text()
        assert ":2030" not in (ROOT / f).read_text()
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
    # The Pro CTA must stay behind the env flag everywhere it is revealed
    # (rule 7: no purchasable offer in prod until a >=10k EUR deal).
    for line in app.splitlines():
        if "gopro" in line and "hidden = false" in line:
            assert "ECO_PRO_ENABLED" in line, line


@needs_repo
def test_payg_pricing_is_consistent_everywhere():
    """#201: the offres page, the server formula and the Polar setup script
    must quote the SAME numbers — a pricing mismatch is a trust bug."""
    html = (ROOT / "frontend/site/offres.html").read_text()
    assert "0,49 €" in html and "99 €" in html
    assert "3 fiches" in html and "10 fiches" in html  # free ladder
    assert "212 fiches" in html                        # where the cap lands
    assert "crédit" not in html.lower()                # billed unit = la fiche
    assert "500 crédits" not in html                   # the giveaway draft is gone
    assert 'id="sim-range"' in html                    # simulator present
    main_py = (ROOT / "api/app/main.py").read_text()
    assert 'PRICE_PER_FICHE_EUR", "0.49"' in main_py   # the billed unit
    assert 'INCLUDED_FICHES", "10"' in main_py
    assert 'ANON_MONTHLY_REPORTS", "3"' in main_py
    assert 'FREE_ACCOUNT_REPORTS", "10"' in main_py
    assert 'MONTHLY_CAP_EUR", "99"' in main_py
    assert '"report": 1' in main_py                    # one unit = one fiche
    # PRICING.md is the source of truth and must quote the live numbers.
    pricing_doc = (ROOT / "PRICING.md").read_text()
    for n in ("0,49", "99 €", "212 fiches", "3", "10"):
        assert n in pricing_doc, n
    setup = (ROOT / "deploy/polar-setup.sh").read_text()
    assert "UNIT_CENTS:-49}" in setup and "CAP_CENTS:-9900}" in setup
    assert "fiches PDF" in setup                      # the customer-facing unit
    assert "cap_amount" in setup                       # Polar enforces the cap too
    assert (ROOT / "deploy/polar-sim.sh").exists()

@needs_repo
def test_self_service_support_and_signup(needs_repo_ok=None):
    """#212: a user must never be stuck — support contact at every friction
    point, and the sign-up journey is proven by a CI e2e (rule 19)."""
    api = (ROOT / "api/app/main.py").read_text()
    assert 'SUPPORT_EMAIL", "contact@confinia.io"' in api
    assert api.count("SUPPORT_EMAIL") >= 4            # quota msgs + 429 page
    assert "?signup=1" in api                          # one-click way out
    app = (ROOT / "frontend/site/app.js").read_text()
    assert 'get("signup") === "1"' in app and "kc.register(" in app
    assert 'get("welcome") === "1"' in app             # post-signup confirmation
    assert "r.status === 429" in app                   # in-app upsell path
    for page in ("index.html", "offres.html"):
        assert "contact@confinia.io" in (ROOT / f"frontend/site/{page}").read_text()
    assert "contact@confinia.io" in (ROOT / "api/app/report.py").read_text()
    wf = (ROOT / ".github/workflows/sandbox.yml").read_text()
    assert "e2e-signup.sh" in wf                       # journey proven per PR
    e2e = (ROOT / "deploy/e2e-signup.sh").read_text()
    assert "reports_left" in e2e and "429" in e2e and "contact@confinia.io" in e2e

@needs_repo
def test_maplibre_vendored_and_versions_match():
    """MapLibre is vendored SAME-ORIGIN (a CDN breaks the 6.x worker) and the
    web app and the PDF render must run the SAME version, or the fiche map
    silently diverges from what the user saw."""
    import json
    # The dist is minified with no reliable version marker, so vendoring
    # records it in assets/maplibre/VERSION (updated with the files).
    vendored = (ROOT / "frontend/site/assets/maplibre/VERSION").read_text().strip()
    render = json.loads((ROOT / "render_stack/package.json").read_text())
    assert render["dependencies"]["maplibre-gl"] == vendored, (
        vendored, render["dependencies"]["maplibre-gl"])
    idx = (ROOT / "frontend/site/index.html").read_text()
    assert "assets/maplibre/maplibre-gl.mjs" in idx
    # No CDN *import* (a comment may still mention esm.sh to explain why not).
    assert "from 'https://esm.sh" not in idx and 'from "https://esm.sh' not in idx


@needs_repo
def test_auth_buttons_never_depend_on_a_cdn():
    """#215: the sign-up path is the product's front door — it must survive a
    blocked CDN, a failed adapter import and an IdP hiccup."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "esm.sh" not in app                      # adapter vendored
    assert "./assets/keycloak/keycloak.mjs" in app
    assert (ROOT / "frontend/site/assets/keycloak/keycloak.mjs").stat().st_size > 10_000
    # Buttons are shown BEFORE any await, and carry working direct URLs.
    head = app[:app.index("let Keycloak")]
    assert 'show("signin", true); show("signup", true);' in head
    assert "openid-connect/${action}" in head          # templated auth URLs
    assert 'authUrl("registrations")' in head           # sign-up without JS

@needs_repo
def test_account_panel_and_payment_banner():
    """#220/#221/#222: the key is retrievable from the UI, a sandbox payment
    mode is announced, and the marker sits on the roof."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "showAccount" in app and "Générer une clé API" in app
    assert "/keys" in app and "copykey" in app        # created once, copyable
    assert "paybanner" in app and 'payment_mode !== "sandbox"' in app
    assert "updateMarkerElevation" in app and "getPitch()" in app
    css = (ROOT / "frontend/site/style.css").read_text()
    assert "#paybanner" in css and "ul.keys" in css
