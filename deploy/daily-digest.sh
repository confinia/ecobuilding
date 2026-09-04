#!/bin/bash
# Wrapper cron du rapport quotidien (#393) : charge les identifiants SMTP puis
# lance le générateur. Planifié à 08:00 Europe/Paris (voir l'entrée crontab de
# l'utilisateur ecobuilding). Journalise dans ~/daily-digest.log.
set -euo pipefail
# cron n'ouvre pas de session : sans cela, podman rootless ne trouve pas son
# socket. Nécessite `loginctl enable-linger ecobuilding` (fait une fois).
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
cd "$(dirname "$0")/.."
set -a
. deploy/secrets.env
set +a
exec python3 deploy/daily-digest.py
