# EcoBuilding — Issue tracker

Living status of every open (and recently shipped) GitHub issue, updated each
working session (rule 15). Lifecycle: **filed → PR open → merged (on staging) →
promoted (production) → closed**. Environments (rule 12):
[production](https://ecobuilding.confinia.io) ·
[staging](https://staging.ecobuilding.confinia.io) ·
[sandbox](https://sandbox.ecobuilding.confinia.io).

Last updated: 2026-08-16 (triage + promote).

## Environment state

| Environment | Runs | Note |
|---|---|---|
| [Production](https://ecobuilding.confinia.io) · API [api.ecobuilding.confinia.io](https://api.ecobuilding.confinia.io) | `main` @ `dda0a28` — **promoted 2026-08-17** (green stack; blue kept for rollback) | Includes [#113](https://github.com/confinia/ecobuilding/issues/113), [#119](https://github.com/confinia/ecobuilding/issues/119), [#121](https://github.com/confinia/ecobuilding/issues/121), [#125](https://github.com/confinia/ecobuilding/issues/125); shared render container rebuilt (marker) |
| [Staging](https://staging.ecobuilding.confinia.io) · API `staging.api.ecobuilding.confinia.io` | candidate = blue (pre-promote prod) | **Routing fixed 2026-08-11** (platform PR [#3](https://github.com/confinia/platform/pull/3)) — validate-on-staging gate restored |
| [Sandbox](https://sandbox.ecobuilding.confinia.io) · API `sandbox.api.ecobuilding.confinia.io` | sandbox stack (:8030) | Publicly routed again (platform PR [#3](https://github.com/confinia/platform/pull/3)) |

## Open / recently shipped issues

| Issue | Status | Next step |
|---|---|---|
| **Parcours e2e Creem VERT de bout en bout** | **Mergé main → staging 2026-08-18** (PR [#235](https://github.com/confinia/ecobuilding/pull/235)) : inscription Keycloak → vérif e-mail (API admin, simulée et documentée) → connexion → fiche → « Passer Pro » → checkout Creem traversé (helper CDP `e2e/checkout-creem.mjs` — la page tierce rejette WebDriver, 28 runs d'itérations dans git) → paiement 9 € encaissé (`order_id` réel) → réconciliation → **panneau compte Pro** → rapport plateforme sans contradiction. Fixes embarqués : `customer:{email}` au checkout (400 sinon), réconciliation `/customers/{id}/subscriptions` (search refuse customer_id), fiche accessible sans WebGL2 (`safeMap`) | Prêt pour **promotion prod** (la v4 y reste inerte : aucun fournisseur configuré) |
| e2e Selenium + bascule **Creem** (règle 21) + **pricing v4** | **Mergé main → staging 2026-08-17** (PR [#234](https://github.com/confinia/ecobuilding/pull/234)) : harnais e2e navigateur (`e2e/`, suite inscription verte 3×), fournisseur = Creem (MoR UE, **Test Mode uniquement**, prod sans config — rule 7), grille v4 paliers S 9 €/30 · M 29 €/100 · L 99 €/illimité ; produit Polar v2 périmé détecté par le rapport e2e puis remplacé/archivé | **Opérateur** : clé `creem_test_…` → `./deploy/creem-setup.sh` → coller dans `sandbox_stack/secrets.env` → `./deploy/sandbox.sh` ; ensuite je sonde le checkout Creem et rejoue le paiement e2e |
| [#232](https://github.com/confinia/ecobuilding/issues/232) Entrée API dédiée (`api.` / `staging.api.` / `sandbox.api.`) | **In production 2026-08-17** (PR [#233](https://github.com/confinia/ecobuilding/pull/233)) : chaque hôte API réutilise le port d'entrée de son environnement (13000/13300/13400) — un port API dédié en prod obligerait l'edge plateforme à connaître la couleur active, donc de la logique applicative en amont. Vérifié sur la VM : les hôtes API renvoient le JSON FastAPI, l'hôte applicatif la SPA ; les chemins `/api` restent servis (dual-publish, rollback = ne rien faire) | **Fait côté plateforme 2026-08-17** : hôtes API publics en HTTPS, sondes sur `/v1/healthz` (JSON uvicorn, pas de fallback SPA) |
| [#224](https://github.com/confinia/ecobuilding/issues/224) Pricing v3 (facturer la fiche) | **In production 2026-08-16** (PR [#225](https://github.com/confinia/ecobuilding/pull/225)): 3 / 10 gratuites, puis 0,49 € la fiche, plafond 99 € ; plus aucun « crédit » côté client ; [PRICING.md](PRICING.md) est la source de vérité | — |
| [#220](https://github.com/confinia/ecobuilding/issues/220) Clé API introuvable dans l'UI · [#221](https://github.com/confinia/ecobuilding/issues/221) bandeau sandbox · [#222](https://github.com/confinia/ecobuilding/issues/222) marqueur sur le toit | **In production 2026-08-16** (PR [#223](https://github.com/confinia/ecobuilding/pull/223)) ; #221 et #222 fermées | — |
| [#219](https://github.com/confinia/ecobuilding/pull/219) Checkout Polar : metadata vides (422) | **In production 2026-08-16** : bloquait tout utilisateur sans organisation | — |
| Caddy admin 2030 → 13090 (demande plateforme) | **In production 2026-08-16** (PR [#226](https://github.com/confinia/ecobuilding/pull/226)) ; 2030 silencieux, admin dans la bande | — |
| [#215](https://github.com/confinia/ecobuilding/issues/215) Aucun bouton d'inscription visible | **Fixed in production 2026-08-16** (PR [#216](https://github.com/confinia/ecobuilding/pull/216)): l'UI d'auth disparaissait dès qu'un import CDN ou l'init Keycloak échouait; keycloak-js vendorisé same-origin, boutons affichés avant tout `await` avec des URLs Keycloak directes en filet. MapLibre 6.4.0 (web + render alignés, test anti-dérive), mentions « bêta » retirées | Operator: recharger et confirmer visuellement |
| [#212](https://github.com/confinia/ecobuilding/issues/212) Self-service PAYG (contact + parcours d'inscription) | **In production 2026-08-16** (PR [#213](https://github.com/confinia/ecobuilding/pull/213)): contact@ à chaque friction (quota, page 429, fiche PDF, header « Aide », offres), inscription en un clic depuis la page quota + écran de bienvenue, 429 in-app transformé en upsell; **e2e CI du parcours complet** (compte jetable → 30 fiches → décompte sur le COMPTE → 429 avec upsell) | Operator: manual robustification pass |
| [#201](https://github.com/confinia/ecobuilding/issues/201) Polar metering | **Wired to the real Polar sandbox 2026-08-16**: meter `aba28fdd…` + product `a908bb90…` (base 9 € fixe + metered 1 c/crédit, `cap_amount` 9900) créés dans l'org `ecobuilding`; simulation réconciliée **53 crédits locaux = 53 dans le meter Polar** | Checkout → webhook → passage Pro (bouton actif en sandbox) |
| [#206](https://github.com/confinia/ecobuilding/issues/206) Pricing policy v2 (subscription-first) | **In production 2026-08-16** (PRs [#207](https://github.com/confinia/ecobuilding/pull/207), [#210](https://github.com/confinia/ecobuilding/pull/210)): 10 fiches/mois sans compte · 30 avec compte gratuit · Pro 9 €/mois (50 incluses, puis 0,49 €, plafond 99 €) · Entreprise sur devis. Plans attachés au compte Keycloak, quota affiché dans l'app | **Operator:** Polar sandbox Organization Access Token → `deploy/polar-setup.sh` |
| [#208](https://github.com/confinia/ecobuilding/issues/208) Santé à proximité (praticiens, FINESS, APL) | Filed 2026-08-16, sources vérifiées ([SOURCES.md](SOURCES.md) §2) | Next build candidate |
| platform staging edge :13300 | **Live 2026-08-16** (PR [#209](https://github.com/confinia/ecobuilding/pull/209)), dual-published with :13000 | Awaiting the platform edge flip |
| [#201](https://github.com/confinia/ecobuilding/issues/201) Pay-as-you-go pricing + Polar metering | **In production 2026-08-16**, repriced same day (PRs [#202](https://github.com/confinia/ecobuilding/pull/202), [#204](https://github.com/confinia/ecobuilding/pull/204)): **0,20 €/fiche dès la première**, 0,01 €/appel API, plafond 99 € (495 fiches); décision + arithmétique dans BUSINESS.md; e2e metering in CI (rule 19), prices read from the API | **Operator:** create a Polar sandbox **Organization Access Token** (org `ecobuilding` exists, id `cc1b6a73…`), then `POLAR_ACCESS_TOKEN=… ./deploy/polar-setup.sh` → paste POLAR_* into `sandbox_stack/secrets.env`; the CI Polar leg then runs itself |
| [#199](https://github.com/confinia/ecobuilding/issues/199) i18n EN + language switcher · [#200](https://github.com/confinia/ecobuilding/issues/200) Mapillary/Wikimedia street view | Filed 2026-08-16 (deferred by the operator) | Later |
| [#196](https://github.com/confinia/ecobuilding/issues/196) Lead notification email | **In production 2026-08-16** (PR [#197](https://github.com/confinia/ecobuilding/pull/197)); e2e validated on sandbox (`sent: True`, 2 mails to contact@) | — |
| [#193](https://github.com/confinia/ecobuilding/issues/193) + [#194](https://github.com/confinia/ecobuilding/issues/194) Fiscalité locale + écoles | **In production 2026-08-16** (PR [#195](https://github.com/confinia/ecobuilding/pull/195)): TFB 29.58 %, TEOM, 8 écoles < 2 km; loading narration | — |
| [#192](https://github.com/confinia/ecobuilding/issues/192) Buyer-data roadmap | Wave 1 done (taxes, écoles). Fibre ARCEP needs a file import (no keyless API); bruit/PEB needs departmental files | Wave 1b: fibre import; wave 2: transports, revenus, commune |
| [#189](https://github.com/confinia/ecobuilding/issues/189) Near-official DPE fiche depth | **In production 2026-08-16** (PR [#190](https://github.com/confinia/ecobuilding/pull/190)): n° DPE + validité 10 ans, surface, coûts €/an par usage, isolation par poste, systèmes — via BDNB rep-logement → ADEME observatoire, verified live | — |
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

- **Exposer l'ID-RNB à côté de l'identifiant BDNB** (produit + interopérabilité).
  Le [Référentiel National des Bâtiments](https://rnb.beta.gouv.fr/) donne à
  chaque bâtiment un identifiant unique et *permanent* de 12 caractères, et
  c'est lui — pas l'id BDNB — qui sert de **clé pivot entre cadastre, BAN,
  BDNB et ADEME**. Nous clefons aujourd'hui sur l'id BDNB : nos URLs et notre
  API ne sont donc pas jointes au reste de l'écosystème, et un id BDNB peut
  bouger d'une version à l'autre (voir [#28](https://github.com/confinia/ecobuilding/issues/28)).
  À faire : renvoyer `rnb_id` dans `/v1/buildings/{id}`, l'accepter en entrée,
  et l'afficher sur la fiche PDF. Bénéfice commercial : c'est l'identifiant
  que les diagnostiqueurs et les collectivités citent, et c'est le prérequis
  pour parler crédiblement sur le forum GéoCommuns (canal ci-dessous).

- **Fuite de processus Chromium du service render** (fiabilité VM). Des
  processus `chrome` de générations PRÉCÉDENTES du conteneur
  `ecobuilding-render_render_1` survivent à sa recréation (constaté
  2026-08-17 : des chrome vieux de 15 jours alors que le conteneur date de
  23 h ; ~20 orphelins > 1 jour, ~1,5 Go de RSS au total). Piste : Puppeteer
  relancé sans que l'ancien navigateur soit attendu (`browser.close()` absent
  d'un chemin d'erreur), et les processus ré-adoptés hors du cgroup du
  conteneur. À faire : trouver le chemin qui fuit dans `render_stack/server.js`,
  et un garde-fou (pkill des chrome orphelins au démarrage du conteneur).

- **Canal : [Forum GéoCommuns](https://forum.geocommuns.fr)** (Discourse de
  l'écosystème géocommuns : Panoramax 421 sujets, RTK-Centipede 178, RNB 24,
  BAN, base routière). Audience = producteurs et réutilisateurs des données
  exactes que nous consommons, dont des nœuds très centraux de l'open data géo
  français. **Ce n'est pas un canal publicitaire** : y poster une annonce
  produit se retournerait contre nous. Format à tenir : un *retour
  d'expérience de réutilisateur* dans les catégories Panoramax et RNB — ce que
  nous consommons, ce qui a manqué, ce que nous renvoyons — avec le lien vers
  EcoBuilding en signature et non en objet. Prose à rédiger et à faire valider
  avant publication (voir [COMMUNICATION.md](COMMUNICATION.md)).
