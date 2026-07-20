# EcoBuilding — launch texts & plan (2026-07-21)

Order: LinkedIn → OSM forum + Mastodon (same day) → Show HN (next weekday,
15h–17h Paris) → Reddit (after HN). One week of Grafana measurement, then
go/no-go on per-address SEO pages (thresholds in BUSINESS.md §8).

⚠ Pre-post guard: add /lookup response cache (BDNB 10k calls/month) BEFORE HN.

## LinkedIn (FR)

🏢 J'ai mis en ligne EcoBuilding : la carte de France des bâtiments en 3D,
colorés par classe énergie (DPE).

Tapez une adresse — ou cliquez sur n'importe quel bâtiment — et voyez sa classe
énergie, son échéance loi Climat & Résilience (G interdit à la location depuis
2025, F en 2028, E en 2034), ses risques naturels (Géorisques), son année de
construction, ses matériaux et son potentiel solaire.

100 % données ouvertes : la BDNB du CSTB (32 millions de bâtiments), la Base
Adresse Nationale et Géorisques. Gratuit, sans compte, avec une API publique
documentée.

👉 https://ecobuilding.confinia.io (essayez votre propre adresse)

Projet perso, développé sur mon temps libre. Retours bienvenus — en particulier
des agences, syndics, diagnostiqueurs et bailleurs : qu'est-ce qui vous serait
réellement utile au quotidien ?

## Show HN

Title: Show HN: 3D map of every French building, colored by energy efficiency (open data)

France publishes remarkable open data about buildings: the BDNB (by CSTB, the
national building research center) cross-references ~20 public databases into
an "identity card" for 32M buildings — energy class, construction year, height,
materials, clay-shrinkage risk, solar potential. It even ships MapLibre-ready
vector tiles.

I render it as a clickable 3D city: search an address or click any building to
get its full record, including its rental-ban deadline — France progressively
bans renting energy-inefficient homes (worst class since 2025, next tiers in
2028 and 2034), so the red buildings have a legal countdown attached.

Free, no account, no tracking (anonymous counters only). Open JSON API:
https://ecobuilding.confinia.io/api/v1/docs

Stack: MapLibre GL, FastAPI, OpenTelemetry→Prometheus→Grafana, two blue/green
podman stacks behind Caddy on a dedicated server. Solo side project.

https://ecobuilding.confinia.io

Mechanics: stay online 2–3h to answer comments. On "already exists": agree —
flat maps exist; this adds 3D + click-to-inspect + open API; love letter to
French open data.

## OSM forum (community.openstreetmap.org, catégorie France) + Mastodon

Petit projet perso : https://ecobuilding.confinia.io — les bâtiments français
en 3D (MapLibre), colorés par DPE, via les tuiles vectorielles ouvertes de la
BDNB (CSTB), fond de carte OpenFreeMap/OpenMapTiles/OSM. Recherche BAN, risques
Géorisques, API publique. Attributions en place — remarques bienvenues,
notamment sur l'attribution ou l'usage des données.

## Reddit

r/openstreetmap, r/webdev, r/dataisbeautiful: shortened Show HN body.
r/france: ONLY if reception elsewhere is good; frame as service public
("vérifiez le DPE et les risques de votre logement"), Forum Libre thread.
