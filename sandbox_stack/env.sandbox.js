// Sandbox OIDC config, mounted over /srv/env.js in the sandbox-frontend
// container so the shared frontend image targets the isolated realm.
window.ECO_REALM = "sandbox-ecobuilding";
window.ECO_CLIENT = "ecobuilding-web";
