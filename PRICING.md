# EcoBuilding — PRICING

The single source of truth for what customers pay, why, and where each number
lives in the code. Change a price HERE first, then in the constants listed in
§4 — a value that appears on the offers page but not in `_usage_cost()` is a
bug, and the test suite fails on the mismatch.

Rationale and market reasoning stay in [BUSINESS.md](BUSINESS.md); the no-risk
payment test procedure is in [TEST_POLAR.md](TEST_POLAR.md).

---

## 1. Current grid (v4, 2026-08-17)

| Palier | Fiches PDF / mois | Prix | Qui |
|---|---|---|---|
| **Découverte** (sans compte) | **3** | 0 € | visiteur anonyme, par IP |
| **Compte gratuit** | **10** + clé API | 0 € | utilisateur inscrit (Keycloak) |
| **Pro S** | **30** | **9 €/mois** | abonné Creem |
| **Pro M** | **100** | **29 €/mois** | abonné Creem |
| **Pro L** | **illimité** (usage raisonnable) | **99 €/mois** | abonné Creem |
| **Entreprise / on-premise / marque blanche** | illimité | sur devis (dès 10 k€/an) | contrat annuel |

**Gratuit et illimité pour tous :** carte 3D, recherche d'adresse,
autocomplétion, appels API bruts (`/lookup`, `/buildings`, `/reverse`).
Seule la **fiche PDF** est comptée.

Tous les paliers sont **sans engagement**, au mois le mois. Pro L joue le rôle
du plafond v3 : la facture ne dépasse jamais 99 €.

## 2. Règles qui ne se négocient pas

1. **L'unité facturée est l'unité que le client comprend.** La v2 facturait des
   « crédits » (1 fiche = 49 crédits à 0,01 €) : le checkout Polar affichait
   « credits €0.01/unit » et laissait croire qu'une fiche coûtait un centime.
   Jamais de granularité interne sur une page de paiement.
2. **Le plafond est un engagement**, pas une estimation : il est appliqué côté
   serveur (`_usage_cost`) ET côté Polar (`cap_amount` sur le prix mesuré).
3. **Un utilisateur n'est jamais bloqué sans issue** : atteindre une limite
   renvoie un 429 qui propose l'étape suivante et l'adresse de support.
4. **Le plan suit le COMPTE**, pas la clé : toutes les clés d'un abonné
   deviennent Pro, rien à resynchroniser.
5. **Rien n'est facturé en production tant que RULES.md #7 n'est pas atteint** :
   la prod n'a aucune configuration Polar, le bouton Pro y est masqué.

## 3. Historique des décisions

| Date | Version | Décision | Raison |
|---|---|---|---|
| 2026-08-16 | v1 | 500 crédits offerts, puis 0,02 €/crédit, plafond 99 € | premier jet pay-as-you-go |
| 2026-08-16 | v2a | 0,20 € la fiche dès la première | 500 crédits = 500 PDF offerts, c'était un cadeau, pas une offre |
| 2026-08-16 | v2b | 9 €/mois + 50 fiches incluses, puis 0,49 € | viser l'abonnement (MRR) plutôt que des transactions |
| 2026-08-16 | v3 | 3 / 10 gratuites, puis 0,49 € la fiche, plafond 99 €, sans socle | le checkout Polar était illisible ; démarrer de très bas prime sur le MRR garanti |
| 2026-08-17 | **v4** | **paliers fixes : Pro S 9 € (30 fiches) · Pro M 29 € (100) · Pro L 99 € (illimité fair-use)** | bascule vers **Creem** (MoR **européen** — souveraineté, facture émise par une entité UE, pas besoin de créer une société tout de suite) ; Creem ne fait pas de facturation à l'usage, et l'opérateur a choisi les paliers plutôt que les packs prépayés (subscription-first) |

**Conséquence assumée de la v4 :** un socle est réintroduit (ce que la v3
avait retiré) — c'est le prix de la souveraineté (MoR européen) et de la
simplicité (pas de metering chez Creem). En échange, chaque abonné actif
redevient du MRR mesurable. Le point à surveiller est l'inverse de la v3 :
un abonné S qui consomme 2 fiches/mois paie 4,50 € la fiche — si le churn
s'installe là, envisager un palier XS ou des packs prépayés, pas de toucher
à Pro L qui joue le rôle du plafond.

## 4. Où vivent les nombres (à changer ensemble)

| Nombre | Code | Fichier |
|---|---|---|
| paliers S/M/L (prix + quotas) | `PRO_TIERS` (`PRO_TIERS_JSON` env) | `api/app/main.py` |
| 3 fiches sans compte | `ANON_MONTHLY_REPORTS` | `api/app/main.py` |
| 10 fiches compte gratuit | `FREE_ACCOUNT_REPORTS` | `api/app/main.py` |
| produits Creem (900/2900/9900 c) | `pick_or_create` | `deploy/creem-setup.sh` |
| mapping palier → produit Creem | `CREEM_PRODUCTS_JSON` | `sandbox_stack/secrets.env` |
| grille affichée + simulateur | cartes `.tier` et script | `frontend/site/offres.html` |

Toutes les valeurs sont surchargeables par variable d'environnement : une
correction de prix est un changement de config, pas un déploiement de code.

## 5. Ce qui est vérifié automatiquement

- `test_pro_tier_grid_v4` : la grille (9/29/99, quotas 30/100/illimité) et la
  recommandation de palier par volume.
- `test_tier_pricing_is_consistent_everywhere` : la page, les constantes du
  serveur, PRICING.md et le script Creem citent **les mêmes nombres**, et le
  mot « crédit » n'apparaît plus côté client.
- `deploy/e2e-usage.sh` (CI, rule 19) : consommation réelle → compteur local →
  `/v1/usage` → meter Polar, avec les prix **lus depuis l'API** pour qu'un
  changement de tarif ne casse pas le test.
- `deploy/e2e-signup.sh` (CI) : les paliers gratuits sont réellement appliqués
  et l'épuisement propose l'étape suivante.
- `e2e/run.sh` (navigateur réel, Selenium IDE) : le parcours complet
  inscription → fiche → checkout Polar → passage Pro, PLUS un rapport lu depuis
  `sandbox-api.polar.sh` qui échoue si la grille de Polar (socle, prix
  unitaire, plafond) contredit celle que l'API annonce. C'est ce rapport qui a
  détecté que le produit Polar sandbox était resté en v2 (socle 9 € +
  0,01 €/crédit) après le passage en v3 — corrigé le 2026-08-17 (produit
  `93fbd58a…`, l'ancien archivé).
