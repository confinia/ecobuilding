# EcoBuilding

**La carte d'identité écologique de chaque bâtiment français, en 3D.**

Type an address → see the building in 3D (MapLibre) with its energy class (DPE),
rental-ban countdown (loi Climat & Résilience), natural risks, materials and
solar potential — all from open data (BDNB/CSTB, BAN, Géorisques).

- Live: https://ecobuilding.confinia.io
- Public API + docs: https://ecobuilding.confinia.io/api/v1/docs
- Monitoring: https://ecobuilding.confinia.io/grafana

| Doc | Purpose |
|---|---|
| [SOURCES.md](SOURCES.md) | Open-data inventory: live, planned, candidate (incl. health, EU/US) |
| [TEST_SUBSCRIPTION.md](TEST_SUBSCRIPTION.md) | Sign-up / sign-in journey (Keycloak) |
| [e2e/README.md](e2e/README.md) | Real-browser signup journey (Selenium IDE + CDP helper) |
| [api/app/main.py](api/app/main.py) | The API itself — every route is documented inline |

Operational documentation (architecture, deployment, security posture, roadmap,
pricing) lives in a private repository: **the code is open, the business is
not**. Everything needed to run this software is here; everything describing how
the business is run is not.

Quickstart: `docker compose up --build` → frontend on :8011, API docs on
:8010/v1/docs. Deploy: `./deploy/deploy.sh`.

## Licence

[GNU AGPL-3.0](LICENSE) — toute personne qui exécute une version modifiée de ce
logiciel accessible par le réseau doit en publier les sources. Cohérent avec un
produit entièrement bâti sur des données publiques ouvertes.

**L'AGPL ne convient pas à votre usage ?** Pour intégrer EcoBuilding à un
produit propriétaire, le livrer à vos clients, ou exploiter une version modifiée
en service sans publier vos modifications, une **licence commerciale** est
disponible : les droits étant détenus en un seul endroit, des conditions autres
que l'AGPL peuvent être accordées. Voir [NOTICE](NOTICE), puis écrire à
clement@igonet.fr.

## Dépôts liés

- [confinia/ecobuilding-mobile](https://github.com/confinia/ecobuilding-mobile) —
  applications iOS et Android, AGPL également. Séparé pour des raisons de cycle
  de vie : compilations signées, magasins, versions installées qui survivent des
  mois à leur serveur.

La stratégie commerciale et la tarification vivent dans un dépôt privé : ce qui
est ouvert, c'est le logiciel, pas le plan d'affaires.
