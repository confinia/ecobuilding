#!/bin/bash
# EcoBuilding — BREAK-GLASS workstation promote (rule 14: the normal path is
# the Actions 'promote' workflow). Runs deploy/promote-up.sh on the VM.
set -eu

HOST=ecobuilding

ssh "$HOST" 'cd ~/projects/ecobuilding && ./deploy/promote-up.sh'

echo "== public smoke (production)"
sleep 2
curl -fsS -m 10 https://ecobuilding.confinia.io/api/v1/healthz && echo
curl -fsS -m 10 -o /dev/null -w "prod frontend: %{http_code}\n" https://ecobuilding.confinia.io/
echo "OK — https://ecobuilding.confinia.io"
