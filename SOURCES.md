# EcoBuilding — open-data sources

Every dataset the product uses or could use, with its granularity, licence and
status. Companion to [DATA.md](DATA.md) (how each is loaded/updated) and the
buyer roadmap [#192](https://github.com/confinia/ecobuilding/issues/192).

Legend: **LIVE** = in production · **PLANNED** = issue filed · **CANDIDATE** =
assessed, not scheduled · **BLOCKED** = no usable open access found.

---

## 1. In production (LIVE)

| Domaine | Source | Granularité | Licence | Ce qu'on en tire |
|---|---|---|---|---|
| Adresses | **BAN** (api-adresse / Géoplateforme) | adresse | Licence Ouverte | géocodage, reverse au clic ([#152](https://github.com/confinia/ecobuilding/issues/152)) |
| Bâtiments | **BDNB** (CSTB) API + tuiles MVT | bâtiment groupe | LO 2.0 | DPE, année, hauteur, matériaux, 3D |
| DPE officiel | **ADEME Observatoire DPE** (`dpe03existant`) | logement | LO | n° DPE, coûts €/an, isolation, systèmes ([#189](https://github.com/confinia/ecobuilding/issues/189)) |
| Risques | **Géorisques** (BRGM) | commune/point | LO | inondation, argiles, seisme, ICPE… |
| Prix immobiliers | **DVF géolocalisé** (DGFiP/Etalab) | parcelle | LO 2.0 | ventes de la parcelle, médianes commune ([#162](https://github.com/confinia/ecobuilding/issues/162)) |
| Eau souterraine | **Hub'Eau piézométrie** (ADES/BRGM) | station | LO | profondeur de nappe ([#119](https://github.com/confinia/ecobuilding/issues/119)) |
| Eau potable | **SISPEA** via Hub'Eau | commune | LO | rendement réseau, prix ([#171](https://github.com/confinia/ecobuilding/issues/171)) |
| Solaire | **PVGIS** (JRC) | point | © UE | productible kWh/kWc ([#119](https://github.com/confinia/ecobuilding/issues/119)) |
| Fiscalité | **DGFiP fiscalité directe locale** | commune | LO | taux TFB, TEOM ([#193](https://github.com/confinia/ecobuilding/issues/193)) |
| Écoles | **Annuaire de l'éducation** (MENJ) | établissement | LO | établissements < 2 km ([#194](https://github.com/confinia/ecobuilding/issues/194)) |
| Photos | **Panoramax** | photo | CC-BY-SA | vue au sol dans la fiche |
| Fond de carte | **OpenFreeMap / OpenMapTiles** | tuiles | ODbL (OSM) | basemap 3D |
| GeoIP | **dbip-country-lite** | pays | CC-BY | pays visiteur (métrique) |

## 2. Santé — la piste « bien-être du lieu de vie » (CANDIDATE)

Un acheteur demande « y a-t-il un médecin, une pharmacie, un hôpital près
d'ici ? » — c'est un critère de choix aussi fort que l'école, et la France
publie tout en open data.

| Source | Contenu | Granularité | Licence | Verdict |
|---|---|---|---|---|
| **Annuaire santé (CNAM/ameli)** — vérifié sur data.gouv.fr | professionnels de santé : spécialité, adresse, **tarifs et secteur (1/2)**, conventionnement | praticien (adresse) | LO | **Le meilleur candidat** : médecin traitant, spécialistes, dentiste, kiné à proximité + « secteur 1 » = reste à charge faible |
| **FINESS** (extraction du fichier des établissements) | hôpitaux, cliniques, EHPAD, laboratoires, pharmacies | établissement | fr-lo | Complément naturel : temps/distance jusqu'à l'hôpital le plus proche |
| **BPE** (INSEE, base permanente des équipements) | comptages d'équipements de santé par commune | commune/IRIS | LO | Contexte : densité médicale de la commune |
| **APL** (DREES, accessibilité potentielle localisée) | indicateur officiel de **désert médical** (consultations/an/habitant accessibles) | commune | LO | Le chiffre qui répond vraiment à « désert médical ou pas » |
| **Qualité de l'air** (Geod'air / Atmo) | PM2.5, NO₂, indice ATMO | station / commune | LO | Santé environnementale, complète les risques |
| **Radon** (IRSN) | potentiel radon par commune | commune | LO | Déjà partiellement visible via Géorisques |
| Bruit (PEB aéroports, cartes de bruit) | exposition sonore | zone | LO | **BLOCKED** : pas d'API nationale, fichiers départementaux ([#192](https://github.com/confinia/ecobuilding/issues/192)) |

⚠ Cadre : ces données décrivent l'**offre de soins autour du bâtiment**, jamais
une personne. Aucune donnée de santé individuelle n'entre dans le produit
(RGPD : les praticiens sont des professionnels référencés publiquement).

## 3. Autres pistes acheteur (roadmap [#192](https://github.com/confinia/ecobuilding/issues/192))

| Domaine | Source | Statut |
|---|---|---|
| Internet / fibre | **ARCEP Ma connexion internet** | PLANNED — pas d'API sans clé, import de fichiers requis |
| Transports | **GTFS national** (transport.data.gouv.fr) | CANDIDATE — arrêt le plus proche, lignes |
| Revenus / salaires | **INSEE Filosofi**, base salaires | CANDIDATE — revenu médian, contexte de solvabilité |
| Commune | **INSEE**, comptes des communes (DGFiP), **RNE** (élus) | CANDIDATE — population, dette/habitant, maire |
| Copropriété | **RNIC** | CANDIDATE — lots, syndic, copro en difficulté |
| Commerces / services | **BPE** (INSEE) | CANDIDATE — équipements par commune |
| Entreprises | **SIRENE** | PARKED — signal acheteur faible |
| Cadastre | **API Carto / Etalab** | LIVE indirectement (via DVF parcelle) ; pas d'adresses dedans |

## 4. Europe / USA (expansion, [#118](https://github.com/confinia/ecobuilding/issues/118))

| Pays | Équivalents ouverts | Verdict |
|---|---|---|
| Pays-Bas | EP-Online (labels) + BAG (bâtiments/adresses) | Meilleur analogue du couple BDNB+BAN |
| Angleterre / Galles | EPC register ouvert + **HM Land Registry Price Paid** | Hook réglementaire (MEES) + prix ouverts |
| Danemark / Irlande | BBR + énergimærke / SEAI BER | Sérieux candidats |
| Allemagne | — | BLOCKED : pas de registre EPC public |
| USA | HMDA, FHFA, HUD FMR, Census/ACS, EIA/NREL, FEMA/NFIP, footprints | Pas de registre EPC national ; parcelles/prix éclatés en ~3 000 comtés → wedge NYC (PLUTO, ACRIS, LL84) |
| Europe (solaire) | **PVGIS** | Déjà utilisé, couvre toute l'Europe |

## 5. Règles d'usage

- **Attribution obligatoire** (LO, ODbL, CC-BY-SA) : affichée dans l'app et
  dans l'annexe de traçabilité de chaque fiche PDF.
- **Aucune donnée personnelle** : le produit décrit des bâtiments et une offre
  de services, jamais des habitants.
- **Granularité affichée honnêtement** : adresse ≠ commune. Une donnée
  communale (fiscalité, eau, APL) est étiquetée comme telle.
- **Dégradation gracieuse** : toute source indisponible renvoie `None` et
  disparaît de la fiche — jamais de valeur inventée.
