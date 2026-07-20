# EcoBuilding — DEV notes

Working rules (2026-07-20):
- **Dev code lives in this directory**, which is the local git repo
  (GitHub: `confinia/ecobuilding`, private — BUSINESS.md ships with the code).
- **Dockerfile + docker-compose.yml are the deployment contract**: everything
  runs with `podman-compose` on the VM (and `docker compose` locally).

## Architecture (3 caddy tiers, 2 independent app stacks)

```
Internet ──▶ MAIN edge caddy (confinia_caddy_1, owns 80/443, TLS, volatile —
             owned by the confinia project; our stanza = 2 lines, forwards
             both hostnames to the router)
                 │
                 ▼ 127.0.0.1:8020
             ROUTER caddy (caddy_server/, project ecobuilding-edge, host net
             loopback) — maps hostnames to stacks; PROMOTE = swap one config
             file (Caddyfile.blue|green) + graceful reload
                 ├── ecobuilding.confinia.io      ──▶ ACTIVE stack
                 └── next.ecobuilding.confinia.io ──▶ CANDIDATE stack
                        │
                        ▼ 127.0.0.1:8021 (blue) / 8022 (green)
             STACK caddy (stack_caddy/Caddyfile, single published port of the
             stack) ── /api/* ─▶ api:8000 ; /grafana* ─▶ grafana:3000 ;
                       /      ─▶ frontend:80        (compose network names)

Each stack (ecobuilding-blue, ecobuilding-green) is COMPLETE & independent:
  caddy + api + frontend + otel-collector + prometheus + grafana +
  podman-exporter, own volumes (per-project prefix), own private network.
  api ──OTLP/http──▶ otel-collector ──:8889──▶ prometheus ◀── podman-exporter
                                                    ▲
                                               grafana (datasource)
```

- **Host**: OVH dedicated VM, `ssh confinia` (= `debian@cka-ovh-dedicated-01`,
  ns3188074.ip-5-135-143.eu / 5.135.143.93). Podman 5.4 + podman-compose 1.3, rootless.
- **Deploy dir**: `~/projects/ecobuilding` on the VM (rsync'd copy of this repo).
- **DNS**: wildcard `*.confinia.io` → VM, so `ecobuilding.confinia.io` already resolves.
- **Edge**: we do NOT run our own :443. The confinia project's caddy is the VM's
  shared edge; each project drops a `*.caddy` vhost into
  `~/projects/confinia/deploy/sites/` and calls
  `~/projects/confinia/deploy/deploy-edge.sh` (validate + graceful reload).
  Our vhost source of truth: [deploy/edge/ecobuilding.caddy](deploy/edge/ecobuilding.caddy).
  ⚠ **Incident 2026-07-20**: the confinia project's own deploy sync owns
  `deploy/sites/` and DELETES foreign files — our vhost was wiped minutes after
  installation (before the TLS cert was issued). Fix: the vhost is also copied
  into the local `confinia-core` checkout (`~/project/confinia/deploy/sites/`),
  so the owning project's syncs now preserve it. deploy.sh does both copies.

## Blue/green: two complete independent stacks, manual validation gate

Same `docker-compose.yml`, two compose project names:

| Stack | Project | Entry port | Role |
|---|---|---|---|
| blue | `ecobuilding-blue` | 127.0.0.1:8021 | active OR candidate |
| green | `ecobuilding-green` | 127.0.0.1:8022 | the other one |

Which stack is production is decided ONLY by the router config
(`caddy_server/Caddyfile` = copy of `Caddyfile.blue` or `Caddyfile.green`);
state recorded in `deploy/.active` on the VM (not in git, survives rsync).

- `./deploy/deploy.sh` → builds fresh images, **fully recreates the CANDIDATE
  stack only** (the active one is never touched), ensures router + main-edge
  stanza, hard health gate on the candidate's local port.
- **You validate on https://next.ecobuilding.confinia.io**, then
  `./deploy/promote.sh` → health-checks the candidate, copies the matching
  router Caddyfile, graceful reload. **The previous stack keeps running.**
- `./deploy/rollback.sh` → same flip, back — instant (the old stack never
  stopped), with a health check on the target.
- No automatic failover from prod to candidate: an unvalidated version must
  never receive production traffic.

## Ports (127.0.0.1 on the VM — never public)

| Service | Port |
|---|---|
| router (ecobuilding-edge) | 8020 |
| blue stack entry caddy | 8021 |
| green stack entry caddy | 8022 |
| everything else (api, frontend, grafana, prometheus, otel, exporter) | stack-internal network only |

Taken by other projects (do not reuse): 8000/8001 (confinia api), 3000
(confinia grafana), 3001 (orbit-poc grafana), 9081/9082 (overwatch), 5432 (pg),
9966 (maplibre-dev), 9100 (node-exporter, host).

## API (a product in its own right)

- **Versioning**: everything under `/v1`; breaking changes → `/v2`, `/v1` stays.
  The public mount is `/api` (edge strips it; FastAPI `root_path="/api"`).
- **Docs**: OpenAPI/Swagger at `https://ecobuilding.confinia.io/api/v1/docs`
  (+ `/api/v1/redoc`, machine-readable `/api/v1/openapi.json`).
- **Endpoints v1**: `GET /v1/healthz`, `GET /v1/suggest?q=` (BAN autocomplete),
  `GET /v1/lookup?q=|ban_id=[&lon=&lat=]` (normalized building record),
  `POST /v1/events` (frontend usage beacon).
- **Data chain** (all keyless, Licence Ouverte):
  BAN geocode → `id` (ex `80021_6370_00007`) → BDNB
  `donnees/batiment_groupe_complet/adresse?cle_interop_adr=eq.<id>` (fast, indexed)
  → Géorisques `resultats_rapport_risque?latlon=lon,lat`.
  ⚠ Do NOT filter BDNB by `cle_interop_adr_principale_ban` on the base endpoint:
  statement timeout (unindexed). BDNB free tier: 10k calls/month → add caching
  before any traffic push.
- Rental-ban calendar hardcoded in `api/app/main.py` (`DPE_BAN_DATES`) — recheck
  legislation before commercial use (pending "Relance logement" bill).

## Observability (OpenTelemetry)

- API: OTel SDK → OTLP/http → `otel-collector` → Prometheus exporter :8889 →
  Prometheus → Grafana. Custom metrics: `ecobuilding_api_requests_total{route,method,status}`,
  `ecobuilding_lookups_total{status}`, `ecobuilding_frontend_events_total{event}`.
- Frontend usage: anonymous beacon (`navigator.sendBeacon` → `POST /v1/events`,
  no cookies, no IP stored) counted by the API into OTel. Events: `page_view`,
  `search`, `lookup`.
- Podman services: `prometheus-podman-exporter` reading the **rootless user
  socket** (`systemctl --user enable --now podman.socket` — done by deploy.sh).
- Grafana: dedicated instance (not confinia's), subpath mode
  (`GF_SERVER_ROOT_URL=…/grafana/`, `GF_SERVER_SERVE_FROM_SUB_PATH=true`),
  admin password auto-generated into `deploy/secrets.env` (gitignored) on first
  deploy, signups off. Dashboard provisioned from
  `monitoring/grafana/dashboards/ecobuilding.json`.

## Frontend

- MapLibre GL JS 4.x (CDN), basemap **OpenFreeMap `liberty`** (free vector
  tiles, no key, no quota) + `fill-extrusion` 3D buildings from the basemap's
  OpenMapTiles `building` layer.
- Next iterations: BDNB vector tiles overlay
  (`https://api.bdnb.io/v1/bdnb/tuiles/batiment_groupe/{z}/{x}/{y}.pbf`, probed OK)
  to color buildings by DPE class; photosphere layer (see maplibre-gl-photosphere
  project already on the VM).

## Workflows

```sh
# local dev (docker or podman)
docker compose up --build          # then http://localhost:8011 / :8010/v1/docs
                                   # (create deploy/secrets.env from the .example first)

# 1. deploy current code to the CANDIDATE stack — prod untouched
./deploy/deploy.sh                 # -> https://next.ecobuilding.confinia.io

# 2. validate manually on next., then flip production to the candidate
./deploy/promote.sh                # -> https://ecobuilding.confinia.io

# oops? (previous stack never stopped — instant)
./deploy/rollback.sh

# logs on the VM (per stack)
ssh confinia 'cd ~/projects/ecobuilding && podman logs -f ecobuilding-green_api_1'

# edge access log
ssh confinia 'podman exec confinia_caddy_1 tail -f /data/logs/ecobuilding-access.log'
```

Note: the ssh alias `confinia` (`~/.ssh/config`) forwards local **9976** →
VM 9966 (maplibre-dev); changed from 9966→9976 on 2026-07-20 to avoid clashing
with another session's forward.

## Decisions

| Date | Decision |
|---|---|
| 2026-07-20 | Shared-edge pattern (vhost drop-in) instead of a second caddy — ports 80/443 already owned by confinia_caddy_1 |
| 2026-07-20 | BDNB `/adresse` endpoint keyed by `cle_interop_adr` (indexed) as the lookup spine |
| 2026-07-20 | Keyless-only data sources for the MVP (BAN, BDNB, Géorisques, OpenFreeMap) |
| 2026-07-20 | Dedicated per-project monitoring stack (VM convention, cf. orbit-poc), Grafana on 3002 |
| 2026-07-20 | GitHub repo private (BUSINESS.md in-repo); deploys via rsync, not git-pull |
