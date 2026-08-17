#!/bin/bash
# EcoBuilding — parcours e2e INSCRIPTION + PAIEMENT, joué dans un vrai
# navigateur par Selenium IDE (projet e2e/ecobuilding.side) et vérifié côté
# plateforme de paiement par e2e/polar_report.py (sandbox-api.polar.sh).
#
#   cp e2e/.env.example e2e/.env   # puis compléter
#   ./e2e/run.sh
#
# Tout est paramétré par e2e/.env : environnement visé (sandbox/staging),
# identifiants attendus, carte de test, jetons Polar, sélecteurs du checkout.
# Rien n'est codé en dur ici, sauf les valeurs par défaut ci-dessous.
#
# SÉCURITÉ : ne jouer que sur sandbox ou staging. La production n'a aucune
# configuration Polar (rule 7) — le paiement y est impossible par construction,
# et run.sh refuse ECO_ENV=production pour que ce ne soit pas qu'une convention.
set -euo pipefail
cd "$(dirname "$0")/.."
ENVFILE="${ENVFILE:-e2e/.env}"
[ -f "$ENVFILE" ] || { echo "ERREUR: $ENVFILE absent — copier e2e/.env.example et le compléter"; exit 1; }
set -a; . "$ENVFILE"; set +a

ECO_ENV="${ECO_ENV:-sandbox}"
case "$ECO_ENV" in
  sandbox)
    APP_URL="${APP_URL:-https://sandbox.ecobuilding.confinia.io}"
    API_URL="${API_URL:-https://sandbox.api.ecobuilding.confinia.io}"
    KC_REALM="${KC_REALM:-sandbox-ecobuilding}"
    KC_CONTAINER="${KC_CONTAINER:-ecobuilding-sandbox_sandbox-keycloak_1}"
    ;;
  staging)
    APP_URL="${APP_URL:-https://staging.ecobuilding.confinia.io}"
    API_URL="${API_URL:-https://staging.api.ecobuilding.confinia.io}"
    KC_REALM="${KC_REALM:-confinia}"
    KC_CONTAINER="${KC_CONTAINER:-ecobuilding-auth_keycloak_1}"
    ;;
  *)
    echo "ERREUR: ECO_ENV=$ECO_ENV refusé. Ce scénario paie avec une vraie carte de test :"
    echo "        il ne doit jouer que sur 'sandbox' ou 'staging'."
    exit 1 ;;
esac

# Une adresse fixe ne peut être inscrite qu'une fois : par défaut on en frappe
# une jetable par exécution, pour que le test soit rejouable sans ménage.
STAMP="$(date +%Y%m%d-%H%M%S)"
E2E_EMAIL="${E2E_EMAIL:-e2e-$STAMP@confinia.io}"
E2E_EMAIL_NOORG="${E2E_EMAIL_NOORG:-e2e-noorg-$STAMP@confinia.io}"
E2E_PASSWORD="${E2E_PASSWORD:-E2e-$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')}"
E2E_ORG="${E2E_ORG:-E2E}"
E2E_FIRSTNAME="${E2E_FIRSTNAME:-CI}"
E2E_LASTNAME="${E2E_LASTNAME:-Selenium}"
E2E_ADDRESS="${E2E_ADDRESS:-7 rue Pierre Corneille, Amiens}"
PDF_WAIT_MS="${PDF_WAIT_MS:-25000}"
PRO_WAIT_MS="${PRO_WAIT_MS:-65000}"

# Sélecteurs du checkout Polar : DOM externe, susceptible de bouger sans
# préavis. Ils sont en .env pour qu'une dérive se corrige en une ligne, sans
# toucher au projet Selenium. Les id React de cette page sont régénérés à
# chaque rendu (_R_imklubsnr5vlb_-form-item) : ne jamais s'y accrocher.
SEL_CO_EMAIL="${SEL_CO_EMAIL:-css=input[name=\"customer_email\"]}"
SEL_CO_NAME="${SEL_CO_NAME:-css=input[name=\"customer_name\"]}"
# Le bouton de paiement est visé par son TEXTE : la page porte plusieurs
# boutons submit/button (code promo, édition d'e-mail) et le premier
# button[type=submit] n'est pas « Subscribe now » — prouvé au WebDriver nu :
# même page, clic par texte → redirection ?pro=success en 9 s.
SEL_CO_SUBMIT="${SEL_CO_SUBMIT:-xpath=//button[contains(.,\"Subscribe\") or contains(.,\"abonner\") or contains(.,\"Payer\")]}"
SEL_STRIPE_FRAME="${SEL_STRIPE_FRAME:-css=iframe[title=\"Secure payment input frame\"]}"
SEL_CARD_NUMBER="${SEL_CARD_NUMBER:-css=#payment-numberInput}"
SEL_CARD_EXPIRY="${SEL_CARD_EXPIRY:-css=#payment-expiryInput}"
SEL_CARD_CVC="${SEL_CARD_CVC:-css=#payment-cvcInput}"

SELENIUM_IMAGE="${SELENIUM_IMAGE:-docker.io/selenium/standalone-chromium:4.47.0}"
NODE_IMAGE="${NODE_IMAGE:-docker.io/library/node:20-bookworm-slim}"
RUNNER_VERSION="${RUNNER_VERSION:-4.0.13}"
NET=eco-e2e
GRID=eco-e2e-selenium
OUT="e2e/results/$STAMP"
mkdir -p "$OUT" e2e/.run e2e/.npm-cache

CR="${CONTAINER_RUNTIME:-}"
[ -n "$CR" ] || CR=$(command -v podman || command -v docker) || true
[ -n "$CR" ] || { echo "ERREUR: ni podman ni docker — impossible de lancer le navigateur"; exit 1; }
echo "== environnement : $ECO_ENV ($APP_URL) · runtime : $(basename "$CR")"
echo "== compte de test : $E2E_EMAIL"

# --- 1. rendu du projet Selenium ---------------------------------------------
# Substitution par LISTE BLANCHE : les variables d'exécution de Selenium IDE
# (${kcScreen}, ${accountPanel}, posées par storeText) doivent survivre intactes.
export APP_URL API_URL KC_REALM E2E_EMAIL E2E_EMAIL_NOORG E2E_PASSWORD E2E_ORG \
       E2E_FIRSTNAME E2E_LASTNAME E2E_ADDRESS PDF_WAIT_MS PRO_WAIT_MS \
       SEL_CO_EMAIL SEL_CO_NAME SEL_CO_SUBMIT SEL_STRIPE_FRAME \
       SEL_CARD_NUMBER SEL_CARD_EXPIRY SEL_CARD_CVC
python3 - "$OUT" <<'PY'
import json, os, re, sys
src = "e2e/ecobuilding.side"
keys = ["APP_URL","API_URL","KC_REALM","E2E_EMAIL","E2E_EMAIL_NOORG","E2E_PASSWORD",
        "E2E_ORG","E2E_FIRSTNAME","E2E_LASTNAME","E2E_ADDRESS","PDF_WAIT_MS","PRO_WAIT_MS",
        "E2E_CARD_NUMBER","E2E_CARD_EXPIRY","E2E_CARD_CVC","E2E_CARD_NAME",
        "SEL_CO_EMAIL","SEL_CO_NAME","SEL_CO_SUBMIT","SEL_STRIPE_FRAME",
        "SEL_CARD_NUMBER","SEL_CARD_EXPIRY","SEL_CARD_CVC"]
missing = [k for k in keys if not os.environ.get(k)]
if missing:
    sys.exit("ERREUR: variables absentes de e2e/.env : " + ", ".join(missing))
text = open(src).read()
for k in keys:
    text = text.replace("${%s}" % k, json.dumps(os.environ[k])[1:-1])
json.loads(text)          # échoue tout de suite si une valeur casse le JSON
open("e2e/.run/ecobuilding.side", "w").write(text)
PY

# --- 2. navigateur ------------------------------------------------------------
# Réseau du navigateur. Jouer le scénario DEPUIS la machine qui héberge le site
# est un cas particulier : le nom public y résout vers l'adresse publique de la
# machine elle-même, et un conteneur sur un réseau bridge ne peut pas y revenir
# (pas de hairpin NAT — connexion refusée, y compris par la passerelle du
# bridge). En réseau « host », le conteneur emprunte le même chemin que la
# machine et cela fonctionne. Ailleurs (poste de l'opérateur), le bridge est
# parfaitement adapté et évite d'ouvrir un port sur la machine.
APP_HOST="${APP_URL#*://}"; APP_HOST="${APP_HOST%%/*}"
E2E_NETWORK="${E2E_NETWORK:-auto}"
if [ "$E2E_NETWORK" = auto ]; then
  APP_IP=$(getent hosts "$APP_HOST" 2>/dev/null | awk '{print $1; exit}')
  if [ -n "$APP_IP" ] && { ip -4 addr show 2>/dev/null || ifconfig 2>/dev/null; } | grep -qw "$APP_IP"; then
    E2E_NETWORK=host
  else
    E2E_NETWORK=bridge
  fi
fi
# Port du grid : dans la bande 13xxx d'ecobuilding (1PESI) et non le 4444 par
# défaut, parce qu'en réseau « host » il est réellement ouvert sur la machine.
GRID_PORT="${GRID_PORT:-13095}"
if [ "$E2E_NETWORK" = host ]; then
  NETARGS=(--network host); GRID_URL="http://localhost:$GRID_PORT"
else
  $CR network exists "$NET" 2>/dev/null || $CR network create "$NET" >/dev/null 2>&1 || true
  NETARGS=(--network "$NET"); GRID_URL="http://$GRID:$GRID_PORT"
fi
$CR rm -f "$GRID" >/dev/null 2>&1 || true
echo "== démarrage du navigateur ($SELENIUM_IMAGE, réseau $E2E_NETWORK, port $GRID_PORT)"
$CR run -d --name "$GRID" "${NETARGS[@]}" --shm-size=2g \
  -e SE_NODE_MAX_SESSIONS=1 -e SE_SESSION_REQUEST_TIMEOUT=120 \
  -e SE_NODE_SESSION_TIMEOUT="${SE_NODE_SESSION_TIMEOUT:-900}" \
  -e SE_START_VNC="${SE_START_VNC:-false}" \
  -e SE_OPTS="--port $GRID_PORT" \
  "$SELENIUM_IMAGE" >/dev/null
# Armé immédiatement après le démarrage du conteneur : une sortie en erreur
# entre ici et la fin ne doit pas laisser un navigateur orphelin sur la machine.
cleanup() {
  ec=$?
  $CR logs "$GRID" > "$OUT/selenium.log" 2>&1 || true
  $CR rm -f "$GRID" >/dev/null 2>&1 || true
  if declare -F kc_delete_user >/dev/null; then
    kc_delete_user "$E2E_EMAIL"; kc_delete_user "$E2E_EMAIL_NOORG"
  fi
  exit $ec
}
trap cleanup EXIT
for i in $(seq 1 60); do
  $CR exec "$GRID" curl -fsS -m 3 "http://localhost:$GRID_PORT/status" 2>/dev/null | grep -q '"ready": *true' && break
  sleep 2
done
echo "   navigateur prêt"

# side-runner abandonne si la session met plus de 30 s à s'ouvrir, et ce délai
# est CODÉ EN DUR dans @seleniumhq/side-runtime (webdriver.js) : impossible de
# l'allonger. Deux parades, parce qu'un premier démarrage de Chromium sur une
# machine chargée dépasse facilement 30 s :
#   1. headless — supprime tout le coût X11 ; les écrans traversés (formulaires
#      Keycloak, checkout Polar, panneau compte) sont du DOM, pas du WebGL ;
#   2. une session d'échauffement jetée avant de lancer la suite, pour que le
#      coût de démarrage à froid soit payé HORS de la fenêtre des 30 s.
# pageLoadStrategy=eager, en plus : le checkout Polar garde des connexions
# ouvertes et ne déclenche jamais l'événement load en headless — en stratégie
# normale, la navigation bloque jusqu'au timeout et la session du grid meurt
# d'inactivité pendant ce blocage (vécu : premier crash de la suite paiement).
# Locale française : le thème Keycloak suit la langue du navigateur, et nos
# utilisateurs sont français. Un Chromium par défaut joue le parcours en
# anglais, c'est-à-dire pas celui qui part en production.
CHROME_ARGS="${CHROME_ARGS:-[--lang=fr-FR,--accept-lang=fr-FR,--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--disable-extensions,--disable-search-engine-choice-screen$([ "${E2E_HEADLESS:-true}" = true ] && echo ",--headless=new")]}"
echo "   échauffement du navigateur"
$CR exec -e P="$GRID_PORT" "$GRID" bash -c 'SID=$(curl -s -m 150 -X POST "http://localhost:$P/session" \
    -H "Content-Type: application/json" \
    -d "{\"capabilities\":{\"alwaysMatch\":{\"browserName\":\"chrome\"}}}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get(\"value\",{}).get(\"sessionId\",\"\"))" 2>/dev/null)
  [ -n "$SID" ] && curl -s -X DELETE "http://localhost:$P/session/$SID" >/dev/null' >/dev/null 2>&1 || true

# --- 3. accès admin Keycloak (vérification e-mail + ménage) -------------------
# La boîte de réception du compte de test est un vrai mailbox externe : la CI ne
# peut pas l'ouvrir. L'ÉTAPE « clic sur le lien de vérification » est donc la
# seule du parcours qui soit simulée — via l'API admin. Elle est signalée comme
# telle dans le rapport : ne jamais la présenter comme un test du mail.
kcadm() {
  local cmd=(podman exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@")
  if [ -n "${E2E_KC_SSH:-}" ]; then ssh "$E2E_KC_SSH" "${cmd[*]}"; else "${cmd[@]}"; fi
}
kc_ready=0
if [ -n "${KC_ADMIN_PASSWORD:-}" ]; then
  kcadm config credentials --server http://localhost:8080/auth --realm master \
    --user "${KC_ADMIN_USER:-ci-admin}" --password "$KC_ADMIN_PASSWORD" >/dev/null 2>&1 && kc_ready=1
fi
[ "$kc_ready" = 1 ] || echo "   AVERTISSEMENT: pas d'accès admin Keycloak (KC_ADMIN_PASSWORD absent) — la vérification e-mail ne pourra pas être franchie"
kc_user_id() { [ "$kc_ready" = 1 ] || return 1
  kcadm get users -r "$KC_REALM" -q "email=$1" --fields id --format csv --noquotes 2>/dev/null | tr -d '\r' | head -1; }
kc_delete_user() { [ "$kc_ready" = 1 ] || return 0
  local id; id=$(kc_user_id "$1" || true); [ -n "$id" ] && kcadm delete "users/$id" -r "$KC_REALM" >/dev/null 2>&1 || true; }

# --- 4. suites ----------------------------------------------------------------
side() {   # side <regex-de-suite> <étiquette>
  echo "== suite : $2 (journal : $OUT/suite-$1.log)"
  $CR run --rm "${NETARGS[@]}" \
    -v "$PWD/e2e:/e2e:z" -v "$PWD/e2e/.npm-cache:/root/.npm:z" -w /e2e \
    -e npm_config_cache=/root/.npm \
    "$NODE_IMAGE" npx -y "selenium-side-runner@$RUNNER_VERSION" \
      --server "$GRID_URL" --base-url "$APP_URL" \
      -c "browserName=chrome pageLoadStrategy=eager goog:chromeOptions.args=$CHROME_ARGS" --filter "$1" \
      --retries "${E2E_RETRIES:-0}" \
      --timeout 30000 --jest-timeout 900000 \
      --output-directory "/e2e/results/$STAMP" \
      --screenshot-failure-directory "/e2e/results/$STAMP/screenshots" \
      ${E2E_DEBUG:+--debug} \
      .run/ecobuilding.side 2>&1 | tee "$OUT/suite-$1.log" | grep -E "Running|Finished|✓|✕|●|Error|error" || return 1
  # tee absorbe le code de retour du runner : le verdict est relu dans le JSON.
  python3 - "$OUT" <<'PYV'
import glob, json, sys
files = sorted(glob.glob(sys.argv[1] + "/results-*.json"))
d = json.load(open(files[-1]))
sys.exit(0 if d.get("numFailedTests") == 0 and d.get("numPassedTests", 0) > 0 else 1)
PYV
}

rc_signup=0; rc_pay=0; pay_ran=0
side "inscription" "01 inscription + 06 organisation obligatoire" || rc_signup=$?

if [ "$rc_signup" = 0 ] && [ "$kc_ready" = 1 ]; then
  UID_=$(kc_user_id "$E2E_EMAIL" || true)
  if [ -n "$UID_" ]; then
    # Avant de franchir le mur, vérifier qu'il existait : si le compte était
    # déjà « e-mail vérifié », c'est que le realm n'exige plus la vérification —
    # une régression de sécurité que ce test doit refuser de masquer.
    VERIF=$(kcadm get "users/$UID_" -r "$KC_REALM" --fields emailVerified 2>/dev/null | tr -d ' \r\n')
    case "$VERIF" in
      *true*) echo "ERREUR: $E2E_EMAIL est déjà vérifié à l'inscription — le realm n'exige plus la vérification d'e-mail (verifyEmail)"; rc_signup=1 ;;
      *) kcadm update "users/$UID_" -r "$KC_REALM" -s emailVerified=true >/dev/null
         echo "== compte créé, vérification e-mail EXIGÉE puis franchie par l'API admin (étape SIMULÉE, cf. rapport)" ;;
    esac
  else
    echo "ERREUR: le compte $E2E_EMAIL n'existe pas dans le realm — l'inscription n'a pas abouti"
    rc_signup=1
  fi
fi

[ "$rc_signup" = 0 ] && { pay_ran=1; side "paiement" "02-05 connexion → fiche → paiement → Pro" || rc_pay=$?; }

# --- 5. rapport depuis la plateforme de paiement ------------------------------
# Le compte de test est supprimé à la sortie : interroger Polar AVANT le ménage.
rc_polar=0
python3 e2e/polar_report.py \
  --out "$OUT" --env "$ECO_ENV" --app-url "$APP_URL" --api-url "$API_URL" \
  --email "$E2E_EMAIL" --signup-rc "$rc_signup" \
  --payment-rc "$([ "$pay_ran" = 1 ] && echo "$rc_pay" || echo -1)" || rc_polar=$?

echo
echo "== résultats : $OUT (rapport : $OUT/report.md)"
if [ "$rc_signup" = 0 ] && [ "$pay_ran" = 1 ] && [ "$rc_pay" = 0 ] && [ "$rc_polar" = 0 ]; then
  echo "== SUCCÈS"
else
  [ "$pay_ran" = 1 ] && P="$rc_pay" || P="non jouée"
  echo "== ÉCHEC (inscription=$rc_signup paiement=$P polar=$rc_polar)"
  exit 1
fi
