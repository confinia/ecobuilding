# e2e — inscription & paiement, dans un vrai navigateur

Ce répertoire joue le parcours qu'un client réel suit pour devenir payant :
il s'inscrit, se connecte, génère une fiche, paie, et son compte bascule en Pro.
Le scénario est un projet **Selenium IDE** (`ecobuilding.side`), rejouable à la
main dans l'extension comme en ligne de commande, et il est doublé d'une
vérification **côté plateforme de paiement** (`payment_report.py` — Creem test mode, règle 21 ; Polar sandbox en héritage).

Les deux moitiés sont nécessaires, et c'est tout l'intérêt du montage :

- le navigateur prouve ce que **voit l'utilisateur** — mais une app peut
  afficher « Pro » sans qu'un centime ait été encaissé ;
- la plateforme de paiement (Creem) prouve ce qui est **réellement facturé** —
  mais un montant correct chez elle ne dit rien de l'accessibilité du parcours.

## Lancer

```sh
cp e2e/.env.example e2e/.env      # puis compléter (voir les commentaires)
./e2e/run.sh
```

Sur la **VM**, ne pas mettre l'`.env` dans le dépôt : chaque déploiement CI
resynchronise l'arbre et **efface les fichiers non suivis** (vécu deux fois).
Le poser hors du dépôt et le passer explicitement :

```sh
ENVFILE=~/.config/ecobuilding-e2e.env ./e2e/run.sh
```

Aucune installation : le navigateur et le lanceur tournent en conteneurs
(`selenium/standalone-chromium` + `node`), avec podman ou docker.

Les résultats atterrissent dans `e2e/results/<horodatage>/` :
`report.md` (lisible), `polar-report.json`, les résultats JSON de Selenium,
`selenium.log`, et une capture d'écran par test échoué.

## Ce que couvre le scénario

| Test | Preuve |
|---|---|
| 01 · inscription | le bouton « Créer un compte » est visible ([#215](https://github.com/confinia/ecobuilding/issues/215)), le formulaire Keycloak accepte le compte, l'écran de vérification e-mail apparaît |
| 06 · organisation obligatoire | un formulaire sans organisation est refusé **sur le formulaire**, et non plus par un « Account is not fully set up » à la connexion suivante |
| 02 · connexion | retour sur l'app authentifié, la pastille porte bien l'adresse du compte |
| 03 · fiche PDF | le parcours carte → bâtiment → fiche fonctionne et consomme le quota du COMPTE |
| 04 · paiement | checkout Polar sandbox rempli avec la carte de test Stripe, retour sur `?pro=success` |
| 05 · plan Pro | le panneau compte annonce Pro |
| rapport Polar | le produit, l'abonnement et la commande existent **chez Polar**, et sa grille tarifaire correspond à celle que l'API annonce |

## La seule étape simulée

Le realm impose `verifyEmail=true`. Après l'inscription, Keycloak envoie un
courriel de vérification à une **vraie** adresse externe, qu'aucune CI ne peut
ouvrir. `run.sh` franchit donc ce mur par l'API admin (`emailVerified=true`)
entre les deux suites, et le rapport le signale explicitement. C'est la seule
étape du parcours qui ne soit pas jouée dans le navigateur : ne jamais la
présenter comme une preuve que l'envoi de courriel fonctionne — cette preuve-là
est apportée séparément par `deploy/kc-smtp.sh` (pré-vol SMTP) et par le test
manuel de « mot de passe oublié » ([#229](https://github.com/confinia/ecobuilding/issues/229)).

Pour supprimer même cette simulation, il faudrait router le SMTP du realm vers
une boîte de test lisible par API (Mailpit) — au prix de casser le test manuel
de courriel en sandbox. Le compromis actuel est délibéré.

## Fragilité assumée : le DOM du checkout Creem

Le parcours payant traverse une page **que nous ne contrôlons pas** (checkout
hébergé Creem, en deux étapes : coordonnées puis carte via un SDK Yuno en
iframe `card_form`). Précautions :

- sélecteurs par `name`/`title`/placeholder uniquement — jamais d'id générés ;
- le champ « Cardholder Name » est **ajouté dynamiquement** au document
  principal une fois la carte reconnue : le scénario l'attend explicitement
  (sans cette attente : « This field is required » et paiement muet) ;
- tous ces sélecteurs vivent dans `.env`, donc une dérive du DOM Creem se
  corrige en une ligne, sans toucher au scénario.

Si l'étape 04 échoue, regarder d'abord la capture d'écran dans
`results/<horodatage>/screenshots/` avant de suspecter notre code.

## Sécurité

`run.sh` refuse `ECO_ENV=production`. Ce n'est pas qu'une convention : le
scénario saisit un numéro de carte, et la production n'a de toute façon aucune
configuration Polar ([RULES.md](../RULES.md) #7), donc `/v1/pro/checkout` y
répond 503 et le bouton « Passer Pro » y est masqué.
