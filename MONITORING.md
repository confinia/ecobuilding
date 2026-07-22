# MONITORING — what is measured, and how

Observability of the EcoBuilding SaaS. Goal (SPECIFICATIONS.md §1): the service
must be observable **from a distance, without action** — usage, demand, health.

## Access

- **Dashboard**: https://ecobuilding.confinia.io/grafana — dashboard
  *« EcoBuilding — usage & services »* (user `admin`, password on the VM in
  `~/projects/ecobuilding/deploy/secrets.env`).
- Grafana serves the **shared monitoring stack** — dashboards and history
  survive blue/green promotes (see Architecture below).

## What is monitored

### 1. Product usage (anonymous — no cookies, no IP stored)

| Metric | Labels | Meaning |
|---|---|---|
| `ecobuilding_frontend_events_total` | `event`, `country` | Frontend beacons: `page_view`, `search`, `lookup`, `building_click`, `geolocate`, `heartbeat` (1/min per visible tab), `showcase_default`. Country = ISO code resolved in memory from IP (dbip-country-lite), IP never persisted. |
| `ecobuilding_lookups_total` | `status` | Building lookups: `ok`, `no_building`, `address_not_found`, `by_id`, `reverse_not_found` |
| `ecobuilding_reports_total` | `has_dpe` | Normalized PDF fiches generated — the demand counter for the future pro plan |
| `ecobuilding_leads_total` | `kind` | Offer-page access requests (`enterprise` / `waitlist`) — the 10k€-deal funnel |

Derived panels: page views & lookups (24h stats), events/min by type,
**Browsing now** ≈ `increase(heartbeat[2m])/2`, **visitors by country** (24h),
page views/min by country.

### 2. API health & behavior

| Metric | Labels | Meaning |
|---|---|---|
| `ecobuilding_api_requests_total` | `route`, `method`, `status` | Every API request (also surfaces scanner probes as 4xx routes) |
| `ecobuilding_upstream_cache_total` | `result` | TTL-cache hits/misses in front of BDNB/BAN/Géorisques — guards the BDNB 10k calls/month free tier |
| OTel FastAPI/httpx instrumentation | — | Request durations, upstream call spans (traces currently dropped at the collector; metrics kept) |

### 3. Infrastructure

| Source | What |
|---|---|
| `prometheus-podman-exporter` (rootless socket) | Per-container CPU, memory, state for ALL podman containers on the VM |
| Prometheus self-scrape + `up` | Scrape-target health (blue collector, green collector, podman, self) |
| Platform layer (confinia/platform repo) | node_exporter (VM CPU/RAM/disk) + **blackbox probes of the public endpoints** (availability, latency, TLS expiry) — visible in the platform Grafana (`grafana.confinia.io`) |

### 4. Edge logs (not metrics)

- **Router access log** (JSON, stdout): every request incl. **blocked scanner
  probes (403)** — `podman logs ecobuilding-edge_caddy_1 | grep '"status":403'`
- Stack caddies + API logs: `podman logs ecobuilding-{blue,green}_{caddy,api}_1`
- Leads raw data: `~/projects/ecobuilding/data/leads/leads.jsonl` on the VM.

## How it works (architecture)

```
frontend beacon ──POST /v1/events──▶ api (adds country label)
api ──OTLP/http──▶ otel-collector (one per stack, app-local buffer)
                      │ blue publishes 127.0.0.1:8891, green :8892
                      ▼
        SHARED prometheus (host net, 127.0.0.1:9095, retention 180d)
        ├── scrapes both stacks with a `stack` label → counters aggregate
        │   across blue/green: PROMOTES NEVER RESET THE DASHBOARDS
        ├── scrapes podman-exporter (127.0.0.1:9882)
        ▼
        SHARED grafana (host net :3002) ◀── /grafana on both public hosts
```

Compose project `ecobuilding-monitoring` (`monitoring_stack/`), deliberately
outside the blue/green pair. Dashboard provisioned from
`monitoring/grafana/dashboards/ecobuilding.json`; shared-stack provisioning in
`monitoring/grafana-shared/`; scrape config in `monitoring/prometheus-shared.yml`.

## Privacy invariants

No cookies. No accounts required. IP is used only in memory to derive a
country code; it is never stored, logged by the API, nor exported. Events are
counters, not user profiles.

## Known gaps (autonomy checklist)

- **No push alerting yet** — dashboards require looking. Planned: Grafana
  alert rules (downtime, error rate, lead arrival) → e-mail; the platform
  blackbox probes already detect public-endpoint downtime.
- Traces are dropped (debug exporter only); revisit if debugging needs grow.
- Old per-stack Prometheus volumes hold pre-2026-07-21 history (not merged
  into the shared TSDB).
