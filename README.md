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
| [DEV.md](DEV.md) | Architecture, deploy, observability, conventions |
| [DATA.md](DATA.md) | Datasets: how each is loaded, where it lives, how it is updated |
| [SOURCES.md](SOURCES.md) | Open-data inventory: live, planned, candidate (incl. health, EU/US) |
| [COMMUNICATION.md](COMMUNICATION.md) | Posting playbook: channel URLs, identities, titles, etiquette |
| [PRICING.md](PRICING.md) | Pricing grid, rules, decision history, where each number lives |
| [TEST_CREEM.md](TEST_CREEM.md) | Payment validation runbook (Creem Test Mode — rule 21) |
| [e2e/README.md](e2e/README.md) | Real-browser signup + payment journey (Selenium IDE + CDP helper), verified against Creem |
| [BUSINESS.md](BUSINESS.md) | Market analysis, strategy, decision log |
| [TODO.md](TODO.md) | Actions (business + product) |

Quickstart: `docker compose up --build` → frontend on :8011, API docs on
:8010/v1/docs. Deploy: `./deploy/deploy.sh`.

## Licence

[GNU AGPL-3.0](LICENSE) — toute personne qui exécute une version modifiée de ce
logiciel accessible par le réseau doit en publier les sources. Cohérent avec un
produit entièrement bâti sur des données publiques ouvertes.

## Dépôts liés

- [confinia/ecobuilding-mobile](https://github.com/confinia/ecobuilding-mobile) —
  applications iOS et Android, AGPL également. Séparé pour des raisons de cycle
  de vie : compilations signées, magasins, versions installées qui survivent des
  mois à leur serveur.

La stratégie commerciale et la tarification vivent dans un dépôt privé : ce qui
est ouvert, c'est le logiciel, pas le plan d'affaires.
