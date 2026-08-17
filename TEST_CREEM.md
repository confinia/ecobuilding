# TEST_CREEM — valider l'inscription et le paiement sans risque (v4)

Fournisseur de paiement : **creem.io** (règle 21 — MoR européen, Estonie).
**Test Mode uniquement** pour l'instant : clés `creem_test_…`,
`test-api.creem.io`, environnement isolé de la production Creem. La
production EcoBuilding n'a AUCUNE configuration de paiement (rule 7) :
`/v1/pro/checkout` y répond 503 et le bouton « Passer Pro » y est masqué.

L'historique Polar (v3, metering) est dans [TEST_POLAR.md](TEST_POLAR.md) —
conservé comme archive ; le code Polar meurt quand le parcours Creem est
prouvé de bout en bout.

## Mise en route (une fois)

1. Dashboard Creem (Test Mode) → **Developers → API keys** → copier la clé
   `creem_test_…`.
2. Créer/adopter les produits paliers :
   `CREEM_API_KEY=creem_test_… ./deploy/creem-setup.sh`
   Le script **adopte** le produit « ecobuilding » créé à la main dans le
   dashboard (au prix récurrent correspondant) et ne crée que les paliers
   manquants : Pro S 9 € · Pro M 29 € · Pro L 99 € (grille v4, PRICING.md).
3. Coller le bloc imprimé (`CREEM_API_KEY`, `CREEM_PRODUCTS_JSON`,
   `CREEM_WEBHOOK_SECRET`) dans `sandbox_stack/secrets.env`, puis
   `./deploy/sandbox.sh`.
4. (Optionnel) Dashboard → Developers → Webhook →
   `https://sandbox.api.ecobuilding.confinia.io/v1/pro/webhook`.
   Le webhook rend la bascule instantanée ; sans lui, la **réconciliation
   par e-mail** (`/customers?email=…` → abonnements actifs) active le compte
   en moins de 60 s — même philosophie que #228.

## Payer avec une carte de test

1. https://sandbox.ecobuilding.confinia.io → créer un compte (organisation
   obligatoire) → « Passer Pro » (Pro S en un clic) ou /offres.html pour
   choisir un palier (`/?gopro=s|m|l`).
2. Carte de test **Creem** : `4111 1111 1111 1111`, date future, CVC
   quelconque. (Refus simulables : `4507 9900 0000 0028` déclinée,
   `…0010` provision insuffisante, `…0044` CVC faux.)
3. Retour sur `?pro=success` ; le panneau compte affiche le palier.

## Vérification automatisée

`./e2e/run.sh` (voir [e2e/README.md](e2e/README.md)) joue tout le parcours
dans un vrai Chromium et relit la plateforme de paiement pour détecter toute
contradiction entre la grille annoncée (`/v1/pricing`) et les produits réels.
