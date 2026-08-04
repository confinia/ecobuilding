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

## Open / recently shipped issues

| Issue | Status | Next step |
|---|---|---|
| [#122](https://github.com/confinia/ecobuilding/issues/122) ISSUES.md tracker + rule 15 | PR [#124](https://github.com/confinia/ecobuilding/pull/124) | Merge |
| [#121](https://github.com/confinia/ecobuilding/issues/121) PDF text clipped at page edge | **Merged** to `main` (PR [#123](https://github.com/confinia/ecobuilding/pull/123), 2026-08-04) | Deploy → promote |
| [#119](https://github.com/confinia/ecobuilding/issues/119) Groundwater + solar PV block | **Merged** to `main` (PR [#123](https://github.com/confinia/ecobuilding/pull/123): Hub'Eau + PVGIS, verified live, 39 tests) | Deploy → promote; BSS boreholes ("présence d'un puits") remain open here |
| [#118](https://github.com/confinia/ecobuilding/issues/118) Eco data beyond France | Filed | Research: score NL / England-Wales / DK / IE |
| [#117](https://github.com/confinia/ecobuilding/issues/117) DATA.md data lifecycle | **Merged** to `main` (PR [#120](https://github.com/confinia/ecobuilding/pull/120), 2026-08-04) | Docs-only — no deploy needed |
| [#115](https://github.com/confinia/ecobuilding/issues/115) STACK_template.md | **Closed** (shipped via [#116](https://github.com/confinia/ecobuilding/pull/116)) | — |
| [#113](https://github.com/confinia/ecobuilding/issues/113) Building marker (web + PDF) | **Merged** to `main` (PR [#114](https://github.com/confinia/ecobuilding/pull/114), sandbox-validated) | Deploy + **rebuild the shared render container** → promote |
| [#112](https://github.com/confinia/ecobuilding/issues/112) CI/CD via GitHub Actions | Filed | Self-hosted runner on the VM; until then `deploy/*.sh` is break-glass (rule 14) |
| [#111](https://github.com/confinia/ecobuilding/issues/111) Dedicated staging stack + DB | Filed | Order against [#112](https://github.com/confinia/ecobuilding/issues/112) |
| [#35](https://github.com/confinia/ecobuilding/issues/35) Polar.sh checkout | Backlog | Gated by rule 7 (no company / paid tier below a 10k€ deal) |
| [#33](https://github.com/confinia/ecobuilding/issues/33) Product v2 on own domain | Backlog | Revisit after launch metrics |
| [#28](https://github.com/confinia/ecobuilding/issues/28) Self-host BDNB | Partial: BDNB restored in PostGIS on the VM; PostgREST exposes only `dvf` today | Expose the BDNB schema + set `BDNB_URL`/`BDNB_BASE_URL` (see DATA.md §2, §4) |

## To file (prose awaiting approval, rule 11)

- Staging routing broken (`next.` → `staging.`) — belongs to `confinia/platform`.
