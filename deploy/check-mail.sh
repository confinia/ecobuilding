#!/bin/bash
# EcoBuilding — read the ops mailbox (rule 20). Same OVH account as the SMTP
# sender, over IMAP: lists the most recent messages so a CI run, an alert or a
# bounce can be verified from the terminal instead of assumed.
#
#   ssh ecobuilding 'cd ~/projects/ecobuilding && ./deploy/check-mail.sh [N]'
#
# Reads SMTP_* from deploy/secrets.env (never takes creds on the command line).
set -eu
cd "$(dirname "$0")/.."
. deploy/secrets.env
N="${1:-10}"

IMAP_HOST="${IMAP_HOST:-${SMTP_HOST:-ssl0.ovh.net}}" \
IMAP_USER="${SMTP_USER:?SMTP_USER missing}" \
IMAP_PASSWORD="${SMTP_PASSWORD:?SMTP_PASSWORD missing}" \
N="$N" python3 <<'PY'
import email, imaplib, os
from email.header import decode_header, make_header

host = os.environ["IMAP_HOST"]
with imaplib.IMAP4_SSL(host, 993) as m:
    m.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    m.select("INBOX")
    typ, data = m.search(None, "ALL")
    ids = data[0].split()
    if not ids:
        print("mailbox empty")
        raise SystemExit(0)
    for i in ids[-int(os.environ["N"]):][::-1]:
        typ, d = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        msg = email.message_from_bytes(d[0][1])
        h = lambda k: str(make_header(decode_header(msg.get(k, "")))).strip()
        print(f"- {h('Date')[:31]:31} | {h('From')[:34]:34} | {h('Subject')[:70]}")
PY
