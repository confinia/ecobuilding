# OpenIndoor — Business Analysis & Tracking

> Working document to analyse and track progress on monetizing a 3D building-exploration
> product built on open data. Last updated: 2026-07-20 (initial draft, market research in progress).

## 1. Product concept

**Input:** open data, mainly OpenStreetMap (buildings, Simple Indoor Tagging), plus
proprietary indoor photosphere captures georeferenced against OSM indoor data.

**Output:** 3D exploration of real buildings in the browser through the MapLibre GL JS engine.

**Technical building blocks:**
- MapLibre GL JS — fill-extrusion layers and/or custom 3D layers, all client-side, no per-request map fees.
- OSM2World (Tobias Knerr) — candidate pipeline for generating richer 3D geometry from OSM data.
- Indoor photospheres — proprietary captured data, the main *differentiated* asset (OSM data itself is open to everyone).
- Retro-FPS navigation demo (Wolfenstein 3D / Duke Nukem style) inside the MapLibre universe — showcase / marketing vehicle.

## 2. Assets & differentiation

| Asset | Who else has it | Defensible? |
|---|---|---|
| OSM building + indoor data | Everyone (open data) | No — but expertise in exploiting it is rare |
| MapLibre 3D rendering pipeline | Open source, replicable | Weakly — execution & polish matter |
| Indoor photospheres + OSM georeferencing | **Only us, per captured building** | Yes — proprietary per-building data |
| Capture + integration know-how | Few players | Yes — service moat |

Key observation: the defensible asset is not the viewer, it is **the per-building captured data
and the pipeline that links photospheres to OSM indoor topology**.

## 3. Candidate markets (hypotheses under research)

| # | Segment | Hypothesis | Willingness to pay | Status |
|---|---|---|---|---|
| H1 | BIM / AEC / digital twins | Building owners pay for lightweight web twins vs heavy BIM tools | **Confirmed** (Esri personas: BIM/CAD pros; enterprise pricing) | Validated §10.1 |
| H2 | Facility management / CAFM | FM operators pay per building for visual asset navigation | **Confirmed** (Esri lead persona; MapsIndoors est. $12–80k/yr) | Validated §10.1 |
| H3 | Indoor wayfinding (airports, hospitals, malls, campuses) | Venues pay SaaS for visitor navigation | **Confirmed** ($165/venue/mo benchmark, Mappedin; Pointr 5k+ venues) | Validated §10.1 |
| H4 | Real-estate / hospitality marketing | Virtual visits (Matterport-like) but map-anchored | Partial (Matterport existed at scale but crashed post-SPAC, bought by CoStar 2025) | Unverified |
| H5 | Public sector / accessibility (FR/EU) | Open-data & accessibility mandates fund indoor mapping | No verified evidence yet; SNCF-Transilien OSM-indoor precedent to check manually | Open |
| H6 | Gaming / virtual tourism | Players pay to explore real buildings | **No willingness-to-pay evidence found**; posture = marketing + flywheel + white-label (§4) | Closed as revenue line |
| H7 | Building ecological quality (FR) | DPE/energy data per building; rental bans create urgency | **Confirmed — strongest vertical** (ban calendar 3-0; Deepki leaves SMB gap; BDNB enables) | **SELECTED §10.2** |
| H8 | Fire / natural risk exposure | Géorisques risks; buyers: insurers, communes, real estate | Partial: paid ERP market proven BUT commoditized duopoly + free state tool; avoid frontal entry; risk *layer* still valuable in H7 product | Validated §10.2 |
| H9 | Solar potential | Per-roof solar scoring; buyers: installers, collectivités | **Avoid**: national incumbents (Cythelia, namR, Otovo); communal WTP refuted 0-3 | Closed §10.2 |
| H10 | Pool / structure detection for taxation | DGFiP "Foncier Innovant" precedent | No verified claims either way | Open (low priority) |
| H11 | Water reserves over time | BRGM/ADES piezometry, drought | No verified claims either way | Open (low priority) |
| H12 | Weather / climate adaptation per building | Météo-France + DRIAS localized | No verified claims; possible layer in H7 product | Open |
| H13 | Ecology / ZAN tracking | ZAN dashboards for communes/EPCI | No verified claims; B2G sales conflicts with side-project constraint | Open (low priority) |
| H14 | Energy consumption per building/area | Enedis/GRDF open data; décret tertiaire (OPERAT) | No verified claims; open question: SMB tertiary owners segment Deepki ignores | Open (watch) |
| H15 | Alignment with French state priorities | Compliance mandates create tool demand | Confirmed via H7 (rental bans = strongest verified engine); other funding streams unverified | Partial §10.2 |

## 4. Business model options

- **Data-as-a-service:** capture + model buildings, sell access/updates per building.
- **SaaS viewer / white-label:** embeddable 3D building explorer, per-building or per-venue pricing.
- **Service + platform (consulting-led):** paid integration projects seed the product; recurring hosting after.
- **Gaming as revenue:** direct B2C mass-market — assessed 2026-07-20 as the weakest path.
  Precedents: Google Maps gaming API shut down (~2022) for lack of viable games; Minecraft Earth
  killed; Niantic shut Harry Potter Wizards Unite despite the IP and sold its games business to
  Scopely (2025) to pivot to selling geospatial data. F2P economics need millions of users and
  paid acquisition. Content bottleneck: OSM indoor coverage is sparse. Counter-example to watch:
  GeoGuessr (real-world data, low ARPU, profitable — but its game loop is inexhaustible, ours isn't).
- **Gaming as marketing + data flywheel + white-label (chosen posture):**
  1. Free viral demo → inbound B2B leads;
  2. "Map your building, then play it" → selfish incentive for OSM indoor contributions
     (StreetComplete effect) → enriches the commons our paid products draw from;
  3. White-label branded instances (mall, museum, event, team-building) at ~1–5k€/venue —
     B2B per-venue pricing, zero user-acquisition cost.
  **Decision rule:** only revisit the consumer-game thesis if the viral launch shows organic
  D7 retention > ~10–15%; no game-design-depth investment before that signal.

## 5. Licensing constraints — VALIDATED (see §10.1 for sources)

- ODbL allows commercial use & any pricing. Rendered 3D views/tiles/game views are **Produced
  Works** → sellable under any terms, attribution only.
- **No proprietary moat in enhanced OSM data** (ODbL 4.6 free-copy right) → proprietary value must
  live in the photosphere layer + the viewer, never in an "improved OSM" database.
- Photospheres stay proprietary if kept as an **independent reference-linked layer** (link by OSM
  element ID; never merge same-feature-type data). ⚠ If photosphere *positions* are computed from
  OSM geometry, that metadata may be OSM-derived — isolate or accept share-alike on positions.
- OSM2World is **MIT since Feb 2026** → fine in closed commercial SaaS.

## 6. Partnerships

### Tobias Knerr (OSM2World) — contact re-established 2026-07

Email exchange (July 2026, follow-up from meeting at SOTM Florence 2022):
- Tobias is funded by the **Prototype Fund** to work on OSM2World: improved terrain support and **export as 3D tiles** → directly solves our OSM2World→web-engine integration problem, funded independently of us.
- He wants to **complete OSM2World's half-finished indoor implementation**; attended an OSM indoor workshop in July 2026. Our photospheres + OSM indoor data are an ideal real-world use case for that work.
- He proposed meeting at **State of the Map Paris** this year.

**Chosen posture:** open-source collaboration, not business entanglement — and **show first,
propose later**: no promises of sponsorship, grants, or joint demos in early contact; offer
concrete artifacts (test data, working examples) only once they exist. In the open-source world
everyone has their own constraints; only delivered work has value. OpenIndoor acts as
flagship use case/contributor (test data, feedback, possibly sponsorship or code) for the indoor
work; the commercial layer (photosphere capture, per-building data, customers) stays ours.
OSM2World is LGPL → server-side use in a commercial SaaS is fine.
**Risk to manage:** do not let product viability depend on a volunteer roadmap — if indoor
support becomes commercially critical, fund it explicitly.

**Opportunity:** joint indoor-3D demo ready before SOTM Paris (2026-10-05). Decision 2026-07-20:
Clément does not attend (cost vs uncertain ROI) — collaboration runs remotely (video calls), and
Tobias can present the demo at SOTM himself → community visibility at zero cost.
**Funding angle:** NLnet / NGI grants (EU, not Germany-restricted) could fund the open-source
indoor/photosphere pipeline — worth exploring before SOTM.

## 7. Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-07-20 | Repo created; research launched on monetization paths | No identified revenue model yet |
| 2026-07-20 | Pursue OSM2World partnership as open-source collaboration (flagship use case), keep commercial layer separate | Tobias's 3D-tiles grant work + indoor plans align with our pipeline; avoid dependency on volunteer time |
| 2026-07-20 | Skip SOTM Paris (2026-10-05) attendance; collaborate remotely, target demo Tobias can present there | Ticket + travel cost vs uncertain ROI; visibility achievable without attending |
| 2026-07-20 | Game = marketing + OSM-indoor data flywheel + white-label venues; NOT a consumer revenue bet unless D7 retention > 10–15% after viral launch | B2C precedents (Google, Microsoft, Niantic) all failed or pivoted; data flywheel serves the B2B verticals |
| 2026-07-20 | Side-project constraint locked in: permanent OVH contract incoming → only autonomous/self-serve revenue models; consulting & sales-led paths excluded | Alternative revenue in spare time, not a second job |

## 8. Current recommendation (updated 2026-07-20 for the side-project constraint)

**Hard constraint (2026-07-20):** Clément will hold a permanent position at OVH. This project is a
SIDE project for spare time — target is autonomous/product revenue ("infrastructure that earns
while I work"), NOT selling time. Excluded: consulting, sales-led B2B/B2G (meetings, procurement,
demos = time-selling in disguise), physical capture at scale.
To check once: OVH employment contract exclusivity/loyalty clause; micro-entreprise alongside a
CDI is standard in France; a GIS SaaS does not compete with OVH (and can be hosted on OVH).

Ranked plays, filtered for "runs without me" — vertical now selected from report #2 (§10.2):
1. **The bet: self-serve DPE-rentability scorecard on BDNB.** Product: enter an address (or a
   portfolio) → 3D building (MapLibre + BDNB's free ready-made vector tiles) with DPE class,
   **rental-ban timeline (G banned 2025 / F 2028 / E 2034)**, risk layers (Géorisques), and
   energy context. Free single-address lookup = SEO surface (every French address a landing
   page); paid tier for professionals (agencies, syndics, small landlords — the segment Deepki
   ignores): portfolio import, monitoring, alerts, exportable reports. SMB card-payment pricing
   (~15–50€/month or per-report). **No verified SMB competitor.** Data cost: ~0€ (Licence
   Ouverte v2.0, attribution only). ⚠ Mitigate <15% DPE coverage via ADEME DPE joins and honest
   "no DPE on file" display; evaluate BDNB Expert paid tier later.
2. **Same pipeline, the API & mapping offers (defined 2026-07-20):**
   - **Unified per-building intelligence API**: one key, one call → address → normalized JSON
     (DPE + ban status, Géorisques risks, BDNB attributes, 3D-ready geometry). Value = one key,
     one schema, SLA vs six raw government APIs (BDNB free tier: 10k calls/mo, no SLA) — the
     "convenience layer on free data" logic the ERP market proves (81% pay despite free tool).
     US analogues: ATTOM/Estated/Regrid. France: namR = enterprise-only datasets → no self-serve
     SMB per-building API exists. Freemium metered: ~500 free calls/mo, tiers ~29/99/299€/mo.
   - **Thematic vector tiles**: hosted "DPE France" / "risks" / "3D buildings" tile endpoints for
     MapLibre/Leaflet devs. Jawg (FR) proves hosted-tiles viability; do NOT do generic basemaps
     (price war) — per-building thematic layers are the open lane.
   - **Embeddable widget**: one `<script>` tag → 3D building + DPE/risk scorecard on any agency
     listing page; ~19–49€/domain/month, self-serve. Distribution to agencies without meetings.
   - Sequencing: scorecard → API (scorecard backend + keys/metering) → tiles/widget (packaging).
     Moat = aggregation quality, DX, uptime, and the 3D geometry endpoint nobody serves.
3. **OpenIndoor 3D viewer + game demo = organic acquisition engine**, not sold directly.
4. **Later, inbound-only:** widget embedded in diagnostiqueur/agency software (Liciel, iNot,
   D-TAB channel) — real distribution but requires partnership negotiation; only if they call.
5. **Deprioritized:** venue SaaS w/ CAD ingestion, photosphere capture at scale, white-label
   game deals, all B2G sales (incl. collectivité white-label — WTP unproven, sales-heavy).

Definition used — *willingness to pay*: verified evidence that identified BUYERS spend money on
the category (published prices, real contracts), the strongest form being one's own paying
customer. Competitors' prices are evidence of buyers, not the goal itself.

## 9. KPIs to track (once live)

- Buildings captured / modeled
- Demo sessions & inbound leads from the FPS demo
- Paying customers, MRR, revenue per building
- Cost per building capture (hours + hardware)

## 10. Research findings

### 10.1 Report #1 — Indoor mapping / 3D building market (completed 2026-07-20)

Method: 104-agent deep-research run; 22 sources fetched, 107 claims extracted, 25 verified by
3-vote adversarial panels → 23 confirmed, 2 refuted. Full output:
`/private/tmp/claude-501/-Users-clement-igonet-project-openindoor/73ad2120-0b9c-45db-b307-ec541124f15f/tasks/w1ov1jo2f.output`

**Who pays (verified):**
- **Mappedin** — the public price benchmark: **$165/map/month** (per-venue SaaS, unlimited floors,
  linear per venue), freemium wedge with SDK/API gated behind Pro. [mappedin.com/pricing]
- **Esri ArcGIS Indoors** — sales-led enterprise contracts, no list price (~$3.9k/yr per named user
  in a leaked US gov price list). Target personas: **facility managers, BIM/CAD professionals,
  emergency responders**, event planners, IT/GIS. Lead value prop = CAD/BIM/facility-data
  integration in large venues (airports, hospitals, universities) — not consumer 3D.
- **Pointr** — self-reports 7B+ sqft / 5,000+ venues; pipeline ingests **customer CAD via AI
  (MapScale)**, GeoJSON storage, Apple IMDF interop.
- **Key market fact:** *no incumbent builds from OSM indoor data* — commercial inputs are customer
  CAD/BIM/IMDF. OSM indoor is an uncommercialized niche: an opening, but also zero proven demand
  for OSM-sourced indoor maps. Open question: OSM as data *source*, or only as data *model* with
  customer-CAD ingestion like incumbents?

**Licensing verdicts (all 3-0 verified against primary sources):**
- ODbL explicitly allows commercial use and charging any price. ✓
- **Produced Works exemption (ODbL 4.5b):** rendered 3D views, display tiles, game views =
  sellable under any terms, attribution only. The viewer and FPS demo trigger NO share-alike. ✓
- **No moat in enhanced OSM data (ODbL 4.6):** any publicly-used derivative database must be
  handed to any recipient free of charge on request. Never build the business on an "improved
  OSM" database. ✓
- **Photospheres can stay proprietary** as an independent, reference-linked layer (Collective
  Database + Horizontal Layers guidelines): link by OSM element ID, never merge. ✓
  ⚠ Caveats: guidelines are OSMF interpretation (not court-tested); Horizontal Layers formally
  scoped to 2D maps; **if photosphere positions are computed from OSM geometry, that positional
  metadata may itself be OSM-derived** — architecture decision to handle carefully.
- **Operational rule:** never blend proprietary corrections into OSM indoor geometry (that
  contaminates via share-alike) — contribute corrections upstream to OSM, keep proprietary
  attributes in separate reference-linked tables. ✓
- **OSM2World is MIT since Feb 2026** (relicensed from LGPL with all contributors' agreement) —
  zero copyleft obstacle for a closed commercial SaaS. ✓

**Coverage gaps (explicitly not verified):** gaming revenue (Q4) and France/EU public-sector GTM
(Q5) produced no surviving verified claims — the "gaming = marketing only" stance rests on absence
of evidence plus known precedents (Google Maps gaming API sunset Dec 2022 for limited adoption,
per Google's deprecation page seen in search phase). Interesting unverified French lead: SNCF
Transilien paid providers (arx IT, Carto'Cité, Wemap) to map stations in OSM indoor — a real
precedent of paid OSM-indoor work in France, to check manually.

**Consequences for strategy:**
1. The asset split is legally confirmed: sell the viewer (Produced Work) + proprietary photosphere
   layer; give OSM improvements back upstream (which also feeds the Tobias/OSM2World partnership).
2. Price anchor exists: undercut or differentiate against $165/venue/month.
3. Realistic buyer today = venue/facility operators; expect CAD/BIM ingestion to matter more than
   OSM coverage for paying customers.

### 10.2 Report #2 — French open-data verticals (completed 2026-07-20)

Method: 105-agent run; 23 sources, 115 claims extracted, 25 verified → 23 confirmed, 2 refuted.
Full output: `/private/tmp/claude-501/.../tasks/woqssbtpf.output`

**The key enabling asset — CSTB BDNB (verified 3-0, live-tested):**
Per-building "identity card" for **32M+ French buildings**, built by cross-referencing ~20 public
databases (DPE, cadastre, IGN BDTopo, incl. OSM links) — *the hard entity-matching work is
already done*. BDNB-Open is **Licence Ouverte v2.0** (commercial use, attribution only), free API
(10k calls/month), and serves **ready-made vector tiles directly consumable by MapLibre** at
building→région scales. Near-perfect synergy with our stack. ⚠ <15% of buildings carry a real
DPE in the open tier; paid "BDNB Expert" tier has CSTB-modelled DPE estimates.

**Strongest compliance engine (3-0):** loi Climat & Résilience rental bans — DPE G banned since
1 Jan 2025, F on 1 Jan 2028, E on 1 Jan 2034. Calendar intact despite legislative churn (Sénat
Gacquerre bill adds suspensions but does NOT touch the dates; recheck before commitment —
April 2026 "Relance logement" bill proposes further derogations).

**The verified gap (3-0):** Deepki saturates ONLY the enterprise/institutional ESG segment
(600+ corporate clients, ~€4,000bn AUM). **Small landlords, independent agencies, syndics, small
communes have no funded incumbent serving them.**

**Verticals to AVOID (verified):**
- **ERP risk reports frontally:** WTP proven (81% of diagnostiqueurs pay a provider) but
  commoditized at 0.42–33€/report, Septeo/Preventimmo (~48%) + Media Immo (~36%) duopoly
  distributed via software integrations (Liciel, iNot, D-TAB), and the state's free
  Géorisques/ERRIAL tool caps prices. Note (refuted 0-3): ERP is NOT mandatory in every
  transaction — only in designated risk zones.
- **Cadastre solaire:** national incumbents exist (Cythelia, namR solaR, Otovo); the claim that
  100+ collectivités pay was REFUTED 0-3 — communal WTP unproven.

**Not verified either way (no surviving claims):** décret tertiaire/OPERAT tools, pool detection,
wildfire, water reserves, ZAN dashboards, BIM integration, and all public-procurement questions
(UGAP, <40k€ marchés) — H10/H11/H13/H14 remain open, not validated.

**Report's ranked plays (synthesis):**
1. **DPE energy-decency portfolio tool on BDNB + ADEME DPE** — "which of my units become
   unrentable in 2028/2034 and why", visualized on 3D buildings; buyers: agencies, syndics,
   small landlords at SMB pricing under Deepki's enterprise floor. **No verified SMB competitor.**
2. Per-building risk/energy intelligence as API/widget inside diagnostiqueur/agency software
   (the verified distribution channel) — differentiate by 3D, don't compete on commodity PDFs.
3. White-label BDNB map layers for small collectivités (⚠ collectivité WTP unproven; B2G sales
   effort conflicts with side-project constraint).
