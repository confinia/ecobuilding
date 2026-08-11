# EcoBuilding — Issue tracker

Living status of every open (and recently shipped) GitHub issue, updated each
working session (rule 15). Lifecycle: **filed → PR open → merged (on staging) →
promoted (production) → closed**. Environments (rule 12):
[production](https://ecobuilding.confinia.io) ·
[staging](https://staging.ecobuilding.confinia.io) ·
[sandbox](https://sandbox.ecobuilding.confinia.io).

Last updated: 2026-08-05 (post-promote).

## Environment state

| Environment | Runs | Note |
|---|---|---|
| [Production](https://ecobuilding.confinia.io) | `main` @ `55c2a18` — **promoted 2026-08-05** (green stack; blue kept for rollback) | Includes [#113](https://github.com/confinia/ecobuilding/issues/113), [#119](https://github.com/confinia/ecobuilding/issues/119), [#121](https://github.com/confinia/ecobuilding/issues/121), [#125](https://github.com/confinia/ecobuilding/issues/125); shared render container rebuilt (marker) |
| [Staging](https://staging.ecobuilding.confinia.io) | candidate = blue (pre-promote prod) | **Routing broken**: Tier-1 platform edge still routes `next.`; fix = PR to `confinia/platform` (STACK_ecobuilding.md §10) |
| [Sandbox](https://sandbox.ecobuilding.confinia.io) | `feat/building-marker` ([#114](https://github.com/confinia/ecobuilding/pull/114)) | Stale — branch merged; next PR will replace it |

## Open / recently shipped issues

| Issue | Status | Next step |
|---|---|---|
| [#128](https://github.com/confinia/ecobuilding/issues/128) Email via alert@confinia.io (Keycloak verify + Grafana alerts) | **Done & validated 2026-08-11**: SMTP relay live (OVH MX Plan, `ssl0.ovh.net:587`); Keycloak realm SMTP + `verifyEmail` applied by `kc-smtp.sh` (pre-flight passed); registration verify-email e2e delivered; Grafana contact point/rule provisioned with matching creds. All as code | Optional: enable DKIM in the OVH manager; close the issue |
| [#125](https://github.com/confinia/ecobuilding/issues/125) Hub'Eau date_recherche lag excluded all stations | **In production** (PR [#126](https://github.com/confinia/ecobuilding/pull/126), promoted 2026-08-05) | — |
| [#122](https://github.com/confinia/ecobuilding/issues/122) ISSUES.md tracker + rule 15 | **Merged** (PR [#124](https://github.com/confinia/ecobuilding/pull/124)) — docs-only | — |
| [#121](https://github.com/confinia/ecobuilding/issues/121) PDF text clipped at page edge | **In production** (PR [#123](https://github.com/confinia/ecobuilding/pull/123), promoted 2026-08-05; verified on the Tournefeuille fiche) | — |
| [#119](https://github.com/confinia/ecobuilding/issues/119) Groundwater + solar PV block | **In production** (PR [#123](https://github.com/confinia/ecobuilding/pull/123) + fix [#126](https://github.com/confinia/ecobuilding/pull/126), promoted 2026-08-05); **reopened** for the remaining scope | BSS boreholes ("présence d'un puits") — find a verified public endpoint |
| [#118](https://github.com/confinia/ecobuilding/issues/118) Eco data beyond France | Filed | Research: score NL / England-Wales / DK / IE |
| [#117](https://github.com/confinia/ecobuilding/issues/117) DATA.md data lifecycle | **Merged** (PR [#120](https://github.com/confinia/ecobuilding/pull/120)) — docs-only | Add Hub'Eau + PVGIS rows (new sources of [#119](https://github.com/confinia/ecobuilding/issues/119)) |
| [#115](https://github.com/confinia/ecobuilding/issues/115) STACK_template.md | **Closed** (shipped via [#116](https://github.com/confinia/ecobuilding/pull/116)) | — |
| [#113](https://github.com/confinia/ecobuilding/issues/113) Building marker (web + PDF) | **In production** (PR [#114](https://github.com/confinia/ecobuilding/pull/114), promoted 2026-08-05; marker verified in the prod PDF render) | — |
| [#112](https://github.com/confinia/ecobuilding/issues/112) CI/CD via GitHub Actions | Filed | Self-hosted runner on the VM; until then `deploy/*.sh` is break-glass (rule 14) |
| [#111](https://github.com/confinia/ecobuilding/issues/111) Dedicated staging stack + DB | Filed | Order against [#112](https://github.com/confinia/ecobuilding/issues/112) |
| [#35](https://github.com/confinia/ecobuilding/issues/35) Polar.sh checkout | Backlog | Gated by rule 7 (no company / paid tier below a 10k€ deal) |
| [#33](https://github.com/confinia/ecobuilding/issues/33) Product v2 on own domain | Backlog | Revisit after launch metrics |
| [#28](https://github.com/confinia/ecobuilding/issues/28) Self-host BDNB | Partial: BDNB restored in PostGIS on the VM; PostgREST exposes only `dvf` today | Expose the BDNB schema + set `BDNB_URL`/`BDNB_BASE_URL` (see DATA.md §2, §4) |

## To file (prose awaiting approval, rule 11)

- Staging routing broken (`next.` → `staging.`) — belongs to `confinia/platform`.
