# OpenIndoor — TODO

Actions to make progress on the product and the business.
Status: `[ ]` todo · `[~]` in progress · `[x]` done

## Business / validation

- [x] Market research #1: who pays for indoor mapping / 3D building visualization (done 2026-07-20 — see BUSINESS.md §9.1)
- [ ] Check the SNCF-Transilien OSM-indoor precedent (arx IT, Carto'Cité, Wemap paid to map stations) — real French paid OSM-indoor work
- [ ] Assess OSM indoor (SIT) coverage/quality in candidate French venues — decide: OSM as data source vs OSM as data model + CAD ingestion
- [ ] Architecture decision: how photosphere positions are georeferenced (avoid OSM-derived positional metadata, or accept share-alike on positions)
- [x] Market research #2: French open-data verticals (done 2026-07-20 — see BUSINESS.md §10.2; winner: DPE-rentability on BDNB)
- [ ] Hands-on BDNB check: pull the free vector tiles into a MapLibre page; query the API for a known address; measure real DPE coverage on a test commune
- [ ] Join test: BDNB building ↔ ADEME DPE database (how much coverage does the join add?)
- [ ] Recheck DPE ban-calendar legislation before committing (April 2026 "Relance logement" bill derogations)
- [ ] Define v1 scope of the DPE-rentability scorecard (free lookup + paid portfolio tier)
- [ ] Design the API surface early (the scorecard backend IS the API): normalized per-building JSON schema, keys, metering
- [x] DPE France layer live in prod (BDNB tiles, 3D colored by class, 2026-07-20)
- [ ] Spec the embeddable widget (script tag, per-domain licensing)
- [ ] Pick 1 primary target segment from research findings (see BUSINESS.md §8)
- [x] Verify ODbL implications (2026-07-20: Produced Works sellable; no moat in enhanced OSM data; photospheres safe as reference-linked layer — BUSINESS.md §5)
- [x] Verify OSM2World license (2026-07-20: MIT since Feb 2026 — commercial SaaS OK)
- [ ] Check OVH employment contract for exclusivity/loyalty clause (side-project compatibility); set up/reuse micro-entreprise
- [ ] Define the self-serve product v1: per-address automated report or 3D scorecard (vertical from report #2)
- [ ] Validate demand cheaply & asynchronously: landing page + SEO test on ~100 generated address pages, measure organic traffic before building the full pipeline

## Partnership — Tobias Knerr / OSM2World

- [ ] Reply to Tobias: short, warm, low-commitment — decline SOTM Paris, mention restarting OpenIndoor experiments, no promises (show first, propose later)
- [ ] Build a working SIT-tagged indoor example (one building) — *then* offer it to Tobias as test material for OSM2World's indoor work
- [ ] Only after something works: consider proposing a joint demo / grant / sponsorship
- [ ] Test OSM2World's 3D-tiles export (Prototype Fund work) as it lands → feed into MapLibre pipeline
- [ ] Explore NLnet / NGI grant for the open-source indoor + photosphere pipeline (discuss with Tobias before SOTM)
- [ ] Decide whether/how to fund or contribute to OSM2World indoor work if it becomes commercially critical

## Product / tech

- [x] Minimal MapLibre 3D demo (2026-07-20: whole France, OpenFreeMap + fill-extrusion — https://ecobuilding.confinia.io)
- [x] MVP deployed: frontend + versioned API (/api/v1/docs) + dedicated Grafana (/grafana) + blue/green staging (next.ecobuilding.confinia.io)
- [ ] Evaluate OSM2World output quality vs plain MapLibre fill-extrusion for target buildings
- [ ] Pipeline: OSM Simple Indoor Tagging → per-floor indoor rendering in MapLibre
- [ ] Georeference existing photospheres against OSM indoor data for one showcase building
- [ ] Integrate photosphere view ↔ 3D map view transition (the differentiating UX)
- [ ] Retro-FPS navigation demo inside one captured building (marketing showcase + data-flywheel seed)
- [ ] Design the "map your building → play it" loop (auto-generate level from any SIT-tagged OSM building)
- [ ] Instrument the demo (sessions, D1/D7 retention) — needed for the gaming decision rule (BUSINESS.md §4)
- [ ] Later, if demo resonates: pitch white-label branded instances to 2-3 venues (mall/museum/event, ~1-5k€)
- [ ] Deploy public demo (static hosting, no per-request map costs)

## Marketing / visibility

- [ ] Pre-announce: add /lookup response cache (BDNB quota guard) — ~1h work
- [ ] Set launch success thresholds in writing (see BUSINESS.md §8 launch plan), then post
- [ ] Show HN draft: "3D map of every French building's energy class (open data, solo side project)" — countdown framing
- [ ] LinkedIn FR post (agencies/notaires angle: interdiction de location 2028/2034)
- [ ] OSM forum + r/openstreetmap + geo Mastodon (community + backlinks)
- [ ] Week after: read Grafana numbers, decide per-address SEO pages go/no-go
- [ ] Publish the FPS demo publicly (HN, OSM community, r/openstreetmap, LinkedIn)
- [ ] Write a technical blog post on the photosphere↔OSM pipeline
- [ ] Present at a local OSM / geo meetup (SOTM-FR?)

## Done

- [x] Define product concept and asset inventory (BUSINESS.md, 2026-07-20)
- [x] Launch monetization market research (2026-07-20)
