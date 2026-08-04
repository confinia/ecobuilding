# EcoBuilding — Issue tracker

Living status of every open (and recently shipped) GitHub issue, updated each
working session (rule 15). Lifecycle: **filed → PR open → merged (on staging) →
promoted (production) → closed**. Environments (rule 12):
[production](https://ecobuilding.confinia.io) ·
[staging](https://staging.ecobuilding.confinia.io) ·
[sandbox](https://sandbox.ecobuilding.confinia.io).

Last updated: 2026-08-04.

## Environment state

| Environment | Runs | Note |
|---|---|---|
| [Production](https://ecobuilding.confinia.io) | `main` as last promoted ([#110](https://github.com/confinia/ecobuilding/pull/110)) | Docs-only merges since ([#116](https://github.com/confinia/ecobuilding/pull/116)) need no deploy |
| [Staging](https://staging.ecobuilding.confinia.io) | — | **Routing broken**: Tier-1 platform edge still routes `next.`; fix = PR to `confinia/platform` (STACK_ecobuilding.md §10) |
| [Sandbox](https://sandbox.ecobuilding.confinia.io) | `feat/building-marker` ([#114](https://github.com/confinia/ecobuilding/pull/114)) | Marker validated there 2026-08-03 |

## Open issues

| Issue | Status | Next step |
|---|---|---|
| [#119](https://github.com/confinia/ecobuilding/issues/119) Groundwater + solar PV block | Fix implemented on `feat/water-solar` (Hub'Eau + PVGIS verified live, 39 tests green); also fixes the PDF text-truncation bug | Open the PR (prose approval), then BSS boreholes as follow-up |
| [#118](https://github.com/confinia/ecobuilding/issues/118) Eco data beyond Europe/France | Filed | Research: score NL / England-Wales / DK / IE |
| [#117](https://github.com/confinia/ecobuilding/issues/117) DATA.md data lifecycle | PR [#120](https://github.com/confinia/ecobuilding/pull/120) open | Merge |
| [#115](https://github.com/confinia/ecobuilding/issues/115) STACK_template.md | Shipped to `main` via [#116](https://github.com/confinia/ecobuilding/pull/116) | Close the issue (close comment awaiting approval) |
| [#113](https://github.com/confinia/ecobuilding/issues/113) Building marker (web + PDF) | PR [#114](https://github.com/confinia/ecobuilding/pull/114) open, **sandbox-validated** | Merge → deploy → rebuild the shared render container |
| [#112](https://github.com/confinia/ecobuilding/issues/112) CI/CD via GitHub Actions | Filed | Self-hosted runner on the VM; until then `deploy/*.sh` is break-glass (rule 14) |
| [#111](https://github.com/confinia/ecobuilding/issues/111) Dedicated staging stack + DB | Filed | Blocked-ish on [#112](https://github.com/confinia/ecobuilding/issues/112) ordering decision |
| [#35](https://github.com/confinia/ecobuilding/issues/35) Polar.sh checkout | Backlog | Gated by rule 7 (no company / paid tier below a 10k€ deal) |
| [#33](https://github.com/confinia/ecobuilding/issues/33) Product v2 on own domain | Backlog | Revisit after launch metrics |
| [#28](https://github.com/confinia/ecobuilding/issues/28) Self-host BDNB | Partially done: BDNB restored in PostGIS on the VM; PostgREST exposes only `dvf` today | Expose the BDNB schema + set `BDNB_URL`/`BDNB_BASE_URL` (see DATA.md §2, §4) |

## To file (prose awaiting approval, rule 11)

- PDF report: long values (Géorisques URL, risk lists) clipped at the page edge
  — fix already on `feat/water-solar`.
- Staging routing broken (`next.` → `staging.`) — belongs to `confinia/platform`.
- This tracker itself (ISSUES.md + rule 15).
