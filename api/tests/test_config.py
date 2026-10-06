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
    # #229: the SANDBOX realm needs it too, or « mot de passe oublié » fails
    # with « Erreur lors de l'envoi du courriel ».
    sandbox_sh = (ROOT / "deploy/sandbox.sh").read_text()
    assert "kc-smtp.sh" in sandbox_sh and "REALM=sandbox-ecobuilding" in sandbox_sh
    kc_smtp = (ROOT / "deploy/kc-smtp.sh").read_text()
    assert 'REALM="${REALM:-confinia}"' in kc_smtp        # parameterised
    assert 'KC_CONTAINER' in kc_smtp and 'SECRETS' in kc_smtp
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
    dispatch→promote. Image builds (#409) and the pytest gate (#411) run on
    GitHub-hosted runners; the VM's own runner only pulls and deploys. The
    wrappers stay break-glass."""
    wf = ROOT / ".github/workflows"
    sandbox = (wf / "sandbox.yml").read_text()
    staging = (wf / "staging.yml").read_text()
    promote = (wf / "promote.yml").read_text()
    assert "pull_request" in sandbox and "deploy/sandbox.sh" in sandbox
    assert "main" in staging and "deploy/stack-up.sh" in staging
    assert "workflow_dispatch" in promote and "deploy/promote-up.sh" in promote
    # #409/#411: image builds and the pytest gate run OFF the shared VM, on
    # GitHub-hosted runners; the VM only pulls images and deploys.
    build_wf = (wf / "build-images.yml").read_text()
    test_wf = (wf / "test.yml").read_text()
    assert "ghcr.io/confinia/ecobuilding-" in build_wf and "ubuntu-latest" in build_wf
    assert "deploy/test.sh" in test_wf and "ubuntu-latest" in test_wf
    for caller in (sandbox, staging):
        assert "build-images.yml" in caller and "test.yml" in caller
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
def test_ci_outcomes_are_recorded_and_visible():
    """#469, règle 25 : chaque workflow consigne son issue — SUCCÈS COMPRIS,
    sinon le silence ne se distingue pas du beau temps — et un tableau de bord
    la montre, avec une règle d'alerte sur le dernier passage en échec."""
    import json as _json
    import yaml as _yaml

    for nom in ("sandbox", "staging", "promote", "bdnb-import", "bdnb-stack"):
        wf = (ROOT / f".github/workflows/{nom}.yml").read_text()
        assert "ci-record.sh" in wf, nom
        bloc = wf[max(0, wf.index("ci-record.sh") - 400):]
        assert "if: always()" in bloc, f"{nom} ne consigne que les échecs"
        assert f'"{nom}"' in wf and "job.status" in wf, nom

    record = (ROOT / "deploy/ci-record.sh").read_text()
    assert "exit 0" in record, "le journal ne doit jamais casser la pipeline"
    assert "-v wf=" in record and "psql" in record   # valeurs passées en variables

    sql = (ROOT / "deploy/ci-run-table.sql").read_text()
    assert "meta.ci_run" in sql and "meta.ci_last" in sql
    assert "GRANT SELECT ON meta.ci_run, meta.ci_last TO grafana_ro" in sql

    dash = _json.loads((ROOT / "monitoring/grafana/dashboards/ci.json").read_text())
    assert dash["uid"] == "ci-runs"
    sqls = " ".join(t.get("rawSql", "") for p in dash["panels"]
                    for t in p.get("targets", []))
    assert "meta.ci_last" in sqls and "meta.ci_run" in sqls

    alertes = _yaml.safe_load(
        (ROOT / "monitoring/grafana-shared/provisioning/alerting/ops-email.yaml").read_text())
    regles = {r["uid"]: r for r in alertes["groups"][0]["rules"]}
    assert "ci-workflow-failed" in regles
    assert regles["ci-workflow-failed"]["annotations"]["__dashboardUid__"] == "ci-runs"
    # Grafana REFUSE `from: 0, to: 0` sur une requête de source de données, et
    # rejette alors tout le provisionnement : il redémarre en boucle et le
    # monitoring tombe (vécu le 27/09). Seul le nœud `__expr__` a droit à zéro.
    for regle in regles.values():
        for q in regle["data"]:
            fenetre = q.get("relativeTimeRange") or {}
            if q["datasourceUid"] != "__expr__":
                assert fenetre.get("from", 0) > 0, (regle["uid"], q["refId"])


@needs_repo
def test_no_trace_of_the_confinia_service():
    """#465: le service api.confinia.io est arrêté (coût sans usage). Aucune
    trace ne doit subsister — une variable oubliée dans un compose ferait
    croire à une intégration vivante, et un `extra_hosts` mort resterait à
    entretenir."""
    for rel in ("api/app/main.py", "api/app/report.py", "frontend/site/app.js",
                "docker-compose.yml", "sandbox_stack/docker-compose.yml",
                "deploy/secrets.env.example", "e2e/smoke.py"):
        texte = (ROOT / rel).read_text()
        assert "CONFINIA" not in texte, rel
        assert "api.confinia.io" not in texte, rel
        assert "commune_history" not in texte, rel
    # Le bloc commune ne fait plus partie du contrat servi.
    main_py = (ROOT / "api/app/main.py").read_text()
    assert '"commune", "dpe_spread"' not in main_py
    # `_date_fr` reste : la phrase d'interdiction de location s'en sert.
    assert "def _date_fr(" in main_py and "_date_fr(date)" in main_py


@needs_repo
def test_sandbox_db_does_not_fsync_every_commit():
    """#467: VM partagée saturée en IOPS. Le Postgres du bac à sable valide
    sans attendre le disque ; la prod garde le défaut, et `fsync=off` — celui
    qui peut laisser une base irrécupérable — reste réservé au miroir BDNB."""
    sandbox = (ROOT / "sandbox_stack/docker-compose.yml").read_text()
    assert "synchronous_commit=off" in sandbox
    # Le commentaire NOMME fsync=off pour dire qu'on ne le met pas ; c'est la
    # commande qui compte.
    cmd = [l for l in sandbox.splitlines() if "command:" in l and "postgres" in l]
    assert cmd and all("fsync=off" not in l for l in cmd), cmd
    prod = (ROOT / "docker-compose.yml").read_text()
    assert "synchronous_commit" not in prod, "la prod garde le défaut (#467)"
    bdnb = (ROOT / "bdnb_stack/docker-compose.yml").read_text()
    assert "fsync=off" in bdnb              # miroir rebuildable, déjà réglé


@needs_repo
def test_a_failing_source_alerts_without_false_alarms():
    """#491 : une alerte par source qui échoue durablement — mais ni un 404
    (« rien ici »), ni une heure creuse (pas de données) ne doivent alerter."""
    import json as _json
    import yaml as _yaml

    alertes = _yaml.safe_load(
        (ROOT / "monitoring/grafana-shared/provisioning/alerting/ops-email.yaml").read_text())
    r = {x["uid"]: x for x in alertes["groups"][0]["rules"]}["upstream-source-failing"]
    expr = r["data"][0]["model"]["expr"]
    assert 'outcome=~"error|failure"' in expr and "not_found" not in expr
    assert ">= 5" in expr and "by (source)" in expr
    assert r["noDataState"] == "OK"
    noeuds = {q["refId"]: q for q in r["data"]}
    assert noeuds["B"]["model"]["type"] == "reduce" and noeuds["C"]["model"]["expression"] == "B"
    dash = _json.loads((ROOT / "monitoring/grafana/dashboards/ecobuilding.json").read_text())
    assert r["annotations"]["__panelId__"] in {str(p["id"]) for p in dash["panels"]}


@needs_repo
def test_no_false_alerts_and_monitoring_config_applies():
    """#487 : deux alertes écrivaient à l'opérateur sans que rien ne soit cassé.
    Prometheus 3 rejetait les /metrics de PostgREST (Content-Type vide), et la
    règle CI n'a jamais évalué (une série au lieu d'une valeur réduite). Et la
    configuration du monitoring doit s'appliquer au déploiement, sans attendre
    un redémarrage."""
    import yaml as _yaml

    prom = _yaml.safe_load((ROOT / "monitoring/prometheus-shared.yml").read_text())
    jobs = {j["job_name"]: j for j in prom["scrape_configs"]}
    for nom in ("bdnb-rest", "bdnb-open"):
        assert jobs[nom].get("fallback_scrape_protocol") == "PrometheusText0.0.4", nom

    alertes = _yaml.safe_load(
        (ROOT / "monitoring/grafana-shared/provisioning/alerting/ops-email.yaml").read_text())
    ci = {r["uid"]: r for r in alertes["groups"][0]["rules"]}["ci-workflow-failed"]
    noeuds = {q["refId"]: q for q in ci["data"]}
    assert noeuds["B"]["model"]["type"] == "reduce" and noeuds["B"]["model"]["expression"] == "A"
    assert noeuds["C"]["model"]["expression"] == "B" and ci["condition"] == "C"
    assert "conclusion = 'failure'" in noeuds["A"]["model"]["rawSql"]   # annulé ≠ échec
    dash = (ROOT / "monitoring/grafana/dashboards/ci.json").read_text()
    assert "conclusion = 'failure'" in dash

    up = (ROOT / "deploy/stack-up.sh").read_text()
    # Montée comme UN FICHIER, la config est figée par l'inode : SIGHUP relit
    # l'ancienne. On compare et on redémarre seulement si elle a changé.
    assert "podman kill -s HUP" not in up
    assert "sha256sum < monitoring/prometheus-shared.yml" in up
    assert "podman restart ecobuilding-monitoring_prometheus_1" in up
    assert "/api/admin/provisioning/alerting/reload" in up


@needs_repo
def test_every_stack_comes_back_after_a_reboot():
    """#484 : après un redémarrage de la VM, aucun des 24 conteneurs ne
    revenait. Une unité par pile, installée par le déploiement, qui REDÉMARRE
    LE POD tel quel — jamais un `podman-compose up`, qui recréerait la
    production sur `:latest` faute du tag du commit déployé."""
    unite = (ROOT / "deploy/systemd/ecobuilding-stack@.service").read_text()
    assert "Type=oneshot" in unite
    assert "RemainAfterExit=yes" in unite          # #144 : garde les auxiliaires
    assert "ExecStart=/usr/bin/podman pod start pod_ecobuilding-%i" in unite
    commandes = [l for l in unite.splitlines() if l.startswith("Exec")]
    assert not any("podman-compose" in l or "up -d" in l for l in commandes)
    # Arrêt propre à l'extinction : le miroir BDNB (fsync=off) a besoin de
    # temps pour son point de contrôle, plus que les 10 s par défaut.
    assert "podman pod stop -t 60" in unite and "WantedBy=default.target" in unite

    install = (ROOT / "deploy/boot-units.sh").read_text()
    for pile in ("auth", "bdnb", "render", "monitoring", "edge", "blue", "green", "sandbox"):
        assert pile in install.split("for pile in")[1].split(";")[0], pile
    assert "enable --now" in install and "podman pod exists" in install
    up = (ROOT / "deploy/stack-up.sh").read_text()
    # Appelé AVANT le contrôle final, qui sort du script dès qu'il réussit.
    assert up.index("./deploy/boot-units.sh") < up.index('if [ "$CANDIDATE" = blue ]')


@needs_repo
def test_stack_up_waits_for_keycloak_before_configuring_it():
    """#475 : le premier changement du compose d'identité a redémarré Keycloak,
    les quatre réglages du royaume ont échoué pendant son démarrage, et le
    déploiement est resté vert. On attend Keycloak — de façon BORNÉE — et un
    échec s'affiche en annotation du run, pas seulement dans le journal."""
    up = (ROOT / "deploy/stack-up.sh").read_text()
    lancement = up.index("podman-compose -p ecobuilding-auth")
    attente = up.index("/auth/realms/confinia/.well-known/openid-configuration")
    premier_reglage = up.index("kc_step kc-smtp.sh")
    assert lancement < attente < premier_reglage
    assert "seq 1 60" in up.split("KC_OK=")[1][:200]     # bornée, jamais sans fin
    for etape in ("kc-smtp", "kc-client", "kc-theme", "kc-master"):
        assert f"kc_step {etape}.sh" in up, etape
    assert "::warning::$1 a échoué" in up


@needs_repo
def test_admin_realm_stays_off_public_hosts():
    """Le royaume d'administration Keycloak (master) et sa console ne répondent
    que sur iam.ecobuilding.confinia.io ; chaque hôte public les refuse AVANT
    de relayer vers Keycloak. Et la connexion d'administration se verrouille
    temporairement après des échecs répétés, réglage rejoué à chaque déploiement."""
    import re as _re

    for f in ("caddy_server/Caddyfile.blue", "caddy_server/Caddyfile.green",
              "sandbox_stack/Caddyfile"):
        cf = (ROOT / f).read_text()
        blocs = _re.findall(r"handle /auth/\* \{(.*?)\n\t\}", cf, _re.S)
        assert blocs, f
        for b in blocs:
            assert "/auth/realms/master" in b and "/auth/admin" in b, f
            # Le refus AVANT le relais, dans le même bloc.
            # (la DIRECTIVE, en début de ligne — pas le mot dans le commentaire)
            assert b.index("respond @admin_keycloak 404") < b.index("\n\t\treverse_proxy "), f

    kc = (ROOT / "deploy/kc-master.sh").read_text()
    assert "bruteForceProtected=true" in kc
    # Un verrou DÉFINITIF offrirait un déni de service à qui connaît le nom
    # du compte : il reste temporaire.
    assert "permanentLockout=false" in kc and "maxFailureWaitSeconds=900" in kc
    assert "kc-master.sh" in (ROOT / "deploy/stack-up.sh").read_text()
    assert "kc-master.sh" in (ROOT / "deploy/sandbox.sh").read_text()


@needs_repo
def test_frontend_lists_other_buildings_readably():
    """#462: la nature d'abord, une ligne pleine largeur, et une ANNEXE qui ne
    mène nulle part — une fiche et un rapport par adresse, l'annexe dedans."""
    app = (ROOT / "frontend/site/app.js").read_text()
    css = (ROOT / "frontend/site/style.css").read_text()
    fn = app[app.index("function batimentLabel"):app.index("function sectionFiscalite")]
    assert 'bouts.push("Annexe probable")' in fn
    assert "!(o.annexe && !o.dwellings)" in fn            # pas de « 0 logements »
    assert "Bâtiment ${i + 2}" in fn                      # numérotées, donc nommables
    assert "Voir sa fiche" not in app                     # plus de colonne répétée
    assert "o.annexe" in fn and "class=\"autre-bat\"" in fn  # annexe : texte, pas lien
    assert ".autre-bat-ligne" in css


@needs_repo
def test_signing_in_comes_back_to_the_same_place():
    """#474 : se connecter quittait la page et on revenait sur le bâtiment
    vitrine. Aucun chemin d'authentification ne doit reconstruire une URL à
    partir de `location.origin` seul : ni les liens du mur de quota, ni les
    `redirectUri` passés à Keycloak."""
    app = (ROOT / "frontend/site/app.js").read_text()
    auth = app[app.index("function initAuth"):app.index("function ecoPricing")
               if "function ecoPricing" in app else len(app)]
    # Les anciennes formes, toutes parties.
    assert 'location.origin + "/?welcome=1"' not in app
    assert 'location.origin + "/?gopro="' not in app
    assert 'href="/?login=1"' not in app and 'href="/?signup=1"' not in app
    # La place est gardée puis rendue.
    assert "sessionStorage.setItem(RETOUR" in app and "restaurerLaPlace()" in app
    assert "retourAvec(" in app and "lienAuth(" in app
    # Un redirect_uri ne doit PAS porter de fragment (RFC 6749 §3.1.2) : c'est
    # pour cela que la place passe par sessionStorage.
    retour = app[app.index("const retourAvec ="):app.index("const restaurerLaPlace")]
    assert "location.hash" not in retour
    # ... alors que le lien du mur de quota, lui, le garde.
    lien = app[app.index("function lienAuth"):]
    assert "location.hash" in lien.split("}")[0]


@needs_repo
def test_keycloak_login_theme_is_provisioned_like_the_realm():
    """#475 : la page de connexion porte la marque, et elle la porte DURABLEMENT —
    le thème est dans le dépôt, monté dans les deux piles, et rejoué sur le
    royaume vivant (l'import ne met jamais à jour un royaume existant)."""
    import json as _json
    import re as _re

    theme = ROOT / "auth_stack/themes/ecobuilding/login"
    props = (theme / "theme.properties").read_text()
    assert "parent=keycloak.v2" in props            # étendre, jamais recopier
    # Déclarer `styles` REMPLACE la liste du parent : la sienne d'abord.
    assert "styles=css/styles.css css/ecobuilding.css" in props
    assert "darkMode=false" in props
    assert (theme / "resources/css/ecobuilding.css").exists()
    assert (theme / "resources/img/logo.svg").read_text() == \
        (ROOT / "frontend/site/assets/logo.svg").read_text()   # UN logo, pas deux
    css = (theme / "resources/css/ecobuilding.css").read_text()
    assert "#2b7a4b" in css and "--keycloak-logo-url" in css

    for langue in ("fr", "en"):
        msgs = (theme / f"messages/messages_{langue}.properties").read_text()
        valeur = next(l for l in msgs.splitlines() if l.startswith("loginTitleHtml="))
        # MessageFormat : une apostrophe SEULE ouvre une citation et avale la
        # suite de la phrase. Elles doivent toutes être doublées.
        assert not _re.search(r"(?<!')'(?!')", valeur), langue
        # Aucun chiffre de quota : pricing.json est la source unique (#397).
        assert not _re.search(r"\d+ (fiches|reports)", valeur), langue

    assert "./themes/ecobuilding:/opt/keycloak/themes/ecobuilding:ro" in \
        (ROOT / "auth_stack/docker-compose.yml").read_text()
    assert "../auth_stack/themes/ecobuilding:/opt/keycloak/themes/ecobuilding:ro" in \
        (ROOT / "sandbox_stack/docker-compose.yml").read_text()
    for f in ("auth_stack/realm-confinia.json", "sandbox_stack/realm-sandbox-ecobuilding.json"):
        assert _json.loads((ROOT / f).read_text())["loginTheme"] == "ecobuilding", f

    kc = (ROOT / "deploy/kc-theme.sh").read_text()
    assert "loginTheme=$THEME" in kc
    # Ne jamais désigner un thème absent : la connexion deviendrait une erreur.
    assert "test -f" in kc and "exit 1" in kc
    assert "kc-theme.sh" in (ROOT / "deploy/stack-up.sh").read_text()
    assert "kc-theme.sh" in (ROOT / "deploy/sandbox.sh").read_text()


@needs_repo
def test_frontend_deep_links_to_a_search():
    """#460: a URL opens a fiche by address (?q= free text, ?ban= BAN key),
    not only by building id (?b=, #14). The map's click handlers must still
    be registered on that path — an early return made the map inert."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert 'get("q")' in app and 'get("ban")' in app
    assert "openSearchFromUrl" in app
    # Both the WebGL2 path and the dead-map fallback honour the link.
    assert app.count("openSearchFromUrl()") >= 2
    # The search link is resolved server-side, no client-side geocoding.
    assert "lookup/stream?${params}" in app
    debut = app.index("openSearchFromUrl();")
    fin = app.index('map.on("click", "bdnb-dpe-3d"')
    assert "return;" not in app[debut:fin], "la carte resterait inerte"


@needs_repo
def test_web_map_selects_nothing_on_arrival_and_never_on_a_drag():
    """#525: no building is opened by default; the first camera stays, a fiche
    opens only from ?b=, a search link, a click or a search. #526: a click
    that ends after the camera moved (pan, zoom, tilt) selects nothing."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "bdnb_id" not in app[app.index("const SHOWCASE = {"):][:200]
    assert "showcase_default" not in app
    assert "openBuildingById(urlBuilding, c.lng, c.lat)" in app
    clic = app[app.index('map.on("click", "bdnb-dpe-3d"'):][:120]
    assert "if (carteBougee()) return;" in clic
    assert 'addEventListener("pointerdown"' in app


@needs_repo
def test_frontend_loading_feedback_is_wired():
    """#150: every loading path shows a spinner. #506: the PDF wait shows the
    server's REAL stages, ticked as the server finishes them (progress token,
    polled), in order; the bar only creeps inside the current stage."""
    app = (ROOT / "frontend/site/app.js").read_text()
    css = (ROOT / "frontend/site/style.css").read_text()
    # All loading paths use the narrated panel (rotating source labels).
    assert app.count("showLoadingPanel(") >= 3     # geolocate + search + click + def
    assert "LOADING_SOURCES" in app and "DGFiP" in app
    order = [app.index(s) for s in
             ('["data", "Données du bâtiment"', '["render_3d", "Carte 3D"',
              '["quartier", "Plan du quartier"', '["compose", "Mise en page"')]
    assert order == sorted(order)
    assert '"progress=" + jeton' in app and "/report/progress/${jeton}" in app
    assert "Math.min((maintenant - debutEtapeMs) / (enCours[1] * 1000), 0.9)" in app
    assert "downloadReport" in app and 'id="report-btn"' in app
    assert "window.open" in app                     # popup-safe: opened in-gesture
    assert ".hint.loading::before" in css and "@keyframes spin" in css


@needs_repo
def test_dpe_perdu_entry_page():
    """#412: the 'retrouver un DPE perdu' entry page reuses the existing
    non-stream endpoints, is honest when no DPE exists, surfaces the ADEME
    number as the key to the official document, and links back to the fiche +
    PDF. Discoverable from the map topbar."""
    dpe = (ROOT / "frontend/site/dpe.html").read_text()
    # Reuses the public endpoints, not a new backend or the NDJSON stream.
    assert "/suggest?" in dpe and "/lookup?ban_id=" in dpe
    assert "/lookup/stream" not in dpe and "/buildings/" not in dpe
    # Reads the DPE from the same fields the fiche uses (validity wording is
    # shared with the fiche since #414, see the test below).
    assert "official_dpe" in dpe and "dpe_class" in dpe
    # Expiry recomputed client-side exactly like report.py (valid_until < today),
    # the validity date itself coming from the API (never the 2021 rule recoded).
    assert "TODAY" in dpe and "expired" in dpe
    # A pre-2021 DPE has a date but no class in BDNB: never the empty state.
    assert "!enDate" in dpe and "Classe non reprise" in dpe
    # Reachable from the map.
    assert 'href="/dpe.html"' in (ROOT / "frontend/site/index.html").read_text()


@needs_repo
def test_dpe_validity_wording_is_shared_and_measured():
    """#414: the fiche and dpe.html say the same thing about a lapsed DPE
    (one shared file), the fiche actually shows validity, the DPE page is
    measured and indexed."""
    site = ROOT / "frontend/site"
    shared = (site / "dpe-validite.js").read_text()
    # One wording, from API-served dates: greyed badge, pre-2021 named,
    # ban in the past tense once passed and conditional on a lapsed DPE.
    assert "dpe_valid_until" in shared and "valid_until" in shared
    assert "ancienne méthode" in shared and "2021-07-01" in shared
    assert "interdite depuis le" in shared and "interdite à partir du" in shared
    assert "s'il confirme la classe" in shared
    for page in ("index.html", "dpe.html"):
        assert 'src="dpe-validite.js"' in (site / page).read_text(), page
    app = (site / "app.js").read_text()
    assert "ecoDpe.validite(" in app and "DPE périmé" in app and "dpe-validity" in app
    assert "à partir de <strong>" not in app         # the 2026 "à partir de 2025"
    dpe = (site / "dpe.html").read_text()
    assert "ecoDpe.validite(" in dpe and "DPE périmé" in dpe
    assert "DPE de l'ancienne méthode" not in dpe   # card wording lives in ONE place
    assert "badgewrap.expired .dpe-badge" in (site / "style.css").read_text()
    # Measured (#347 beacon, known labels only) and indexed.
    assert 'track("dpe_page_view")' in dpe and '"dpe_page_lookup"' in dpe
    for meta in ('"lapsed"', '"found"', '"none"'):
        assert meta in dpe, meta
    assert "ecobuilding.confinia.io/dpe.html" in (site / "sitemap.xml").read_text()
    # The ADEME number is the key to the lost official document.
    assert "dpe_number" in dpe and "ecoDpe.ademeUrl(" in dpe   # link built in dpe-validite.js (#418)
    # Honest empty state — many buildings have no DPE on record.
    assert "Aucun DPE n'est enregistré" in dpe
    # CTAs back into the product: full fiche (?b=) and the free PDF.
    assert "/?b=" in dpe and "/report/" in dpe
    # Reachable from the map.
    assert 'href="/dpe.html"' in (ROOT / "frontend/site/index.html").read_text()


@needs_repo
def test_fiche_is_never_mistaken_for_the_dpe():
    """#418: wherever our PDF is offered, the page says it is not the DPE, in
    one shared sentence; the official route goes first on dpe.html and every
    DPE number links to the document at ADEME, by its number."""
    site = ROOT / "frontend/site"
    shared = (site / "dpe-validite.js").read_text()
    assert "NOT_THE_DPE" in shared and "Ce n'est pas le diagnostic de performance énergétique" in shared
    assert "diagnostiqueur certifié" in shared and "archivé par l'ADEME" in shared
    assert "observatoire-dpe-audit.ademe.fr/afficher-dpe/" in shared
    dpe = (site / "dpe.html").read_text()
    assert "Consulter le DPE officiel (ADEME)" in dpe and "ecoDpe.ademeUrl(num)" in dpe
    assert "Fiche EcoBuilding (PDF) — pas le DPE" in dpe and "ecoDpe.NOT_THE_DPE" in dpe
    assert "Informations publiques du DPE" in dpe
    assert "Télécharger la fiche PDF" not in dpe
    # The ADEME button comes before our PDF button.
    assert dpe.index("Consulter le DPE officiel") < dpe.index("Fiche EcoBuilding (PDF)")
    app = (site / "app.js").read_text()
    assert "Fiche EcoBuilding (PDF) — pas le DPE" in app and "ecoDpe.NOT_THE_DPE" in app
    assert "Obtenir la fiche PDF" not in app
    assert 'kv("N° DPE officiel", ademeLink(' in app and 'kv("N° DPE", ademeLink(' in app
    # The map loads the shared file before app.js.
    idx = (site / "index.html").read_text()
    assert idx.index('src="dpe-validite.js"') < idx.index("s.src = 'app.js'")


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
    # Dedicated API hostnames: environment leftmost, SAME entry port as the
    # environment (a dedicated prod API port would push colour-awareness into
    # the platform edge), path prefixed so the stack caddy strips it.
    for f in ("caddy_server/Caddyfile.blue", "caddy_server/Caddyfile.green"):
        c = (ROOT / f).read_text()
        assert "http://api.ecobuilding.confinia.io:13000" in c
        assert "http://staging.api.ecobuilding.confinia.io:13300" in c
        assert "api.staging.ecobuilding" not in c      # wrong ordering
        assert "rewrite * /api{uri}" in c
    sb = (ROOT / "sandbox_stack/Caddyfile").read_text()
    assert "sandbox.api.ecobuilding.confinia.io" in sb
    # The path form must keep working during the transition (dual-publish).
    for f in ("caddy_server/Caddyfile.blue", "caddy_server/Caddyfile.green"):
        assert "handle /auth/*" in (ROOT / f).read_text()
    assert "handle_path /api/*" in (ROOT / "stack_caddy/Caddyfile").read_text()

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
def test_tier_pricing_is_consistent_everywhere():
    """#397 : api/app/pricing.json est le SPOT (source unique). Toutes les
    surfaces — offres.html, PRO_TIERS/constantes serveur, creem-setup.sh —
    doivent s'y accorder ; un écart de prix ou de quota est un bug de confiance.
    Le serveur et le script DÉRIVENT du SPOT ; la page HTML est écrite à la main,
    donc c'est elle qu'on confronte nombre par nombre."""
    import json
    spot = json.loads((ROOT / "api/app/pricing.json").read_text())["tiers"]
    html = (ROOT / "frontend/site/offres.html").read_text()

    # Gratuit : quota mensuel affiché.
    disc = spot["discover"]
    assert f"{disc['quota']} fiches PDF par mois" in html
    # Chaque palier Pro : quota/jour affiché ; prix affiché SAUF l'offert (gratuit).
    for key in ("pro_s", "pro_m", "pro_l"):
        t = spot[key]
        if t["quota"] is not None:
            assert f"{t['quota']} fiches PDF par jour" in html, key
        if not t["launch_free"]:
            assert f"{t['price_month']} €" in html, key
    assert "offre de lancement" in html.lower() and "gratuit" in html.lower()
    assert "clé API" in html
    assert "crédit" not in html.lower()                 # unité facturée = la fiche

    # PRO_TIERS et les quotas gratuits DÉRIVENT du SPOT : on vérifie l'accord.
    from app.main import PRO_TIERS, ANON_MONTHLY_REPORTS, FREE_ACCOUNT_REPORTS, CREDIT_COST
    for key in ("pro_s", "pro_m", "pro_l"):
        t = spot[key]
        k = key[len("pro_"):]
        assert PRO_TIERS[k]["eur"] == t["price_month"], key
        assert PRO_TIERS[k]["fiches_jour"] == t["quota"], key
        assert PRO_TIERS[k]["label"] == t["name"], key
    assert ANON_MONTHLY_REPORTS == disc["quota"]
    assert FREE_ACCOUNT_REPORTS == disc["quota"]
    assert CREDIT_COST["report"] == 1                   # une unité = une fiche

    # creem-setup.sh lit le SPOT, il ne code plus les cents en dur.
    setup = (ROOT / "deploy/creem-setup.sh").read_text()
    assert "pricing.json" in setup and "cents pro_m" in setup

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
def test_site_points_to_the_iphone_app():
    """#422: the app is on the App Store; Safari iOS gets the Smart App Banner
    on the two entry pages and every page links the listing."""
    APP_ID = "id6803865290"
    for page in ("index.html", "dpe.html"):
        html = (ROOT / "frontend/site" / page).read_text()
        assert '<meta name="apple-itunes-app" content="app-id=6803865290">' in html, page
    for page in ("index.html", "dpe.html", "apropos.html"):
        html = (ROOT / "frontend/site" / page).read_text()
        assert f"https://apps.apple.com/fr/app/ecobuilding/{APP_ID}" in html, page


@needs_repo
def test_map_constructor_guarded_since_maplibre_6_7():
    """#420: MapLibre >= 6.7 THROWS GPUInitializationError from the Map
    constructor without WebGL2. The web app must survive it (search and fiche
    still work, a notice says why) and the render page must report it
    through window.__error instead of sitting out puppeteer's timeout."""
    vendored = (ROOT / "frontend/site/assets/maplibre/VERSION").read_text().strip()
    assert tuple(int(x) for x in vendored.split(".")) >= (6, 7, 0), vendored
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "function createMap()" in app and "const map = createMap();" in app
    guard = app[app.index("function createMap()"):app.index("const map = createMap();")]
    assert "try {" in guard and "new maplibregl.Map({" in guard and "catch (e)" in guard
    assert "mapDead = e" in guard and "new Proxy(" in guard      # inert map, no throws later
    assert "ne permet pas d'afficher la carte 3D" in app          # the notice
    assert "openBuildingById(urlBuilding, +h[2], +h[1])" in app  # ?b= link still opens
    # The fiche path never touches the map unguarded.
    body = app[app.index("async function openBuildingById"):]
    body = body[:body.index("\n}\n")]
    assert "safeMap(() => placeMarker(lon, lat))" in body
    render = (ROOT / "render_stack/render.html").read_text()
    assert "map = new maplibregl.Map({" in render
    assert "window.__error = String(e);" in render


@needs_repo
def test_map_bearing_locked_north_up():
    """#505: rotating the map around its vertical axis lost the end user.
    Every camera change is forced north-up, the compass is gone, rotation
    gestures are off, and a shared link's bearing is reset once loaded."""
    app = (ROOT / "frontend/site/app.js").read_text()
    guard = app[app.index("function createMap()"):app.index("const map = createMap();")]
    assert "transformCameraUpdate: () => ({ bearing: 0 })" in guard
    assert "NavigationControl({ showCompass: false })" in app
    assert "map.touchZoomRotate.disableRotation();" in app
    assert "map.keyboard.disableRotation();" in app
    assert 'map.jumpTo({ bearing: 0 })' in app
    assert "bearing: -18" not in app        # no fly-to turns the map any more


@needs_repo
def test_web_map_offers_the_ign_aerial_photo():
    """#258: a Plan / Photo switch on the web map, IGN orthophoto under the
    labels and the DPE volumes, volumes faded (not hidden) in photo mode."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "LAYER=ORTHOIMAGERY.ORTHOPHOTOS" in app and "data.geopf.fr/wmts" in app
    assert 'map.addLayer({ id: "ign-ortho", type: "raster"' in app
    assert 'layers.find((l) => l.type === "symbol")?.id' in app       # under the labels
    assert '"fill-extrusion-opacity", on ? 0.9 : 0.45' in app
    assert "map.addControl(new AerialToggle()" in app
    main = (ROOT / "api/app/main.py").read_text()
    assert '"aerial_on", "aerial_off"' in main


@needs_repo
def test_web_map_shows_prices_by_default():
    """#319: DVF cells (tint under the 3D volumes, label with the trend) and
    sold addresses (dot + label above) show from the first load; the Prix
    button hides them for the visit, nothing stored on the device. Relative
    colour scale with a legend, fonts the base style actually serves."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "map.addControl(new PriceToggle()" in app
    assert "const PRIX = { actif: true," in app
    couches = app[app.index('map.addSource("prix-cellules"'):app.index('map.on("moveend", chargerPrix);')]
    assert couches.count("visibility: visPrix") == 4 and 'visibility: "none"' not in couches
    assert 'map.on("moveend", chargerPrix);\n  chargerPrix();' in app
    bouton = app[app.index("class PriceToggle"):app.index("map.addControl(new PriceToggle()")]
    assert "localStorage" not in bouton
    assert '"bdnb-dpe-3d");' in app[app.index('id: "prix-cellules", type: "fill"'):][:600]
    assert app.count('"text-font": ["Noto Sans Bold"]') >= 2
    assert "/prices/${chemin}/${x}/${y}.json" in app and "out.length > 36" in app
    main = (ROOT / "api/app/main.py").read_text()
    assert '"prices_on", "prices_off"' in main
    sh = (ROOT / "deploy/bdnb-local-api.sh").read_text()
    assert "deploy/dvf-prix-carte.sql" in sh


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
    # Le repli construit les DEUX URL, et les recalcule au clic pour garder la
    # place (#474) — d'où `authUrl(action, …)` plutôt qu'un appel par bouton.
    assert '"registrations"' in head and "authUrl(action" in head

@needs_repo
def test_account_panel_and_payment_banner():
    """#220/#221/#222: the key is retrievable from the UI, a sandbox payment
    mode is announced, and the marker sits on the roof."""
    app = (ROOT / "frontend/site/app.js").read_text()
    assert "showAccount" in app and "Générer une clé API" in app
    assert "/keys" in app and "copykey" in app        # created once, copyable
    assert "paybanner" in app and 'payment_mode !== "sandbox"' in app
    # Épingles à l'ALTITUDE 0 (demande opérateur 2026-08-18) : l'élévation en
    # pixels (#222) mentait dès que la caméra tournait. Ce qui reste garanti :
    # pas d'épingle sans bâtiment (masquées sous le minzoom de la couche), et
    # aucun setOffset simulant une altitude.
    assert "updateMarkerVisibility" in app and "BUILDINGS_MINZOOM" in app
    assert "setOffset" not in app
    css = (ROOT / "frontend/site/style.css").read_text()
    assert "#paybanner" in css and "ul.keys" in css


def test_aucun_bouton_pro_quand_le_paiement_est_ferme():
    """Un bouton qui finit en « momentanément indisponible » est pire que pas
    de bouton : l'utilisateur a voulu payer et s'est heurté à une alerte.

    Le drapeau existait déjà, mais n'était posé qu'à UN endroit — l'en-tête.
    Le mur de quota, lui, proposait Pro quoi qu'il arrive. Ce test verrouille
    les deux surfaces."""
    js = (ROOT / "frontend/site/app.js").read_text()
    # Le mur web ne propose Pro que si l'offre est réellement ouverte.
    i = js.index("function showQuotaPanel")
    bloc = js[i:i + 3000]
    assert "ECO_PRO_ENABLED" in bloc, \
        "le mur de quota ignore si Pro est achetable"
    assert "mailto:contact@confinia.io" in bloc, \
        "sans offre ouverte, le mur doit recueillir le besoin, pas le perdre"

    # Et le mur rendu par le serveur suit la même règle.
    main_py = (ROOT / "api/app/main.py").read_text()
    j = main_py.index("Limite gratuite atteinte — EcoBuilding")
    assert 'PAYMENT_PROVIDER != "none"' in main_py[j:j + 2500], \
        "la page 429 propose les offres même quand rien n'est achetable"


def test_la_fiche_ne_se_dit_pas_normalisee():
    """« Fiche bâtiment normalisée » promettait une norme qui n'existe pas.

    Ce document est assemblé à partir de données ouvertes ; il ne se conforme
    à aucun référentiel. Emprunter l'autorité d'une norme est le genre de
    surenchère que ce produit passe son temps à retirer — et l'opérateur
    l'avait déjà corrigé sur la fiche App Store sans que ce soit répercuté."""
    report = (ROOT / "api/app/report.py").read_text()
    assert "Fiche bâtiment normalisée" not in report
    # Depuis #322 le titre se décline (« Fiche bâtiment » / « Fiche LOGEMENT »)
    # mais la promesse honnête — formatée et sourcée — reste littérale.
    assert "formatée et sourcée — données ouvertes" in report
    assert "Fiche bâtiment" in report and "Fiche LOGEMENT" in report
    # Aucun titre de document ne doit revendiquer une norme — il y en a deux,
    # la fiche et son annexe de traçabilité, et mon premier test ne visait que
    # la première trouvée, qui se trouvait être l'annexe.
    for i, ligne in enumerate(report.splitlines()):
        if 'class="doctitle"' in ligne:
            assert "normalis" not in ligne, f"ligne {i + 1} : {ligne}"

    app = (ROOT / "frontend/site/app.js").read_text()
    bouton = app[app.index('id="report-btn"'):][:400]
    assert "normalis" not in bouton


def test_les_deux_annonces_de_droits_disent_le_meme_droit_quotidien():
    """`/v1/config` et `/v1/pricing` exposent chacun un bloc `free_tiers`,
    identiques mot pour mot dans le code. Le champ quotidien de #294 a
    atterri dans un seul des deux — remplacement sur la première occurrence —
    et `/v1/config` a continué d'annoncer un monde mensuel."""
    from fastapi.testclient import TestClient

    import app.main as main

    c = TestClient(main.app)
    cfg = c.get("/v1/config").json()["free_tiers"]
    pri = c.get("/v1/pricing").json()["free_tiers"]
    assert cfg == pri, f"les deux annonces divergent :\n  config  {cfg}\n  pricing {pri}"
    assert cfg["free_account_reports_day"] == main.FREE_ACCOUNT_DAILY_REPORTS
