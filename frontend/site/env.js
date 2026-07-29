// Runtime OIDC config, loaded before app.js. Production ships this file as-is
// (realm "confinia"). The isolated sandbox stack mounts an override over
// /srv/env.js (see sandbox_stack/env.sandbox.js) to point the SAME frontend
// image at the sandbox-ecobuilding realm — no separate build.
window.ECO_REALM = "confinia";
window.ECO_CLIENT = "ecobuilding-web";
