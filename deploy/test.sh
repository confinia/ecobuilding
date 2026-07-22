#!/bin/bash
# EcoBuilding — run the test suite exactly as CI would, in a clean container.
# Use as a manual gate before promoting, or wire as a git pre-push hook until
# GitHub Actions is activated (see SECURITY.md §3). Runs on the VM (podman) or
# any host with podman/docker.
#
#   ./deploy/test.sh              # local (needs podman)
#   ssh confinia 'cd ~/projects/ecobuilding && ./deploy/test.sh'
set -eu
cd "$(dirname "$0")/../api"

ENGINE=$(command -v podman || command -v docker)
"$ENGINE" run --rm -v "$PWD":/w -w /w -e OTEL_METRIC_EXPORT_INTERVAL=600000 \
  docker.io/library/python:3.12-slim bash -c '
    apt-get update -qq >/dev/null &&
    apt-get install -y -qq --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core >/dev/null 2>&1 &&
    pip install -q -r requirements.txt pytest 2>/dev/null &&
    python -m pytest tests -v --tb=short'
