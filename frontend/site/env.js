// Runtime OIDC config, loaded before app.js. Production ships this file as-is
// (realm "confinia"). The isolated sandbox stack mounts an override over
// /srv/env.js (see sandbox_stack/env.sandbox.js) to point the SAME frontend
// image at the sandbox-ecobuilding realm — no separate build.
// URL CANONIQUE de Keycloak, absolue et jamais relative. Keycloak est partagé
// par les deux couleurs (blue/green) et son KC_HOSTNAME est figé sur ce
// domaine : appeler « /auth » en relatif depuis staging posait le cookie de
// session sur staging.ecobuilding.confinia.io puis renvoyait un formulaire
// dont l'action pointait vers ecobuilding.confinia.io — « Cookie introuvable »,
// connexion impossible sur staging. L'URI de redirection staging est déjà
// autorisée sur le client, donc le retour se fait bien vers l'environnement
// d'origine.
window.ECO_AUTH_URL = "https://ecobuilding.confinia.io/auth";
window.ECO_REALM = "confinia";
window.ECO_CLIENT = "ecobuilding-web";
window.ECO_PRO_ENABLED = false;   // hide "Passer Pro" in prod until the plan is live (RULES.md #7)
