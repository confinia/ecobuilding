# EcoBuilding — launch texts & plan (2026-07-21)

Order (revised 2026-08-12, operator call — FR-personas first): OSM forum ✓ →
GeoRezo → Reddit r/immobilier + r/InternetIsBeautiful → Mastodon (when the
mapstodon approval lands) → LinkedIn via the Confinia COMPANY page (not the
personal profile). Show HN DEFERRED: not for lack of US data (the countdown
story carries on HN), but HN is not the buyer channel; revisit with a
technical write-up or EU/NYC data angle. One week of Grafana measurement, then
go/no-go on per-address SEO pages (thresholds in BUSINESS.md §8 — the 7-day
window started at the first post; log every post below).

Pre-post guard CLEARED 2026-08-03: /lookup cache + per-IP daily cap live.

## Posting log (fill as you post — anchors the threshold window)

- [x] LinkedIn — posté depuis la page ENTREPRISE EcoBuilding (linkedin.com/company/ecobuilding-confinia-io, séparation vie perso assumée) : 2026-08-12 (~07h30 UTC); 1re réaction en <1 h
- [x] OSM forum — relance sur le sujet 44898 : 2026-08-12 (~12h UTC) — WINDOW START; seuils jusqu'au 2026-08-19 (initial post 2026-07-21 : 111 vues, 6 likes, réponses dont cquest)
- [ ] Mastodon — :
- [~] Show HN — DEFERRED (2026-08-12, operator call; revisit post-window)
- [~] r/immobilier — modmail envoyé (rule 9 du sub : outil gratuit via wiki) : 2026-08-12, en attente de la modération
- [x] Reddit r/openstreetmap — text post : 2026-08-15 (u/SpaceClement); AUSSI à faire : commentaire dans le thread épinglé « OpenStreetMap websites/apps to share » (long tail)
- [x] Reddit r/SideProject — text post : 2026-08-15 (u/SpaceClement)
- [~] Reddit r/InternetIsBeautiful — post 2026-08-15 REMOVED par automod (karma insuffisant); modmail d'appel envoyé; retry seulement après accord mods ou karma construit (r/gis, r/openstreetmap). Le social card (#169) s'affichait parfaitement.
- [ ] GeoRezo — :

## LinkedIn (FR)

🏢 EcoBuilding est en ligne: la carte de France des bâtiments en 3D,
colorés par classe énergie (DPE).
(Voix de MARQUE: la page entreprise parle, jamais « je » — séparation vie perso.)

Tapez une adresse (ou cliquez sur n'importe quel bâtiment) et voyez sa classe
énergie, son échéance loi Climat & Résilience (G interdit à la location depuis
2025, F en 2028, E en 2034), ses risques naturels (Géorisques), son année de
construction, ses matériaux, la profondeur de la nappe phréatique et son
productible solaire (PVGIS). Chaque bâtiment a aussi sa fiche PDF normalisée,
gratuite.

100 % données ouvertes : la BDNB du CSTB (32 millions de bâtiments), la Base
Adresse Nationale et Géorisques. Gratuit, sans compte, avec une API publique
documentée.

👉 https://ecobuilding.confinia.io (essayez votre propre adresse)

Projet indépendant, en amélioration continue. Retours bienvenus, en particulier
des agences, syndics, diagnostiqueurs et bailleurs: qu'est-ce qui vous serait
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

Each building also gets a free normalized PDF report: energy label, risk
report, groundwater depth at the nearest piezometer, PVGIS solar yield, street
imagery and a full data-provenance annex (every value links back to its
official source).

Free, no account, no tracking (anonymous counters only). Open JSON API:
https://ecobuilding.confinia.io/api/v1/docs

Stack: MapLibre GL, FastAPI, OpenTelemetry→Prometheus→Grafana, two blue/green
podman stacks behind Caddy on a dedicated server. Solo side project.

https://ecobuilding.confinia.io

Mechanics: stay online 2–3h to answer comments. On "already exists": agree —
flat maps exist; this adds 3D + click-to-inspect + open API; love letter to
French open data.

## OSM France — forum.openstreetmap.fr, catégorie « Annonces »

(⚠ la catégorie France de community.openstreetmap.org est une ARCHIVE
read-only — ne pas y poster ; la communauté FR vit sur forum.openstreetmap.fr.
Version EN éventuelle : community.openstreetmap.org → General talk.)

Titre : EcoBuilding — les bâtiments français en 3D, colorés par DPE
(MapLibre + BDNB + fond OSM)

Bonjour,

Petit projet perso mis en ligne ce week-end : https://ecobuilding.confinia.io

Les bâtiments français en 3D dans MapLibre GL, colorés par classe DPE, à partir
des tuiles vectorielles ouvertes de la BDNB (CSTB, Licence Ouverte, ~32 M de
bâtiments). Fond de carte OpenFreeMap (OpenMapTiles / données © OpenStreetMap).
Recherche d'adresse via la BAN, risques via Géorisques. En cliquant sur un
bâtiment : classe énergie, échéance loi Climat & Résilience, année de
construction, matériaux, aléa argiles, profondeur de nappe (Hub'Eau) et
productible solaire (PVGIS), plus une fiche PDF gratuite avec annexe de
traçabilité des sources.

Une API JSON publique et documentée expose la même chaîne de données :
https://ecobuilding.confinia.io/api/v1/docs

Les attributions sont en place (OSM, OpenMapTiles, OpenFreeMap, BDNB, BAN,
Géorisques, Hub'Eau, PVGIS) ; si vous voyez quelque chose à corriger sur ce
point, je suis preneur. Remarques et idées bienvenues !

## Mastodon (mapstodon.space ou instance geo)

Toot court : lien + « bâtiments français en 3D colorés par DPE, 100 % données
ouvertes (BDNB/CSTB, BAN, Géorisques), fond OSM, API publique ».

## Reddit

- **r/InternetIsBeautiful** (priorité #1, HN étant bloqué) — link post, titre :
  "Interactive 3D map of every building in France, colored by energy
  efficiency — built entirely on open government data" + 1 commentaire auteur
  (click any building → record; rental bans 2025/2028/2034; free API).
- **r/immobilier** (persona acheteur/bailleur) — titre : "[Outil gratuit]
  Vérifiez le DPE, l'échéance d'interdiction de location et les risques de
  n'importe quel bâtiment, en 3D" + texte FR (données ouvertes, pas de compte).
- r/openstreetmap, r/webdev, r/SideProject, r/dataisbeautiful : corps Show HN
  raccourci.
- r/france : SEULEMENT si bonne réception ailleurs ; angle service public,
  Forum Libre.

## GeoRezo (georezo.net — géomaticiens FR = prospects API)

Titre : EcoBuilding — BDNB en tuiles vectorielles + MapLibre : bâtiments 3D
colorés par DPE, API publique.
REX : la BDNB expose 32 M de bâtiments en tuiles MVT consommables par MapLibre
(couche sql_statement, classe_bilan_dpe, hauteur_mean…). Carte 3D cliquable +
API JSON normalisée (BAN → BDNB → Géorisques) : ecobuilding.confinia.io
(docs /api/v1/docs). Détails techniques volontiers — preneur de retours sur les
usages métier.

## Product Hunt (optionnel)

Tagline : "Every French building's energy efficiency, in 3D — open data, free API".

## Astuce LinkedIn

Lien dans le PREMIER COMMENTAIRE, pas dans le post (throttling des liens
externes) ; reposter aux heures de bureau FR.
