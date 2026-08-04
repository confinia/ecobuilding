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
| [BUSINESS.md](BUSINESS.md) | Market analysis, strategy, decision log |
| [TODO.md](TODO.md) | Actions (business + product) |

Quickstart: `docker compose up --build` → frontend on :8011, API docs on
:8010/v1/docs. Deploy: `./deploy/deploy.sh`.
