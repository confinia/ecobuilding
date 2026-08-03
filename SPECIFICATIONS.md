# SPECIFICATIONS — EcoBuilding SaaS

Main expectations of the EcoBuilding service. Companion docs:
[DEV.md](DEV.md) (architecture/ops) · [BUSINESS.md](BUSINESS.md) (strategy) ·
[RULES.md](RULES.md) (working rules) · [TEST_SUBSCRIPTION.md](TEST_SUBSCRIPTION.md) /
[TEST_POLAR.md](TEST_POLAR.md) (validation) · [LAUNCH.md](LAUNCH.md) (communication).

## 1. Vision

Turn French open building data into a **self-serve, autonomous SaaS**: the
target operating mode is *« 6 months away, money observable from a distance »* —
every acquisition, delivery, payment and monitoring mechanism must run without
human presence. Model: **open-core** — a free open-data commons version
(ecobuilding.confinia.io) and a commercial deployment on its own domain
(candidate: ecobuilding.io, #33) sharing one codebase.

## 2. Personas & expectations

| Persona | Expectation | Offer |
|---|---|---|
| Visitor / citizen | Understand a building's energy class, rental-ban deadline, risks in seconds | Free 3D map, no account |
| **Diagnostiqueur / pre-sale pro** (primary buyer) | Normalized pre-visit fiche in one click; complete building history; small unit price, volume use | PDF fiche (free beta → pro quota N/day), later full history & sources |
| Developer / proptech | One key, one call, one normalized JSON, docs, uptime | Public API `/api/v1` (free beta → metered keys, ~10 free req/day then key) |
| Enterprise (portal, insurer, agency network) | SLA, white-label map, custom fields — annual contract | Enterprise tier from 10k€/an (the only pre-incorporation transactable tier) |

## 3. Functional scope — CURRENT (v1, in production)

- **3D map of France** (MapLibre GL): buildings colored by DPE class from BDNB
  vector tiles, real heights; DPE legend; 2D/3D toggle, zoom/pitch controls.
- **Address search** (BAN autocomplete: cities → fly-to, streets, addresses →
  building record), **GPS locate** (reverse geocode → building), **click any
  building** → info panel (DPE + rental-ban countdown per loi Climat &
  Résilience G/F/E = 2025/2028/2034, year, materials, clay risk, zone risks +
  Géorisques link, solar potential).
- **Shareable state**: camera in URL hash + selected building in `?b=`;
  default landing = showcase building (244 Rue de Rivoli, DPE G).
- **Normalized PDF fiche** per building (weasyprint): étiquettes énergie &
  climat (A→G scales), structured sections, sources & legal disclaimer —
  free during beta, metered by `ecobuilding_reports_total`.
- **Public API v1** (`/api/v1/docs`, OpenAPI): healthz, suggest, lookup,
  reverse, buildings/{id}, report/{id}.pdf, events, leads. Versioning: breaking
  changes → `/v2`, `/v1` stays.
- **Offer page** (`/offres.html`): Découverte (free) / API Pro 99€ (waitlist) /
  Enterprise & white-label from 10k€/an — request-access lead form (persisted,
  promote-proof, metric).
- **Observability**: OpenTelemetry → shared Prometheus/Grafana (`/grafana`),
  usage events (page_view, search, lookup, building_click, geolocate,
  heartbeat), visitor countries (GeoIP country-only), per-container metrics.

## 4. Functional scope — PLANNED (tracked issues)

- **Accounts**: Keycloak IdP, sign-up/sign-in in frontend, mandatory
  **organization (tenant)** at registration, org claim in JWT, auto-provisioned
  free key, `/v1/me` (#36, #27).
- **Pro plan via Polar.sh** (MoR): checkout → webhook → pro tier — quota'd PDF
  fiches per day, higher API limits; sandbox first; real money only post-10k€
  rule (#35).
- **Metering**: ~10 anonymous req/day then key required (#27).
- **SEO per-address pages** — the structural acquisition engine (server-rendered
  `/adresse/{ban_id}`, sitemaps, commune-by-commune with DPE-coverage gate).
- **Data depth**: full per-building change history & sources (ADEME DPE join).
- **Self-hosted BDNB** for SLA independence (#28); GeoJSON exports (#24);
  cooling data layer (#23); Panoramax imagery (#22); sovereign-stack page (#25).

## 5. Non-functional expectations

- **Zero-downtime**: two complete blue/green stacks; deploys touch only the
  candidate; production switches only via `promote.sh` after manual validation
  on staging.ecobuilding.confinia.io; instant rollback (previous stack keeps
  running); router config applied by graceful reload.
- **Autonomy** (departure-ready checklist): self-serve payments + key
  auto-provisioning; lead auto-response; alerting (push, not dashboards);
  reboot survival (linger ✓); upstream independence (BDNB self-host);
  SEO pages indexed. Money must arrive and be observable without action.
- **Privacy**: no cookies, no accounts required for the free tier, IP never
  stored (in-memory country-only GeoIP), anonymous usage counters.
- **Security/honesty**: scanner paths blocked+logged at the edge; secrets out
  of git; generated documents must NEVER imitate official ones (DPE/ERP) —
  familiar visual vocabulary yes, lookalike no, disclaimer always.
- **Cost discipline**: keyless/open upstreams, client-side rendering, no
  per-request map fees; upstream quotas guarded by TTL cache.
- **Quality gate**: every change = GitHub issue → PR → CI (pytest; suites for
  unimplemented flows are SKIPPED, never faked) → staging validation → promote.

## 6. Business rules (invariants)

1. **No company creation below a 10k€ invoice** — until then: free beta,
   lead capture, 10k€-scale deals only (white-label, data contracts).
2. **Payment rail**: Polar.sh (Merchant of Record — EU VAT handled).
3. **Side-project constraint**: no revenue model requiring meetings or
   physical presence; everything self-serve.
4. **Under-promise communication**: announce only what already works.
5. **Data licensing**: sources are Licence Ouverte (BDNB/CSTB, BAN,
   Géorisques) — attribution displayed everywhere, including PDFs; produced
   works sellable; no proprietary moat claimed on open data itself.

## 7. Success metrics

Usage: page views, lookups, building clicks, fiche downloads, countries.
Demand: leads (enterprise vs waitlist), key signups, fiche quota hits.
Business: first ≥10k€ deal (triggers incorporation + payment go-live);
then MRR via Polar with zero-touch delivery.
