#!/bin/bash
# EcoBuilding — CI failure notification we control (rule 20).
# GitHub's own notifications go to the owner's personal inbox, which the
# session cannot read; contact@confinia.io is a redirection, not a mailbox.
# So the pipeline sends its own mail: To contact@ (the operator reads it) and
# Cc alert@ (a real OVH mailbox, readable with deploy/check-mail.sh).
#
# Called from a workflow step with `if: failure()`:
#   ./deploy/ci-notify.sh "<workflow>" "<run url>" "<ref>"
set -eu
cd "$(dirname "$0")/.."
. deploy/secrets.env
WF="${1:-unknown}"; URL="${2:-}"; REF="${3:-}"

[ -n "${SMTP_PASSWORD:-}" ] || { echo "ci-notify: no SMTP creds, skipping"; exit 0; }

WF="$WF" URL="$URL" REF="$REF" python3 <<'PY'
import os, smtplib, ssl
from email.message import EmailMessage

env = {}
for line in open("deploy/secrets.env"):
    if "=" in line and not line.startswith("#"):
        k, _, v = line.strip().partition("=")
        env[k] = v

m = EmailMessage()
m["From"] = env.get("SMTP_FROM", "alert@confinia.io")
m["To"] = env.get("ALERT_RCPT", "contact@confinia.io")
m["Cc"] = env.get("SMTP_USER", "alert@confinia.io")   # readable mailbox
m["Subject"] = f"[EcoBuilding CI] ECHEC: {os.environ['WF']} ({os.environ['REF']})"
m.set_content(
    f"Le workflow {os.environ['WF']} a echoue.\n\n"
    f"Ref : {os.environ['REF']}\nRun : {os.environ['URL']}\n\n"
    "Logs : gh run view <id> --log-failed\n")
with smtplib.SMTP(env["SMTP_HOST"], int(env.get("SMTP_PORT", "587")), timeout=20) as s:
    s.starttls(context=ssl.create_default_context())
    s.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
    s.send_message(m)
print("ci-notify: failure mail sent")
PY
