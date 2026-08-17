# TEST_POLAR — valider l'inscription et le paiement sans risque

**Aucun euro réel ne peut être encaissé** : la production n'a AUCUNE
configuration Polar (0 variable `POLAR_*`), donc `/v1/pro/checkout` y répond
503 et le bouton « Passer Pro » y est masqué (`ECO_PRO_ENABLED=false`,
rule 7). Tout le test de paiement se fait sur le **sandbox**.

## L'environnement de test EST l'image de production

`sandbox.ecobuilding.confinia.io` fait tourner **exactement la même image**
que la production (vérifié 2026-08-16 : `ImageID cea98525539f5711` des deux
côtés). Seule la CONFIGURATION diffère :

| | Production | Sandbox |
|---|---|---|
| Image API | `ecobuilding-api:latest` | **la même** |
| Réalm Keycloak | `confinia` | `sandbox-ecobuilding` (isolé) |
| Données (leads, clés, usage) | volume prod | volume sandbox |
| Polar | **aucun** (503) | `sandbox-api.polar.sh` |
| Bouton « Passer Pro » | masqué (rule 7) | visible |

Donc : pour tester un paiement, on utilise le sandbox ; le code exercé est
celui qui partira en production.

## Procédure complète (validée 2026-08-16)

### 1. Rien à préparer : le webhook n'est plus nécessaire (#228)

Le passage en Pro ne dépend **plus** d'un webhook. `_pro_active()` lit d'abord
l'état local puis, si le compte n'est pas actif, interroge Polar
(`GET /v1/subscriptions?external_customer_id=…&active=true`, en cache 60 s).
Un abonnement payé devient donc actif **en moins d'une minute sans aucune
configuration**. Déclarer le webhook (dashboard → Settings → Webhooks, format
Raw, secret dans `POLAR_WEBHOOK_SECRET`) ne fait que rendre le basculement
instantané — c'est une optimisation, pas un prérequis.

### 2. Payer avec une carte de test

1. Ouvrir https://sandbox.ecobuilding.confinia.io et créer un compte
   (le champ **Organisation est obligatoire** : sans lui, Keycloak refuse la
   connexion avec « Account is not fully set up »).
2. Cliquer **« Passer Pro »** → redirection vers le checkout hébergé Polar
   (URL en `sandbox.polar.sh/checkout/…`).
3. Carte de test Stripe : **4242 4242 4242 4242**, date future quelconque,
   CVC quelconque, code postal quelconque. Aucun argent réel n'est débité.
4. Retour sur l'app (`?pro=success`).

### 3. Vérifier que le plan a basculé

```sh
# côté app : le badge du compte affiche « Pro » au lieu des fiches restantes
curl -H "Authorization: Bearer <token>" \
  https://sandbox.ecobuilding.confinia.io/api/v1/usage | jq '.plan, .cost_eur'
# -> "pro", 9.0
```
Le webhook `subscription.created` écrit le statut dans `pro.json` ; toutes les
clés API du compte deviennent « pro » automatiquement (le plan suit le COMPTE).

## Ce qui est déjà prouvé automatiquement (CI, rule 19)

| Étape | Preuve |
|---|---|
| Inscription → quota compte | `deploy/e2e-signup.sh` : compte jetable, 30 fiches, décompte sur le compte, 429 avec upsell |
| Consommation → facturation | `deploy/e2e-usage.sh` : crédits locaux = crédits ingérés dans le meter Polar (53 = 53) |
| Objets Polar | meter `b8afa9bb…` (somme des fiches) + produit `93fbd58a…` (0,49 €/fiche, `cap_amount` 9900, **sans socle** — v3) ; l'ancien couple v2 `aba28fdd…`/`a908bb90…` (base 9 € + 1 c/crédit) est **archivé** 2026-08-17 |
| Checkout | URL de checkout sandbox obtenue via l'API avec un vrai compte (2026-08-16) |
| Passage Pro | réconciliation testée unitairement (bascule + cache + échec sans octroi d'accès) ; la validation grandeur nature demande un vrai paiement carte, seule étape non automatisable |

## Bugs trouvés en faisant ce test (et corrigés)

- `422 metadata` : Polar refuse les valeurs de metadata vides ; on envoyait
  `org: ""` pour tout utilisateur sans organisation → **tous** ces checkouts
  échouaient. Corrigé ([#219](https://github.com/confinia/ecobuilding/pull/219)).
- Bouton « Passer Pro » visible en production malgré `ECO_PRO_ENABLED=false`
  (le rafraîchissement du quota le démasquait). Corrigé
  ([#218](https://github.com/confinia/ecobuilding/pull/218)).
- Token d'organisation Polar : interdit d'envoyer `organization_id` (422).
- Realm Keycloak : `organization` est un attribut REQUIS ; sans lui, toute
  connexion échoue avec « Account is not fully set up ».
- Polar refuse de créer un abonnement payant par API (« the customer should go
  through a checkout ») et la création de client demande un scope absent : la
  saisie de carte est **la seule étape qui exige un humain**, d'où la
  réconciliation (#228) plutôt qu'une dépendance au webhook.
