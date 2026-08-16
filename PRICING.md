# EcoBuilding — PRICING

The single source of truth for what customers pay, why, and where each number
lives in the code. Change a price HERE first, then in the constants listed in
§4 — a value that appears on the offers page but not in `_usage_cost()` is a
bug, and the test suite fails on the mismatch.

Rationale and market reasoning stay in [BUSINESS.md](BUSINESS.md); the no-risk
payment test procedure is in [TEST_POLAR.md](TEST_POLAR.md).

---

## 1. Current grid (v3, 2026-08-16)

| Palier | Fiches PDF / mois | Prix | Qui |
|---|---|---|---|
| **Découverte** (sans compte) | **3** | 0 € | visiteur anonyme, par IP |
| **Compte gratuit** | **10** + clé API | 0 € | utilisateur inscrit (Keycloak) |
| **Pro** (paiement à l'usage) | **10 offertes**, puis 0,49 € la fiche | **plafond 99 €/mois** | abonné Polar |
| **Entreprise / on-premise / marque blanche** | illimité | sur devis (dès 10 k€/an) | contrat annuel |

**Gratuit et illimité pour tous :** carte 3D, recherche d'adresse,
autocomplétion, appels API bruts (`/lookup`, `/buildings`, `/reverse`).
Seule la **fiche PDF** est facturée.

Points de repère : 30 fiches = 9,80 € · 100 fiches = 44,10 € · le plafond de
99 € est atteint à **212 fiches**, tout ce qui suit est inclus.

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
| 2026-08-16 | **v3** | **3 / 10 gratuites, puis 0,49 € la fiche, plafond 99 €, sans socle** | le checkout Polar était illisible ; démarrer de très bas prime sur le MRR garanti |

**Conséquence assumée de la v3 :** sans socle, un compte Pro inactif rapporte
0 €. Le nombre de comptes ne mesure donc rien : **seul le volume de fiches
compte**. Si beaucoup d'abonnés restent sous 10 fiches/mois, la première
correction à envisager est de baisser le nombre de fiches offertes ou de
réintroduire un socle — pas de toucher au plafond, qui est l'argument de vente.

## 4. Où vivent les nombres (à changer ensemble)

| Nombre | Code | Fichier |
|---|---|---|
| 0,49 € la fiche | `PRICE_PER_FICHE_EUR` | `api/app/main.py` |
| 10 fiches offertes (Pro) | `INCLUDED_FICHES` | `api/app/main.py` |
| 3 fiches sans compte | `ANON_MONTHLY_REPORTS` | `api/app/main.py` |
| 10 fiches compte gratuit | `FREE_ACCOUNT_REPORTS` | `api/app/main.py` |
| plafond 99 €/mois | `MONTHLY_CAP_EUR` | `api/app/main.py` |
| prix unitaire Polar (49 c) + plafond (9900 c) | `UNIT_CENTS`, `CAP_CENTS` | `deploy/polar-setup.sh` |
| grille affichée + simulateur | cartes `.tier` et script | `frontend/site/offres.html` |

Toutes les valeurs sont surchargeables par variable d'environnement : une
correction de prix est un changement de config, pas un déploiement de code.

## 5. Ce qui est vérifié automatiquement

- `test_pro_payg_curve` : la courbe (0 / 10 offertes / 30 / 212 / plafond).
- `test_payg_pricing_is_consistent_everywhere` : la page, les constantes du
  serveur et le script Polar citent **les mêmes nombres**, et le mot
  « crédit » n'apparaît plus côté client.
- `deploy/e2e-usage.sh` (CI, rule 19) : consommation réelle → compteur local →
  `/v1/usage` → meter Polar, avec les prix **lus depuis l'API** pour qu'un
  changement de tarif ne casse pas le test.
- `deploy/e2e-signup.sh` (CI) : les paliers gratuits sont réellement appliqués
  et l'épuisement propose l'étape suivante.
