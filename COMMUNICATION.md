# EcoBuilding — communication playbook

Operational how-to per channel: where to go, which account, what to post,
what tone. The COPY lives in [LAUNCH.md](LAUNCH.md) (single source of texts +
posting log — timestamp every post there); this file is the *how*.

## Identities (keep them consistent)

| Context | Identity | Notes |
|---|---|---|
| LinkedIn | **EcoBuilding company page** (`linkedin.com/company/ecobuilding-confinia-io`) | BRAND voice, never « je ». Personal profile stays silent (separation from job-market visibility). Link in FIRST comment. |
| OSM forum | `contact_confinia` | Community tone, light first-person OK. |
| GeoRezo | create `confinia` (email `contact@confinia.io`) | Forums distrust brand voice: technical REX tone. |
| Reddit | `u/SpaceClement` | Personal pseudonym — fine, no LinkedIn linkage. |
| Mastodon | `@confinia@mapstodon.space` (approval pending) | Geo instance = the audience is the local timeline. |
| Email (warm leads) | clement@igonet.fr, personal | Person-to-person beats brand-to-person. |

## Channel playbook

### GeoRezo — the API-buyer audience (géomaticiens)
- **URL:** https://georezo.net/forum/viewforum.php?id=5 (board **Webmapping**;
  fallback if mods object: « Géo communiqué », id=14)
- **Account:** `confinia` / contact@confinia.io. (A dormant personal account
  exists — username `clement@igonet.fr`, registered 2026-07-17: do NOT post
  from it, the username displays the raw personal email publicly; its emailed
  cleartext password should be changed.)
- **Action:** NEW topic
- **Title:** `EcoBuilding — BDNB en tuiles vectorielles + MapLibre: bâtiments 3D colorés par DPE, API publique`
- **Body:** LAUNCH.md § GeoRezo (the depersonalized REX version)
- **Etiquette:** REX framing (how BDNB MVT tiles are consumed), not product ad;
  answer technical questions fast; mention the API docs URL once.

### OSM forum (forum.openstreetmap.fr)
- **URL:** https://forum.openstreetmap.fr/t/ecobuilding-les-batiments-francais-en-3d-colores-par-dpe-maplibre-bdnb-fond-osm/44898
- **Action:** REPLY to the existing topic (never a new one — duplicate titles
  are blocked and the thread carries history: cquest engaged there).
- **Cadence:** one update-reply per meaningful product milestone, max ~1/month.

### LinkedIn (EcoBuilding page)
- **URL (admin):** https://www.linkedin.com/company/138063926/admin/
- **Action:** post AS the page; product link goes in the FIRST COMMENT
  (LinkedIn throttles posts with external links).
- **Voice:** brand (« EcoBuilding est en ligne »), rule 8 French style.
- **Engagement play:** comment AS the page on relevant posts (e.g. BAN/open-data
  threads) — that's how a 0-follower page gets seen. Never like/repost from the
  personal profile.

### Reddit
- **r/immobilier:** rule 9 du sub = free tools go through **modmail → wiki des
  outils** (sent 2026-08-12, awaiting mods). Once wiki-listed, link the wiki in
  comments on relevant DPE threads — never a direct post.
- **r/InternetIsBeautiful:** KARMA-GATED (2026-08-15: u/SpaceClement below the
  activity threshold). Unlock path: a week of genuine comments in r/gis /
  r/openstreetmap earns enough total karma. Then: direct LINK post allowed.
  Title: `Interactive 3D map of every building in France, colored by energy efficiency — built entirely on open government data`
  + one author comment (click any building → record; rental bans 2025/2028/2034; free API).
- **r/openstreetmap, r/SideProject:** no gate — TEXT posts, EN, OSM-angle /
  launch-story angle respectively (run-sheets given 2026-08-15). r/webdev:
  check karma requirements first.
- **r/france:** only if the rest lands well; public-service angle, Forum Libre.

### Mastodon (mapstodon.space)
- **Action:** once the approval email arrives, post the toot from LAUNCH.md.
  Value = the instance's local timeline (geo people); federate with hashtags
  #OSM #OpenData #cartographie #DPE.

### Show HN — DEFERRED (2026-08-12)
- Not for lack of a story; HN is not the buyer channel. Revisit with a
  technical write-up ("how BDNB MVT + MapLibre render 32M buildings") or the
  EU/NYC data angle.

### Earned media — OpenCage / Geomob
- **Who:** OpenCage (open geocoding co., @opencage@en.osm.town, Ed Freyfogle)
  runs the **Geomob** meetups (Paris edition, 5-min lightning talks) and the
  Geomob podcast; their blog features open-geo-data projects.
- **Why us:** BAN + BDNB + DVF + Hub'Eau + PVGIS mashup in 3D = their exact
  editorial line; historical OpenCage backlink to confinia already exists.
- **Action when ready:** short EN pitch (what it is, the open datasets, the
  live URL) proposing a Geomob Paris lightning talk or a blog feature. Rule 5:
  pitch only what is live. Speaking = Clement in person — his call on the
  identity-mixing trade-off (a geo talk is portfolio-positive, distinct from
  the LinkedIn concern).
- **Instance note:** en.osm.town is the OSM-themed Mastodon instance — the
  fallback (or complement) if the mapstodon.space approval stalls.

### Timely hooks (use within days of the trigger)
- **Cash Investigation (eau potable):** the SISPEA rendement block (#171) is
  live — post angle: « Vérifiez le rendement d'eau potable de votre commune ».
- **BAN vs Google threads** (e.g. Marc Gavanier's post): page comment, one
  sentence + link, sovereignty angle.

## Rules that apply everywhere

- Under-promise (rule 5): announce only what is live; no roadmap promises.
- French style (rule 8): no em dash, no space before `,` or `:`.
- Every post: timestamp in LAUNCH.md's posting log (threshold window ends
  **2026-08-19**; thresholds in BUSINESS.md §8 are fixed).
- Replies to comments: within hours if possible — early reply speed is the
  only reach lever we control.
