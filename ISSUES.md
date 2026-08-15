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
| [Staging](https://staging.ecobuilding.confinia.io) | candidate = blue (pre-promote prod) | **Routing fixed 2026-08-11** (platform PR [#3](https://github.com/confinia/platform/pull/3)) — validate-on-staging gate restored |
| [Sandbox](https://sandbox.ecobuilding.confinia.io) | sandbox stack (:8030) | Publicly routed again (platform PR [#3](https://github.com/confinia/platform/pull/3)) |

## Open / recently shipped issues

| Issue | Status | Next step |
|---|---|---|
| [#173](https://github.com/confinia/ecobuilding/issues/173) 1PESI 13xxx port migration | **Complete 5/5, platform-confirmed 2026-08-15**; legacy slots freed; post-audit PR [#179](https://github.com/confinia/ecobuilding/pull/179) purged script remnants (sandbox.sh dead :8030 checks — 6 min wasted per run —, stale router artifact, dead prometheus.yml) | Follow-ups: grafana 13040 network-join; [#178](https://github.com/confinia/ecobuilding/issues/178) BAN→Géoplateforme |
| [#162](https://github.com/confinia/ecobuilding/issues/162) DVF prices off in prod + no panel display | **In production 2026-08-12** (PR [#163](https://github.com/confinia/ecobuilding/pull/163)): `DVF_RPC_URL` wired (RPC was live all along), panel 'Prix de vente (DVF)' section; verified: 78575 maison 4 363 €/m², 5 sources | — |
| [#152](https://github.com/confinia/ecobuilding/issues/152) Map click titled with wrong address (multi-street groupes, unreliable BDNB relations) | **In production 2026-08-12** (PR [#153](https://github.com/confinia/ecobuilding/pull/153)): BAN-reverse arbitration (member > on-building ≤30 m > nearest member <150 m > principal), exact Lambert-93 inverse, `sandbox.sh --force-recreate` fix (stale-code footgun) | — |
| [#150](https://github.com/confinia/ecobuilding/issues/150) Frontend loading feedback | **In production 2026-08-12** (PR [#158](https://github.com/confinia/ecobuilding/pull/158)): spinners on all panel loads; PDF button with honest staged labels, popup-safe, quota page preserved | — |
| [#144](https://github.com/confinia/ecobuilding/issues/144) Runner post-job cleanup kills podman helpers | **Closed 2026-08-12** (PR [#149](https://github.com/confinia/ecobuilding/pull/149)): deploys run via `ssh localhost` (lingering logind session — transient units get reaped too); validated: sandbox :8030 + staging :8021 alive after job end | — |
| [#146](https://github.com/confinia/ecobuilding/issues/146) Panel titled with BDNB principal address (Marronniers/Peupliers) | **In production 2026-08-12** (PR [#148](https://github.com/confinia/ecobuilding/pull/148); sandbox+staging via pipeline, first successful promote dispatch) | — |
| Launch thresholds (TODO, no issue) | **Written** into BUSINESS.md §8 (2026-08-11), fixed pre-post | Post the launch (LAUNCH.md copy ready) |
| [#141](https://github.com/confinia/ecobuilding/issues/141) /grafana 502 (IPv6-only bind after recreate) | **Fixed & validated 2026-08-11** (PR [#142](https://github.com/confinia/ecobuilding/pull/142)): `GF_SERVER_HTTP_ADDR=0.0.0.0` pinned; public /grafana 200 | Follow-up to file: scrape Grafana itself so the target-down alert emails this class of failure |
| [platform#2](https://github.com/confinia/platform/issues/2) + [#136](https://github.com/confinia/ecobuilding/issues/136) staging/sandbox routing + KC client URIs | **Done & validated 2026-08-11** (platform PR [#3](https://github.com/confinia/platform/pull/3), eco PR [#137](https://github.com/confinia/ecobuilding/pull/137)): staging + sandbox live over TLS, live realm replays URIs from the bootstrap JSON on deploy | — |
| [#128](https://github.com/confinia/ecobuilding/issues/128) Email via alert@confinia.io (Keycloak verify + Grafana alerts) | **Done & validated 2026-08-11**: SMTP relay live (OVH MX Plan, `ssl0.ovh.net:587`); Keycloak realm SMTP + `verifyEmail` applied by `kc-smtp.sh` (pre-flight passed); registration verify-email e2e delivered; Grafana contact point/rule provisioned with matching creds; DKIM enabled. All as code. **Closed** | — |
| [#125](https://github.com/confinia/ecobuilding/issues/125) Hub'Eau date_recherche lag excluded all stations | **In production** (PR [#126](https://github.com/confinia/ecobuilding/pull/126), promoted 2026-08-05) | — |
| [#122](https://github.com/confinia/ecobuilding/issues/122) ISSUES.md tracker + rule 15 | **Merged** (PR [#124](https://github.com/confinia/ecobuilding/pull/124)) — docs-only | — |
| [#121](https://github.com/confinia/ecobuilding/issues/121) PDF text clipped at page edge | **In production** (PR [#123](https://github.com/confinia/ecobuilding/pull/123), promoted 2026-08-05; verified on the Tournefeuille fiche) | — |
| [#119](https://github.com/confinia/ecobuilding/issues/119) Groundwater + solar PV block | **In production** (PR [#123](https://github.com/confinia/ecobuilding/pull/123) + fix [#126](https://github.com/confinia/ecobuilding/pull/126), promoted 2026-08-05); **reopened** for the remaining scope | BSS boreholes ("présence d'un puits") — find a verified public endpoint |
| [#118](https://github.com/confinia/ecobuilding/issues/118) Eco data beyond France | Filed | Research: score NL / England-Wales / DK / IE |
| [#117](https://github.com/confinia/ecobuilding/issues/117) DATA.md data lifecycle | **Merged** (PR [#120](https://github.com/confinia/ecobuilding/pull/120)) — docs-only | Add Hub'Eau + PVGIS rows (new sources of [#119](https://github.com/confinia/ecobuilding/issues/119)) |
| [#115](https://github.com/confinia/ecobuilding/issues/115) STACK_template.md | **Closed** (shipped via [#116](https://github.com/confinia/ecobuilding/pull/116)) | — |
| [#113](https://github.com/confinia/ecobuilding/issues/113) Building marker (web + PDF) | **In production** (PR [#114](https://github.com/confinia/ecobuilding/pull/114), promoted 2026-08-05; marker verified in the prod PDF render) | — |
| [#112](https://github.com/confinia/ecobuilding/issues/112) CI/CD via GitHub Actions | **Done & self-validated 2026-08-11** (PR [#139](https://github.com/confinia/ecobuilding/pull/139)): runner `ecobuilding-vm` online; PR→sandbox run passed, merge→staging run passed (deploy + test gate + smoke); promote = Actions dispatch; `deploy/*.sh` wrappers = break-glass (rule 14 live) | — |
| [#111](https://github.com/confinia/ecobuilding/issues/111) Dedicated staging stack + DB | Filed | Order against [#112](https://github.com/confinia/ecobuilding/issues/112) |
| [#35](https://github.com/confinia/ecobuilding/issues/35) Polar.sh checkout | Backlog | Gated by rule 7 (no company / paid tier below a 10k€ deal) |
| [#33](https://github.com/confinia/ecobuilding/issues/33) Product v2 on own domain | Backlog | Revisit after launch metrics |
| [#28](https://github.com/confinia/ecobuilding/issues/28) Self-host BDNB | Partial: BDNB restored in PostGIS on the VM; PostgREST exposes only `dvf` today | Expose the BDNB schema + set `BDNB_URL`/`BDNB_BASE_URL` (see DATA.md §2, §4) |

## To file (prose awaiting approval, rule 11)

- (none)
