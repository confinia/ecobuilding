#!/bin/bash
# EcoBuilding #128 — Keycloak realm email, as code. Configures SMTP on the
# `confinia` realm and enables the "verify email" flow so every new
# registration gets a confirmation mail from alert@confinia.io.
# Idempotent: kcadm `update` overwrites the same fields on every run.
# Run ON the VM (called by deploy.sh; safe to run standalone). Reads SMTP_*
# from deploy/secrets.env; exits quietly if they are not provisioned yet.
set -eu
cd "$(dirname "$0")/.."
. deploy/secrets.env

if [ -z "${SMTP_HOST:-}" ] || [ -z "${SMTP_PASSWORD:-}" ]; then
  echo "kc-smtp: SMTP_* not in deploy/secrets.env — skipping (realm unchanged)"
  exit 0
fi

KC=ecobuilding-auth_keycloak_1
KCADM="podman exec -i $KC /opt/keycloak/bin/kcadm.sh"

$KCADM config credentials --server http://localhost:8080/auth \
  --realm master --user "${KC_BOOTSTRAP_ADMIN_USERNAME:-admin}" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null

# Port 587 = STARTTLS (starttls=true, ssl=false); 465 would be the inverse.
if [ "${SMTP_PORT:-587}" = "465" ]; then TLS=false SSL=true; else TLS=true SSL=false; fi

$KCADM update realms/confinia \
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

echo "kc-smtp: realm confinia SMTP + verifyEmail configured (from ${SMTP_FROM:-$SMTP_USER})"
