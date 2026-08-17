#!/bin/bash
# EcoBuilding #128 — Keycloak realm email, as code. Configures SMTP on a realm
# and enables the "verify email" flow so registrations and PASSWORD RESETS can
# actually send mail. Idempotent: kcadm `update` overwrites the same fields.
# Run ON the VM (called by stack-up.sh and sandbox.sh; safe standalone).
#
# Defaults to production; the sandbox stack calls it with its own realm:
#   REALM=sandbox-ecobuilding KC_CONTAINER=ecobuilding-sandbox_sandbox-keycloak_1 \
#   SECRETS=sandbox_stack/secrets.env ADMIN_USER=ci-admin ./deploy/kc-smtp.sh
set -eu
cd "$(dirname "$0")/.."
REALM="${REALM:-confinia}"
SECRETS="${SECRETS:-deploy/secrets.env}"
. "$SECRETS"

if [ -z "${SMTP_HOST:-}" ] || [ -z "${SMTP_PASSWORD:-}" ]; then
  echo "kc-smtp: SMTP_* not in $SECRETS — skipping (realm $REALM unchanged)"
  exit 0
fi

# Pre-flight: never enable verifyEmail with creds the relay rejects — that
# would strand new registrations behind a mail that can't be sent (#128).
if ! python3 - <<'PY'
import os, smtplib, ssl, sys
env = {}
for line in open(os.environ.get("SECRETS", "deploy/secrets.env")):
    if "=" in line and not line.startswith("#"):
        k, _, v = line.strip().partition("=")
        env[k] = v
try:
    port = int(env.get("SMTP_PORT", "587"))
    if port == 465:
        s = smtplib.SMTP_SSL(env["SMTP_HOST"], port, timeout=20)
    else:
        s = smtplib.SMTP(env["SMTP_HOST"], port, timeout=20)
        s.starttls(context=ssl.create_default_context())
    s.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
    s.quit()
except Exception as e:
    print(f"kc-smtp: SMTP pre-flight failed ({e})", file=sys.stderr)
    sys.exit(1)
PY
then
  echo "kc-smtp: relay rejects the creds — skipping (realm unchanged, fix SMTP_PASSWORD then re-run)"
  exit 0
fi

KC="${KC_CONTAINER:-ecobuilding-auth_keycloak_1}"
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

$KCADM config credentials --server http://localhost:8080/auth \
  --realm master --user "${ADMIN_USER:-${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

# Port 587 = STARTTLS (starttls=true, ssl=false); 465 would be the inverse.
if [ "${SMTP_PORT:-587}" = "465" ]; then TLS=false SSL=true; else TLS=true SSL=false; fi

$KCADM update "realms/$REALM" \
  -s "smtpServer.host=$SMTP_HOST" \
  -s "smtpServer.port=${SMTP_PORT:-587}" \
  -s "smtpServer.starttls=$TLS" \
  -s "smtpServer.ssl=$SSL" \
  -s "smtpServer.auth=true" \
  -s "smtpServer.user=$SMTP_USER" \
  -s "smtpServer.password=$SMTP_PASSWORD" \
  -s "smtpServer.from=${SMTP_FROM:-$SMTP_USER}" \
  -s "smtpServer.fromDisplayName=EcoBuilding" \
  -s "smtpServer.replyTo=${ALERT_RCPT:-}" \
  -s verifyEmail=true

echo "kc-smtp: realm $REALM SMTP + verifyEmail configured (from ${SMTP_FROM:-$SMTP_USER})"
