/* EcoBuilding frontend — MapLibre GL + EcoBuilding API (/api/v1). */

const API = "/api/v1";

// --- Usage beacon (anonymous, no cookies) ------------------------------------
function track(event, meta) {
  const body = JSON.stringify({ event, meta: meta || null });
  navigator.sendBeacon?.(`${API}/events`, new Blob([body], { type: "application/json" })) ||
    fetch(`${API}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body });
}
track("page_view");

// Payment-mode banner (#221): when the backend is wired to a SANDBOX payment
// provider, say so loudly — a test checkout must never look like a real one.
fetch(`${API}/config`).then((r) => r.ok && r.json()).then((c) => {
  if (!c || c.payment_mode !== "sandbox") return;
  const b = document.createElement("div");
  b.id = "paybanner";
  b.textContent = "Mode paiement SANDBOX — aucun paiement réel n'est encaissé (cartes de test uniquement)";
  document.body.appendChild(b);
  document.body.classList.add("has-paybanner");
}).catch(() => {});

// --- Pricing numbers, read from the API and never hardcoded here ------------
// Every stale number in the UI so far (30 fiches, 9 €/mois) was a copy of a
// server constant that later changed. The API is the only source of truth.
let _pricing = null;
async function ecoPricing() {
  if (_pricing) return _pricing;
  try { _pricing = await (await fetch(`${API}/pricing`)).json(); } catch { _pricing = {}; }
  return _pricing;
}

// --- Auth (Keycloak, shared /auth) — progressive: UI hides if IdP is down ---
// Keycloak 26 ships the JS adapter as an ESM module; it is vendored
// same-origin under assets/keycloak/ (#215 — no CDN in the auth path).
(async function initAuth() {
  // The sign-in / sign-up buttons are the ONLY way a visitor becomes a user,
  // so they are shown FIRST and never depend on anything loading. Previously
  // a failed CDN import or a failed init silently returned and the auth UI
  // stayed hidden — the product looked like it had no accounts at all (#215).
  // Base Keycloak absolue (voir env.js) : en relatif, la connexion est
  // impossible sur staging, dont le domaine diffère du KC_HOSTNAME partagé.
  const authBase = (window.ECO_AUTH_URL || "/auth").replace(/\/$/, "");
  const realm = window.ECO_REALM || "confinia";
  const clientId = window.ECO_CLIENT || "ecobuilding-web";
  const show = (id, on) => { const el = document.getElementById(id); if (el) el.hidden = !on; };
  // Fallback wiring for a dead adapter. The Keycloak client ENFORCES PKCE, so
  // a bare authorization URL is bounced with « Missing parameter:
  // code_challenge_method » — the #215 fallback silently died the day PKCE
  // was enabled. The challenge is hand-rolled here (WebCrypto): the Keycloak
  // pages then open, the account really gets created; only the silent token
  // exchange needs the adapter, so the user signs in on their next visit.
  const authUrl = async (action) => {
    const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const verifier = b64u(crypto.getRandomValues(new Uint8Array(40)));
    const challenge = b64u(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    return `${authBase}/realms/${encodeURIComponent(realm)}/protocol/openid-connect/${action}` +
      `?client_id=${encodeURIComponent(clientId)}&response_type=code&scope=openid` +
      `&code_challenge=${challenge}&code_challenge_method=S256` +
      `&redirect_uri=${encodeURIComponent(location.origin + "/?welcome=1")}`;
  };
  const signinEl = document.getElementById("signin");
  const signupEl = document.getElementById("signup");
  try {
    if (signinEl) signinEl.href = await authUrl("auth");
    if (signupEl) signupEl.href = await authUrl("registrations");
  } catch {}    // pas de WebCrypto : l'adaptateur ci-dessous reste le chemin
  show("signin", true); show("signup", true);

  let Keycloak;
  try {
    // Vendored same-origin (assets/keycloak/): a CDN in the auth path is a
    // single point of failure — the MapLibre lesson, applied to sign-up.
    ({ default: Keycloak } = await import("./assets/keycloak/keycloak.mjs"));
  } catch (e) {
    return;   // buttons already work through the direct URLs above
  }
  const kc = new Keycloak({ url: authBase, realm, clientId });
  kc.init({ onLoad: "check-sso", pkceMethod: "S256",
            silentCheckSsoRedirectUri: location.origin + "/silent-sso.html" })
    .then((authenticated) => {
      if (authenticated) {
        const t = kc.tokenParsed || {};
        document.getElementById("userlabel").textContent =
          (t.email || t.preferred_username || "compte") + (t.org ? " · " + t.org : "");
        show("userchip", true); show("signin", false); show("signup", false);
        const chip = document.getElementById("userlabel");
        if (chip) { chip.style.cursor = "pointer"; chip.title = "Mon compte, mes clés API";
                    chip.onclick = () => { track("account_open"); showAccount(); }; }
        if (window.ECO_PRO_ENABLED) show("gopro", true);
        // Un jeton périmé ne part JAMAIS (#305). Après une mise en veille,
        // le rafraîchissement échoue en silence et chaque requête partait
        // avec un Bearer mort : le serveur traitait l'utilisateur en anonyme
        // — mauvais plan, mauvais quota — pendant que l'écran affichait
        // encore son compte. Rendre null vaut mieux que mentir : les appels
        // redeviennent franchement anonymes, et l'en-tête le dit.
        window.ecoToken = () => (kc.isTokenExpired(5) ? null : kc.token);
        const sessionExpiree = () => {
          const el = document.getElementById("userlabel");
          if (!el || el.dataset.expired) return;
          el.dataset.expired = "1";
          el.textContent = "Session expirée — se reconnecter";
          el.onclick = () => kc.login();
          window.ecoQuota = null;
          track("session_expired_shown");
        };
        setInterval(() => kc.updateToken(60).then((renewed) => {
          const el = document.getElementById("userlabel");
          if (renewed && el && el.dataset.expired) {
            delete el.dataset.expired;               // la session a survécu
            location.reload();                       // repartir d'un état vrai
          }
        }).catch(() => {
          if (kc.isTokenExpired(0)) sessionExpiree();
        }), 30000);
        track("signed_in_view");
        refreshQuota();
        if (new URLSearchParams(location.search).get("welcome") === "1") {
          track("signup_completed");
          ecoPricing().then((p) => {
            const free = p.free_tiers?.free_account_reports_day
                          ?? p.free_tiers?.free_account_reports_month;
            showPanel(`<h2>Bienvenue 🎉</h2>
              <p>Votre compte est actif : <strong>${free ?? "vos"} fiches PDF par mois</strong>,
              une clé API et le suivi de votre consommation.</p>
              <p class="hint">Cliquez un bâtiment sur la carte pour générer une fiche.
              Un problème ? <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20aide">contact@confinia.io</a></p>`);
          });
          history.replaceState(null, "", location.pathname);
        }
      }
      // Adapter available: prefer its flows (PKCE, silent SSO) over raw URLs.
      if (signinEl) signinEl.onclick = (e) => { e.preventDefault(); track("signin_click"); kc.login(); };
      if (signupEl) signupEl.onclick = (e) => {
        e.preventDefault(); track("signup_click");
        kc.register({ redirectUri: location.origin + "/?welcome=1" });
      };
      const out = document.getElementById("signout");
      if (out) out.onclick = (e) => { e.preventDefault(); kc.logout({ redirectUri: location.origin }); };
      // v4 : trois paliers. Le bouton du bandeau démarre Pro S en un clic ;
      // la page /offres.html propose le choix via des liens /?gopro=s|m|l.
      const startCheckout = async (tier) => {
        track("gopro_click", { tier });
        try {
          const r = await fetch(`/api/v1/pro/checkout?tier=${tier}`,
                                { headers: { Authorization: "Bearer " + kc.token } });
          // 409 = l'utilisateur est DÉJÀ abonné. Un second checkout créerait un
          // second abonnement qui s'additionne, donc l'API refuse — mais choisir
          // un palier supérieur depuis la page Offres, c'est un CHANGEMENT
          // d'offre. Vécu : quota Pro S épuisé, clic sur Pro M, et le front
          // répondait « momentanément indisponible » — impasse complète.
          if (r.status === 409) {
            const up = await fetch(`/api/v1/pro/upgrade?tier=${tier}`,
              { method: "POST", headers: { Authorization: "Bearer " + kc.token } });
            if (up.ok) {
              track("tier_switch", { tier, from: "offers" });
              await refreshQuota();
              showPanel(`<h2>Offre modifiée</h2>
                <p>Vous êtes maintenant sur l'offre <strong>${tier.toUpperCase()}</strong>.
                Le prorata est géré automatiquement.</p>
                <p class="hint">Détail dans « Mon compte ».</p>`);
              return;
            }
            const why = (await up.json().catch(() => ({})))?.detail;
            alert(why || "Changement d'offre impossible : contact@confinia.io");
            return;
          }
          if (!r.ok) throw new Error(r.status);
          const url = (await r.json()).url;
          // Overlay embarqué : le client RESTE sur EcoBuilding (confiance, UX).
          // onComplete est cosmétique — l'activation réelle passe par la
          // réconciliation serveur (webhook/e-mail), jamais par le navigateur.
          if (window.Creem?.openCheckout) {
            window.Creem.openCheckout({
              checkoutUrl: url, locale: "fr",
              onComplete: () => {
                try { window.Creem.close(); } catch {}
                track("gopro_paid_embed");
                showPanel(`<h2>Merci ! 🎉</h2>
                  <p>Paiement reçu — votre abonnement s'active
                  (moins d'une minute).</p>
                  <p class="hint">Une question ?
                  <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20Pro">contact@confinia.io</a></p>`);
                // La réconciliation tourne en ~60 s : rafraîchir le quota
                // jusqu'à voir le plan basculer.
                let tries = 0;
                const poll = setInterval(() => {
                  refreshQuota();
                  if (++tries >= 5) clearInterval(poll);
                }, 20000);
              },
            });
            return;
          }
          window.location.href = url;      // repli : checkout hébergé Creem
        } catch { alert("Le passage à l'offre Pro est momentanément indisponible : contact@confinia.io"); }
      };
      const go = document.getElementById("gopro");
      if (go) go.onclick = (e) => { e.preventDefault(); startCheckout("s"); };
      const wantedTier = new URLSearchParams(location.search).get("gopro");
      if (wantedTier && /^[sml]$/.test(wantedTier)) {
        if (authenticated) { history.replaceState(null, "", location.pathname); startCheckout(wantedTier); }
        else kc.login({ redirectUri: location.origin + "/?gopro=" + wantedTier });
      }
      // Arriving from the quota page: open registration immediately.
      if (!authenticated && new URLSearchParams(location.search).get("signup") === "1") {
        track("signup_autostart");
        kc.register({ redirectUri: location.origin + "/?welcome=1" });
      }
      // « Déjà un compte ? » depuis le panneau de limite : connexion directe.
      if (!authenticated && new URLSearchParams(location.search).get("login") === "1") {
        track("login_autostart");
        kc.login({ redirectUri: location.origin });
      }
    })
    .catch(() => { /* IdP hiccup: the direct-URL buttons stay usable */ });
})();

// Live-audience heartbeat: 1/min per visible tab, anonymous like all events.
setInterval(() => { if (document.visibilityState === "visible") track("heartbeat"); }, 60000);

// --- Map ----------------------------------------------------------------------
// Showcase: 244 Rue de Rivoli, Paris (DPE G, rental ban since 2025).
const SHOWCASE = {
  bdnb_id: "bdnb-bg-LT4B-YEAJ-XXF1",
  lon: 2.325414, lat: 48.86646,
  zoom: 18.15, bearing: -36.8, pitch: 38,
};
// Captured BEFORE map init: maplibre rewrites the hash continuously.
const hadHash = !!location.hash;
const urlBuilding = new URLSearchParams(location.search).get("b");

const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/liberty",
  // Default camera = the showcase building (a #hash in the URL overrides it).
  center: [SHOWCASE.lon, SHOWCASE.lat],
  zoom: SHOWCASE.zoom,
  pitch: SHOWCASE.pitch,
  bearing: SHOWCASE.bearing,
  hash: true,   // position in URL (#zoom/lat/lng/bearing/pitch), shareable & restored on load
  attributionControl: { compact: true },
});

// Selected building in the URL (?b=<bdnb_id>, hash preserved): a shared URL
// reproduces both the view and the open info panel.
function setUrlBuilding(id) {
  const qs = id ? `?b=${encodeURIComponent(id)}` : location.pathname;
  history.replaceState(null, "", (id ? qs : location.pathname) + location.hash);
}
// --- Controls: zoom + compass/pitch, GPS, 3D toggle -----------------------------
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

const geolocate = new maplibregl.GeolocateControl({
  positionOptions: { enableHighAccuracy: true },
  trackUserLocation: true,
  showUserHeading: true,
  fitBoundsOptions: { maxZoom: 17.5 },
});
map.addControl(geolocate, "bottom-right");
geolocate.on("geolocate", async (pos) => {
  const { longitude: lon, latitude: lat } = pos.coords;
  track("geolocate");
  map.easeTo({ zoom: 17.5, pitch: 55 });
  showLoadingPanel('Recherche du bâtiment à votre position…');
  try {
    const r = await fetch(`${API}/reverse?lon=${lon}&lat=${lat}`);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    renderPanel({ label: data.query.address }, data);
  } catch {
    showPanel('<p class="hint">Aucune adresse trouvée à votre position.</p>');
  }
});

class PitchToggle {
  onAdd(m) {
    this._map = m;
    this._btn = document.createElement("button");
    this._btn.className = "maplibregl-ctrl-icon";
    this._btn.textContent = "3D";
    this._btn.style.fontWeight = "700";
    this._btn.title = "Basculer 2D / 3D";
    this._btn.onclick = () => m.easeTo({ pitch: m.getPitch() > 10 ? 0 : 55 });
    this._el = document.createElement("div");
    this._el.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this._el.appendChild(this._btn);
    return this._el;
  }
  onRemove() { this._el.remove(); }
}
map.addControl(new PitchToggle(), "bottom-right");

// --- 3D buildings colored by DPE class (BDNB open data, CSTB) -------------------
const DPE_COLORS = ["match", ["get", "classe_bilan_dpe"],
  "A", "#009036", "B", "#52b153", "C", "#a5cc74", "D", "#f4e70f",
  "E", "#f0b40f", "F", "#eb8235", "G", "#d7221f",
  "#d5cdc0"];

// La MÊME palette, assombrie. Le survol repeignait tout en vert foncé : le
// bâtiment qu'on s'apprêtait à cliquer perdait sa classe, l'information même
// qu'on est venu chercher. Ici il s'assombrit dans SA couleur — le repère est
// net, la classe reste lisible. Mêmes teintes que les applications mobiles.
const DPE_COLORS_DARK = ["match", ["get", "classe_bilan_dpe"],
  "A", "#004f1e", "B", "#29662b", "C", "#5c8033", "D", "#998f08",
  "E", "#946e08", "F", "#8f4d1a", "G", "#7d0f0f",
  "#6b6359"];

map.on("load", () => {
  // Only extrude BDNB (cquest / OSM-FR feedback, issue #51): the basemap's own
  // OSM building extrusions overlapped the BDNB "bâtiment groupe" layer, with
  // BDNB and OSM footprints not aligning 1:1. Remove the basemap building
  // layers so the DPE-colored BDNB volumes are the only 3D buildings shown.
  for (const layer of map.getStyle().layers) {
    if (layer.id !== "bdnb-dpe-3d" && /building/i.test(layer.id)) {
      map.removeLayer(layer.id);
    }
  }

  map.addSource("bdnb", {
    type: "vector",
    // Nos tuiles, pas celles de BDNB en direct : api.bdnb.io est anonyme et
    // limité à 120 req/min et 10 000 req/mois PAR IP. Or MapLibre, au-dessus du
    // maxzoom, redemande la même tuile une fois par identifiant sur-zoomé (~15
    // fois à z18 avec du pitch) : au bout de quelques rechargements l'IP du
    // visiteur prenait un 429 et la 3D disparaissait sans un mot. Le proxy API
    // mutualise ces requêtes et les met en cache (voir /v1/tiles).
    tiles: ["/api/v1/tiles/batiment_groupe/{z}/{x}/{y}.pbf"],
    // BDNB ne publie QUE le z14 (z13 et z15+ répondent 404) : demander z13
    // ne ramenait rien tout en consommant le quota.
    minzoom: 14,
    maxzoom: 14,
    attribution: "Bâtiments & DPE : BDNB (CSTB)",
    // L'id BDNB devient l'id de feature : c'est lui qui permet le feature-state
    // du surlignage au survol (et il est stable d'une tuile à l'autre).
    promoteId: "batiment_groupe_id",
  });
  map.addLayer({
    id: "bdnb-dpe-3d",
    source: "bdnb",
    "source-layer": "sql_statement",
    type: "fill-extrusion",
    minzoom: 14,
    paint: {
      // Survol : couleur STABLE (demande opérateur — pas de clignotement au
      // survol) pour lever l'ambiguïté avant le clic. Le clignotement est
      // réservé au CHARGEMENT du bâtiment cliqué (feature-state "loading").
      "fill-extrusion-color": ["case",
        ["boolean", ["feature-state", "loading"], false],
        ["case", ["boolean", ["feature-state", "pulse"], false], "#a7e3c1", "#2b7a4b"],
        ["boolean", ["feature-state", "hover"], false], DPE_COLORS_DARK,
        DPE_COLORS],
      "fill-extrusion-height": ["coalesce", ["get", "hauteur_mean"], 6],
      // Opacité FIXE : fill-extrusion-opacity ne supporte pas les expressions
      // par feature (« data expressions not supported ») — une expression ici
      // invalide la propriété en silence. Le surlignage passe par la couleur.
      "fill-extrusion-opacity": 0.9,
    },
  });

  // Une carte sans volumes 3D doit le DIRE. Jusqu'ici l'échec des tuiles était
  // parfaitement muet : la carte s'affichait nue et l'utilisateur en déduisait
  // une panne du site. On ne signale que la source « bdnb » (les avertissements
  // de style/sprite du fond de carte ne concernent pas l'utilisateur).
  map.on("error", (e) => {
    if (e && e.sourceId === "bdnb") showTileNotice();
  });
  map.on("sourcedata", (e) => {
    if (e && e.sourceId === "bdnb" && e.isSourceLoaded) hideTileNotice();
  });

  // Un seul bâtiment survolé à la fois — surlignage STABLE (demande
  // opérateur : pas de clignotement au survol), sans timer.
  let hoverId = null;
  const setHover = (id, state) => safeMap(() =>
    map.setFeatureState({ source: "bdnb", sourceLayer: "sql_statement", id }, state));
  function stopHover() {
    if (hoverId !== null) { setHover(hoverId, { hover: false }); hoverId = null; }
    removeHoverMarker();
  }
  map.on("mousemove", "bdnb-dpe-3d", (e) => {
    const f = e.features && e.features[0];
    const id = f && f.id;
    if (id === undefined || id === hoverId) return;
    stopHover();
    hoverId = id;
    setHover(id, { hover: true });
    const c = ecoGeo.featuresCenter([f]);
    if (c) placeHoverMarker(c[0], c[1]);
  });
  map.on("mouseleave", "bdnb-dpe-3d", stopHover);

  // CHARGEMENT d'un bâtiment cliqué : lui, il CLIGNOTE (feature-state
  // loading+pulse) et porte une icône d'attente — le retour visuel est sur
  // l'objet. Arrêté par le premier rendu final (showPanel sans keepLoadingFx).
  let fxId = null, fxTimer = null, fxOn = false;
  window.ecoStartLoadingFx = (id, lon, lat) => {
    window.ecoStopLoadingFx();
    if (id != null) {
      fxId = id;
      setHover(id, { loading: true, pulse: false });
      fxTimer = setInterval(() => {
        if (fxId === null) return;
        fxOn = !fxOn;
        setHover(fxId, { loading: true, pulse: fxOn });
      }, 350);
    }
    if (lon != null) placeLoadingMarker(lon, lat);
  };
  window.ecoStopLoadingFx = () => {
    if (fxTimer) { clearInterval(fxTimer); fxTimer = null; }
    if (fxId !== null) { setHover(fxId, { loading: false, pulse: false }); fxId = null; }
    removeLoadingMarker();
  };
  document.getElementById("legend").hidden = false;

  // Initial selection: ?b= from the URL, else the showcase (no-hash visits).
  const initialB = urlBuilding || (!hadHash ? SHOWCASE.bdnb_id : null);
  if (initialB) {
    if (!urlBuilding) track("showcase_default");
    const c = map.getCenter();
    openBuildingById(initialB, c.lng, c.lat);
  }

  // Click any building -> full record (BDNB id comes from the tile itself).
  map.on("click", "bdnb-dpe-3d", (e) => {
    const f = e.features && e.features[0];
    const id = f && f.properties.batiment_groupe_id;
    if (!id) return;
    track("building_click");
    removeHoverMarker();
    if (marker) marker.remove();
    // Coordonnées = CENTROÏDE du bâtiment cliqué, jamais e.lngLat : en vue
    // inclinée, le point au sol sous le curseur peut être des dizaines de
    // mètres DERRIÈRE le volume cliqué, et ce lon/lat sert à l'arbitrage
    // d'adresse côté serveur (#152) — la fiche se titrerait avec la mauvaise
    // adresse. Le bâtiment fait foi, pas le sol.
    const c = ecoGeo.featuresCenter([f]) || [e.lngLat.lng, e.lngLat.lat];
    openBuildingById(id, c[0], c[1]);
  });
  map.on("mouseenter", "bdnb-dpe-3d", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "bdnb-dpe-3d", () => { map.getCanvas().style.cursor = ""; });
});

let marker = null;
const MARKER_COLOR = "#2b7a4b";
// Marqueur d'APERÇU au survol (#237) : même épingle, même maths d'élévation,
// mais translucide — il montre le toit du bâtiment que le clic sélectionnerait,
// sans toucher au marqueur de sélection.
let hoverMarker = null;
function placeHoverMarker(lon, lat) {
  removeHoverMarker();
  // opacité via l'OPTION du constructeur : MapLibre 6 réécrit style.opacity
  // de l'élément à chaque frame (gestion d'occlusion) et écraserait un style
  // posé à la main.
  hoverMarker = new maplibregl.Marker({ color: MARKER_COLOR, opacity: "0.65" })
    .setLngLat([lon, lat]).addTo(map);
  hoverMarker.getElement().style.pointerEvents = "none";   // ne jamais voler le clic
  updateMarkerVisibility();
}
function removeHoverMarker() {
  if (hoverMarker) { hoverMarker.remove(); hoverMarker = null; }
}
// Icône d'attente posée sur le bâtiment en cours de chargement (altitude 0,
// comme toutes les épingles en attendant les marqueurs élevés natifs).
let loadingMarker = null;
function placeLoadingMarker(lon, lat) {
  removeLoadingMarker();
  const el = document.createElement("div");
  el.className = "building-loading";
  el.innerHTML = '<div class="building-loading-spin"></div>';
  el.style.pointerEvents = "none";
  loadingMarker = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map);
  updateMarkerVisibility();
}
function removeLoadingMarker() {
  if (loadingMarker) { loadingMarker.remove(); loadingMarker = null; }
}

// Identifying pin (issue #113): drop it at a point immediately, then re-anchor
// onto the target building's footprint centroid once its tile is loaded, so the
// pin sits on top of the building instead of the off-centre BAN address point.
// Same helper (ecoGeo.featuresCenter) and color as the PDF render for parity.
function placeMarker(lon, lat) {
  if (marker) marker.remove();
  marker = new maplibregl.Marker({ color: MARKER_COLOR }).setLngLat([lon, lat]).addTo(map);
  updateMarkerVisibility();
}
// MapLibre markers are screen-anchored with no altitude API (6.4), so the
// building height is converted to a pixel offset for the CURRENT camera:
// metres -> pixels at this latitude/zoom, foreshortened by the pitch. Kept in
// sync on every camera move so the pin stays on the roof (#222).
const BUILDINGS_MINZOOM = 14;   // minzoom de la couche bdnb-dpe-3d (BDNB : z14 seul)
// Épingles à l'ALTITUDE 0, posées au centroïde du bâtiment. L'ancienne
// élévation en pixels (#222) n'était juste qu'à cap nul : caméra tournée,
// « plus haut à l'écran » n'est plus « au-dessus du bâtiment » et l'épingle
// atterrissait à côté. En attendant un support natif des marqueurs élevés
// dans maplibre-gl-js, on ne triche plus — on garde seulement la règle
// « pas d'épingle sans bâtiment » (masquées sous le minzoom de la couche).
function updateMarkerVisibility() {
  const visible = map.getZoom() >= BUILDINGS_MINZOOM;
  for (const m of [marker, hoverMarker, loadingMarker]) {
    if (m) m.getElement().style.display = visible ? "" : "none";
  }
}
map.on("move", updateMarkerVisibility);
function anchorMarkerToBuilding(id) {
  if (!marker || !id) return;
  const tryAnchor = () => {
    const feats = map.querySourceFeatures("bdnb",
      { sourceLayer: "sql_statement", filter: ["==", ["get", "batiment_groupe_id"], id] });
    const c = ecoGeo.featuresCenter(feats);
    if (c) { marker.setLngLat(c); return true; }
    return false;
  };
  if (!tryAnchor()) map.once("idle", tryAnchor);   // retry after the building's tile loads
}

// --- Search / autocomplete ------------------------------------------------------
const input = document.getElementById("search");
const list = document.getElementById("suggestions");
let debounce = null;

input.addEventListener("input", () => {
  clearTimeout(debounce);
  const q = input.value.trim();
  if (q.length < 3) { list.hidden = true; return; }
  debounce = setTimeout(async () => {
    try {
      // Le centre de la carte sert de repère : il suit ce que l'utilisateur
      // regarde, et ne demande aucune permission. Sans lui, chercher « ecole »
      // proposait des écoles de toute la France.
      const c = map && map.getCenter ? map.getCenter() : null;
      const near = c ? `&lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}` : "";
      const r = await fetch(`${API}/suggest?q=${encodeURIComponent(q)}${near}`);
      const { suggestions } = await r.json();
      list.innerHTML = "";
      suggestions.forEach((s) => {
        const li = document.createElement("li");
        li.textContent = s.label;
        li.onclick = () => select(s);
        list.appendChild(li);
      });
      list.hidden = suggestions.length === 0;
    } catch { list.hidden = true; }
  }, 250);
});
document.addEventListener("click", (e) => { if (!e.target.closest("#searchbox")) list.hidden = true; });

// La carte est un AGRÉMENT, pas un prérequis : sans WebGL2 (navigateur l'
// entreprise bridé, VM, vieux poste — nos personas collectivités), MapLibre
// lève GPUInitializationError et le moindre map.flyTo jette. La fiche doit
// s'ouvrir quand même : tout contact avec la carte passe par ce garde-fou.
function safeMap(fn) { try { fn(); } catch { /* carte morte : on continue */ } }

// Bandeau discret « bâtiments 3D indisponibles » (échec des tuiles). Discret
// mais explicite : le reste du site fonctionne, seule la couche 3D manque.
let tileNoticeEl = null;
function showTileNotice() {
  if (tileNoticeEl) return;
  tileNoticeEl = document.createElement("div");
  tileNoticeEl.id = "tile-notice";
  tileNoticeEl.innerHTML = "Bâtiments 3D momentanément indisponibles. " +
    "<button type=\"button\" id=\"tile-retry\">Réessayer</button>";
  document.body.appendChild(tileNoticeEl);
  tileNoticeEl.querySelector("#tile-retry").addEventListener("click", () => {
    hideTileNotice();
    // Redemander les tuiles sans recharger la page : on relit la source.
    safeMap(() => {
      const s = map.getSource("bdnb");
      if (s && s.setTiles) s.setTiles(["/api/v1/tiles/batiment_groupe/{z}/{x}/{y}.pbf"]);
      else map.triggerRepaint();
    });
  });
}
function hideTileNotice() {
  if (tileNoticeEl) { tileNoticeEl.remove(); tileNoticeEl = null; }
}

async function select(s) {
  list.hidden = true;
  input.value = s.label;
  track("search", s.type || "unknown");
  safeMap(() => { if (marker) marker.remove(); });

  // City or street: just fly there (zoom 13.5+ reveals the DPE colors).
  if (s.type !== "housenumber") {
    const zoom = s.type === "municipality" ? 13.5 : 16.5;
    panel.hidden = true;
    safeMap(() => map.flyTo({ center: [s.lon, s.lat], zoom, pitch: 45, duration: 2500 }));
    return;
  }

  // Full address: fly to the building and open its record.
  safeMap(() => map.flyTo({ center: [s.lon, s.lat], zoom: 17.5, pitch: 55, bearing: -18, duration: 2500 }));
  safeMap(() => placeMarker(s.lon, s.lat));
  window.ecoStartLoadingFx?.(null, s.lon, s.lat);
  showLoadingPanel('Chargement des données du bâtiment…');
  try {
    // Flux NDJSON : le bâtiment s'affiche dès que BDNB a répondu, les autres
    // sources s'ajoutent à leur arrivée (au lieu d'attendre la plus lente).
    const r = await fetch(`${API}/lookup/stream?ban_id=${encodeURIComponent(s.ban_id)}&lon=${s.lon}&lat=${s.lat}`);
    if (!r.ok) throw new Error(r.status);
    const data = await consumeBuildingStream(r, s);
    safeMap(() => anchorMarkerToBuilding(data.buildings?.[0]?.bdnb_id));   // pin onto the building footprint
    track("lookup", data.buildings?.length ? "ok" : "no_building");
  } catch {
    showPanel('<p class="hint">Erreur de chargement. Réessayez.</p>');
  }
}

// --- Panel rendering -------------------------------------------------------------
const panel = document.getElementById("panel");
const content = document.getElementById("panel-content");
document.getElementById("close").onclick = () => { panel.hidden = true; setUrlBuilding(null); };

function showPanel(html, opts) {
  // L'effet de chargement (clignotement + spinner sur le bâtiment) s'arrête
  // au premier rendu FINAL — l'écran de chargement, lui, le laisse vivre.
  if (!opts?.keepLoadingFx) window.ecoStopLoadingFx?.(); content.innerHTML = html; panel.hidden = false; }

// Panoramax street-level photos near the building (issue #22).
// Le panneau étant re-rendu à CHAQUE bloc du flux, cette vue ne doit être
// cherchée qu'une fois par position — sinon neuf appels Panoramax par clic.
let streetviewAt = null, streetviewCache = "";
async function loadStreetview(lon, lat) {
  const el = document.getElementById("streetview");
  if (!el || lon == null || lat == null) return;
  const at = `${lon},${lat}`;
  if (streetviewAt === at) {                  // déjà chargée : on la replace
    if (streetviewCache) el.innerHTML = streetviewCache;
    return;
  }
  streetviewAt = at;
  streetviewCache = "";
  try {
    const r = await fetch(`${API}/streetview?lon=${lon}&lat=${lat}`);
    const { photos } = await r.json();
    if (!photos?.length) return;
    // Panoramax couvre mal hors des villes : Commons complète, et l'acheteur
    // veut d'abord VOIR l'environnement du bien (#200). Chaque image porte son
    // auteur et sa licence — c'est une obligation des licences CC-BY-SA.
    streetviewCache = `<h3>Photos du lieu</h3><div class="pano-strip">` +
      photos.map((p) => {
        const credit = [p.author, p.licence].filter(Boolean).join(" · ");
        const label = p.title || (p.source === "Panoramax" ? "Vue au sol" : "Photo");
        return `<a href="${p.viewer}" target="_blank" rel="noopener" title="${label}${credit ? " — " + credit : ""}">` +
               `<img src="${p.thumb}" loading="lazy" alt="${label}"></a>`;
      }).join("") +
      `</div><p class="hint">${[...new Set(photos.map((p) => p.source).filter(Boolean))].join(" · ")} — réutilisation sous licence libre, auteur cité au survol</p>`;
    el.innerHTML = streetviewCache;
  } catch { /* imagery is best-effort */ }
}

async function openBuildingById(id, lon, lat) {
  placeMarker(lon, lat);
  anchorMarkerToBuilding(id);   // id is the tile's batiment_groupe_id -> pin on the footprint
  window.ecoStartLoadingFx?.(id, lon, lat);
  showLoadingPanel('Chargement des données du bâtiment…');
  try {
    const r = await fetch(`${API}/buildings/${encodeURIComponent(id)}/stream?lon=${lon}&lat=${lat}`);
    // 404 = vraie absence de fiche ; tout le reste (réseau, 5xx, redéploiement
    // en cours) est PASSAGER et mérite un « Réessayer » — l'ancien message
    // unique faisait croire à un trou de données définitif (vécu : un clic
    // pendant un redéploiement affichait « Données indisponibles »).
    if (r.status === 404) {
      showPanel('<p class="hint">Pas de fiche BDNB pour ce bâtiment.</p>');
      return;
    }
    if (!r.ok) throw new Error(r.status);
    await consumeBuildingStream(r);
  } catch {
    showPanel(`<p class="hint">Données momentanément indisponibles.</p>
      <p><button id="retry-building" class="report-link">Réessayer</button></p>`);
    const b = document.getElementById("retry-building");
    if (b) b.onclick = () => openBuildingById(id, lon, lat);
  }
}

// Affichage AU FIL DE L'EAU (demande opérateur). Neuf sources ouvertes sont
// interrogées par bâtiment : attendre la plus lente laissait l'utilisateur
// devant un panneau vide plusieurs secondes. L'API émet du NDJSON — le
// bâtiment d'abord, puis un bloc par source — et on re-rend le panneau à
// chaque ligne. Le gabarit gère déjà les blocs absents (`data.x ? … : ""`),
// donc un re-rendu complet suffit : pas de rustine par section.
const STREAM_PENDING = {
  area_risks: "Risques (Géorisques)", groundwater: "Nappe phréatique (Hub'Eau)",
  solar_pv: "Solaire (PVGIS)", water_network: "Eau potable (SISPEA)",
  official_dpe: "DPE officiel (ADEME)", local_taxes: "Fiscalité locale (DGFiP)",
  schools: "Écoles (annuaire)", prices: "Prix de vente (DVF)", rnb: "ID-RNB",
  commune: "Commune (Confinia)", dpe_spread: "DPE des logements (ADEME)",
};
async function consumeBuildingStream(response, searched) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const data = { pending: Object.keys(STREAM_PENDING) };
  let buf = "", first = true;

  const paint = () => {
    const panel = document.getElementById("panel-content");
    const top = panel ? panel.scrollTop : 0;   // ne pas remonter à chaque bloc
    renderPanel(searched || { label: data.query?.address || "Bâtiment" }, data,
                { keepLoadingFx: data.pending.length > 0 });
    const after = document.getElementById("panel-content");
    if (after) after.scrollTop = top;
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();                          // ligne partielle : on la garde
    for (const line of lines) {
      if (!line.trim()) continue;
      let ev;
      try { ev = JSON.parse(line); } catch { continue; }
      if (ev.type === "error") throw new Error(ev.status || "stream");
      if (ev.type === "core") { Object.assign(data, ev); }
      else if (ev.type === "block") {
        data[ev.name] = ev.value;
        data.pending = data.pending.filter((n) => n !== ev.name);
      } else if (ev.type === "done") {
        Object.assign(data, ev);
        data.pending = [];
      }
      paint();
    }
  }
  data.pending = [];
  paint();
  return data;
}

// Human-readable French labels for Géorisques raw keys.
const RISK_LABELS = {
  inondation: "Inondation", remonteeNappe: "Remontée de nappe",
  seisme: "Séisme", mouvementTerrain: "Mouvement de terrain",
  retraitGonflementArgile: "Retrait-gonflement des argiles",
  feuForet: "Feu de forêt", radon: "Radon", icpe: "ICPE",
  canalisationsMatieresDangereuses: "Canalisations (matières dangereuses)",
  pollutionSols: "Pollution des sols", nucleaire: "Nucléaire",
  ruptureBarrage: "Rupture de barrage", risqueMinier: "Risque minier",
  cavite: "Cavité souterraine", avalanche: "Avalanche",
};
function humanizeRisk(r) {
  return RISK_LABELS[r] || r.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/^./, (c) => c.toUpperCase());
}

function kv(k, v) {
  return v === null || v === undefined || v === "" ? "" :
    `<div class="kv"><span class="k">${k}</span><span>${v}</span></div>`;
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
function sectionNappe(data) {
  return data.groundwater?.available ? `<h3>Eau souterraine</h3>
    ${kv("Profondeur de la nappe", data.groundwater.water_table_depth_m != null ? data.groundwater.water_table_depth_m + " m sous le sol" : null)}
    ${kv("Piézomètre le plus proche", data.groundwater.station_distance_m != null ? `à ${data.groundwater.station_distance_m} m` + (data.groundwater.station_commune ? ` (${data.groundwater.station_commune})` : "") : null)}
    ${kv("Mesuré le", data.groundwater.measured_on ? String(data.groundwater.measured_on).slice(0, 10) : null)}
    <p class="hint">${data.groundwater.note || ""} ${data.groundwater.well_regulation || ""}</p>` : "";
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
function sectionFiscalite(data) {
  return data.local_taxes ? `<h3>Fiscalité locale${data.local_taxes.year ? ` (${data.local_taxes.year})` : ""}</h3>
    ${kv("Taxe foncière (bâti), taux global", data.local_taxes.property_tax_built_pct != null ? data.local_taxes.property_tax_built_pct + " %" : null)}
    ${kv("Ordures ménagères (TEOM)", data.local_taxes.waste_tax_pct != null ? data.local_taxes.waste_tax_pct + " %" : null)}` : "";
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
function sectionEcoles(data) {
  return data.schools?.within_2km ? `<h3>Écoles à proximité (${data.schools.within_2km} < 2 km)</h3>
    ${(data.schools.nearest || []).slice(0, 3).map((s) => kv(`${s.type || "Établissement"}${s.statut ? " · " + s.statut : ""}`, `${s.name} (${s.distance_m} m)`)).join("")}
    <p class="hint">Proximité ≠ sectorisation (carte scolaire).</p>` : "";
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
function sectionEau(data) {
  return data.water_network ? `<h3>Eau potable (commune)</h3>
    ${kv(`Rendement du réseau${data.water_network.year ? ` (${data.water_network.year})` : ""}`, data.water_network.efficiency_pct != null ? data.water_network.efficiency_pct + " %" : null)}
    ${kv("Part perdue en fuites", data.water_network.losses_pct != null ? data.water_network.losses_pct + " %" : null)}
    ${kv("Prix de l'eau (120 m³)", data.water_network.price_eur_m3 != null ? data.water_network.price_eur_m3 + " €/m³" : null)}` : "";
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
function sectionPrix(data) {
  return data.prices?.available ? `<h3>Prix de vente (DVF)</h3>
    ${kv("Médiane commune, maison", data.prices.commune_eur_m2?.Maison?.median ? data.prices.commune_eur_m2.Maison.median.toLocaleString("fr-FR") + " €/m²" : null)}
    ${kv("Médiane commune, appartement", data.prices.commune_eur_m2?.Appartement?.median ? data.prices.commune_eur_m2.Appartement.median.toLocaleString("fr-FR") + " €/m²" : null)}
    ${(data.prices.sales || []).slice(0, 3).map((s) => kv(`Vente ${String(s.date || "").slice(0, 10)}`, `${(s.valeur_fonciere || 0).toLocaleString("fr-FR")} € (${s.type_local || "?"}${s.surface_m2 ? ", " + Math.round(s.surface_m2) + " m²" : ""})`)).join("")}
    <p class="hint">Transactions réelles DGFiP (DVF) : parcelle du bâtiment et médianes communales.</p>` : "";
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
function sectionRisques(data) {
  const risks = (data.area_risks?.risques_naturels || []).concat(data.area_risks?.risques_technologiques || []);
  return risks.length
    ? `<div class="risk-block"><span class="k">Risques de la zone</span>
        <div class="risk-chips">${risks.map((r) => `<span class="chip">${humanizeRisk(r)}</span>`).join("")}</div></div>`
    : "";
}

function sectionRapportRisques(data) {
  return data.area_risks?.report_url
    ? `<p class="hint"><a href="${data.area_risks.report_url}" target="_blank" rel="noopener">Rapport Géorisques complet →</a></p>`
    : "";
}


// Section qui ne dépend QUE de la position — donc affichable même
// sans bâtiment BDNB.
//
// La commune au sens CIVIL, et le nom qu'elle portait avant. Un acte ancien
// nomme parfois une commune qui n'existe plus ; et quand rien n'a bougé, le
// dire daté et sourcé vaut aussi la peine.
//
// Les réserves de la source sont reprises, jamais résumées : répéter ses
// chiffres sans ses réserves affirmerait plus qu'elle.
function sectionCommune(data) {
  const c = data.commune;
  if (!c?.nom) return "";
  const avant = c.precedent
    ? kv("Auparavant", `${c.precedent.nom}, jusqu'au ${c.precedent.jusqu_au_fr}`)
    : "";
  const reserves = (c.limites || []).concat((c.non_etablis || []).map((d) => d.texte));
  return `<h3>Commune</h3>
    ${kv("Commune", `${c.nom} (${c.code})`)}
    ${c.existe_encore
      ? kv("Nom et limites inchangés depuis", c.depuis_fr)
      : kv("A cessé d'exister le", c.jusqu_au_fr)}
    ${avant}
    ${kv("Données arrêtées au", c.arret_des_donnees_fr)}
    ${reserves.length ? `<p class="hint">${reserves.map((r) => r).join(" ")}</p>` : ""}`;
}


// L'éventail des DPE connus à l'adresse (#287).
//
// Une professionnelle de la promotion immobilière : « Tu raisonnes en DPE par
// bâtiment. Mais il arrive que les apparts d'une même résidence aient des DPE
// différents. » Mesuré : dès qu'une adresse porte plusieurs diagnostics, deux
// fois sur trois les classes diffèrent. Annoncer une classe unique, c'est se
// tromper pour presque tous les logements.
//
// Rien ne s'affiche s'il n'y a qu'un diagnostic : la fiche a déjà raison là.
function sectionEventailDpe(data) {
  const e = data.dpe_spread;
  if (!e || !e.diagnostics) return "";
  const parts = Object.entries(e.repartition || {})
    .map(([c, n]) => `<span class="dpe-badge dpe-${c}">${c}</span>&nbsp;${n}`).join(" · ");
  const titre = e.identiques
    ? `${e.diagnostics} diagnostics connus à cette adresse, tous en ${e.classe_min}.`
    : `${e.diagnostics} diagnostics connus à cette adresse : de <strong>${e.classe_min}</strong>
       à <strong>${e.classe_max}</strong>.`;
  const couv = e.logements_batiment
    ? ` L'immeuble compte ${e.logements_batiment} logements.` : "";
  // UN BLOC PAR DPE.
  //
  // Un tableau suivi des caractéristiques détaillées d'un seul logement se
  // lisait comme « trois diagnostics, une seule date » — la question posée par
  // l'opérateur en regardant sa fiche. Chaque diagnostic a sa date, sa
  // consommation, son coût et son isolation : il lui faut son bloc.
  const repr = data.official_dpe?.dpe_number;
  const blocs = (e.logements || []).map((l) => {
    const titre = `${l.surface_m2 != null ? l.surface_m2 + " m²" : "Logement"}`;
    const marque = l.identifiable
      ? "seul logement de cette surface"
      : `⚠ ${l.memes_surfaces} logements de cette surface — indiscernables`;
    const est = l.numero_dpe && l.numero_dpe === repr;
    return `<div class="logement${est ? " repr" : ""}">
      <div class="logement-t"><span class="dpe-badge dpe-${l.classe}">${l.classe}</span>
        <strong>${titre}</strong>${est ? " · classe affichée ci-dessus" : ""}</div>
      ${kv("Établi le", l.etabli_le)}
      ${kv("Consommation", l.conso_kwh_m2y ? Math.round(l.conso_kwh_m2y) + " kWh/m²/an" : null)}
      ${kv("GES", l.ges_kgco2_m2y ? Math.round(l.ges_kgco2_m2y) + " kgCO₂/m²/an" : null)}
      ${kv("Coût annuel", l.cout_annuel_eur ? Math.round(l.cout_annuel_eur).toLocaleString("fr-FR") + " €/an" : null)}
      ${kv("Isolation", [l.isolation_enveloppe && "enveloppe " + l.isolation_enveloppe,
                         l.isolation_menuiseries && "menuiseries " + l.isolation_menuiseries]
                        .filter(Boolean).join(" · ") || null)}
      ${kv("N° DPE", l.numero_dpe)}
      <p class="hint">${marque}</p>
      ${l.numero_dpe ? `<button class="report-link fiche-logement" data-dpe="${l.numero_dpe}">📄 Fiche de ce logement</button>` : ""}</div>`;
  }).join("");
  return `<div class="dpe-spread"><p class="hint">${titre}
      La classe ci-dessus est celle du logement représentatif du bâtiment,
      pas celle de tous.${couv}</p>
    <p>${parts}</p>
    ${blocs}
    ${blocs ? `<p class="hint">Seuls les logements diagnostiqués figurent : c'est un
      minimum observé, pas un inventaire. Retrouvez le vôtre par sa surface, ou par
      le numéro de DPE que le vendeur vous remet.</p>` : ""}</div>`;
}

function renderPanel(s, data, opts) {
  const b = data.buildings?.[0];
  if (b?.bdnb_id) setUrlBuilding(b.bdnb_id);
  if (!b) {
    // Pas de bâtiment ne veut pas dire rien à dire.
    //
    // Cette branche affichait UNE phrase et jetait tout le reste — alors que
    // les risques de la zone, la nappe, la fiscalité et les écoles étaient
    // déjà arrivés : ils ne dépendent que du point, pas du bâtiment. Et la
    // phrase invitait à chercher « sous une adresse voisine », ce qui est faux
    // outre-mer, où la BDNB n'a aucun bâtiment nulle part.
    showPanel(`<h2>${s.label}</h2>
      <p class="hint">${data.no_building?.text
        || "Aucun bâtiment n'est décrit à cette adresse dans la base nationale (BDNB)."}</p>
      ${sectionRisques(data)}
      ${sectionRapportRisques(data)}
      ${sectionNappe(data)}
      ${sectionFiscalite(data)}
      ${sectionEcoles(data)}
      ${sectionEau(data)}
      ${sectionPrix(data)}
      ${sectionCommune(data)}
      <div id="streetview"></div>
    `, opts);
    loadStreetview(data.query?.lon, data.query?.lat);
    return;
  }
  const cls = b.energy?.dpe_class;
  const ban = b.energy?.rental_ban;
  // Le badge dit l'ÉVENTAIL quand les logements diffèrent (#287).
  //
  // Une lettre unique est l'élément le plus visible de la fiche, et elle a
  // l'air catégorique. Mesuré : dès qu'un immeuble porte plusieurs
  // diagnostics, deux fois sur trois les classes diffèrent — le badge
  // affirmait donc une certitude fausse pour presque tous les logements.
  // Le dégradé va de la couleur de la meilleure classe à celle de la pire.
  const spread = data.dpe_spread;
  const eventail = spread && !spread.identiques && spread.classe_min && spread.classe_max;
  const dpeBadge = eventail
    ? `<span class="dpe-badge dpe-range" style="background:linear-gradient(100deg,
         var(--dpe-${spread.classe_min}) 0%, var(--dpe-${spread.classe_max}) 100%)"
       >${spread.classe_min}&nbsp;–&nbsp;${spread.classe_max}</span>`
    : `<span class="dpe-badge dpe-${cls || "unknown"}">${cls || "?"}</span>`;
  const banHtml = !cls ? "" : ban?.rental_ban_date
    ? `<div class="ban-warning">⚠ Location interdite à partir de <strong>${ban.rental_ban_date.slice(0, 4)}</strong> (loi Climat &amp; Résilience)</div>`
    : `<div class="ban-warning ban-ok">✓ Aucune interdiction de location prévue pour cette classe</div>`;

  const risksHtml = sectionRisques(data);

  // Title with the address the user searched — a BDNB "bâtiment groupe" can
  // span several streets and its principal address then reads as the wrong
  // building (#146). The principal address stays visible as its own row.
  const searched = data.query?.address || s.label || b.address;
  // Affichage progressif : dire ce qui manque encore, sans cacher le reste.
  const pending = data.pending || [];
  const pendingHtml = pending.length
    ? `<p class="hint loading">Encore en cours : ${pending.map((n) => STREAM_PENDING[n] || n).join(", ")}…</p>`
    : "";
  const reportParams = [];
  if (data.query?.lon != null) reportParams.push(`lon=${data.query.lon}`, `lat=${data.query.lat}`);
  if (searched && searched !== b.address) reportParams.push(`address=${encodeURIComponent(searched)}`);
  showPanel(`
    <h2>${searched}</h2>
    ${b.address && b.address !== searched ? kv(`Adresse principale (groupe BDNB${b.dwellings ? `, ${b.dwellings} logements` : ""})`, b.address) : ""}
    <h3>Énergie (DPE)</h3>
    <p>${dpeBadge} ${b.energy?.consumption_kwh_m2y ? `&nbsp;${Math.round(b.energy.consumption_kwh_m2y)} kWh/m²/an` : ""}</p>
    ${banHtml}
    ${sectionEventailDpe(data)}
    ${/* Ces lignes décrivent le logement représentatif. Quand les blocs par
          logement sont affichés (#288), le bloc marqué « classe affichée
          ci-dessus » porte déjà les cinq mêmes champs à l'identique : les
          répéter dessous faisait une section entière de doublons (#309).
          Sans blocs — diagnostic unique ou absent — elles restent : c'est
          alors la seule information. */""}
    ${data.dpe_spread?.logements?.length ? "" : `
    ${data.official_dpe?.dpe_number ? `<h4 class="sub">Le logement représentatif${
        data.official_dpe?.surface_habitable_m2
          ? ` (${Math.round(data.official_dpe.surface_habitable_m2 * 10) / 10} m²)` : ""}</h4>` : ""}
    ${kv("Date du DPE", b.energy?.dpe_date ? String(b.energy.dpe_date).slice(0, 10) : null)}
    ${kv("GES", b.energy?.ghg_kgco2_m2y ? Math.round(b.energy.ghg_kgco2_m2y) + " kgCO₂/m²/an" : null)}
    ${kv("N° DPE officiel", data.official_dpe?.dpe_number)}
    ${kv("Surface habitable", data.official_dpe?.surface_habitable_m2 ? Math.round(data.official_dpe.surface_habitable_m2 * 10) / 10 + " m²" : null)}
    ${kv("Coût annuel d'énergie", data.official_dpe?.annual_cost_eur ? Math.round(data.official_dpe.annual_cost_eur).toLocaleString("fr-FR") + " €/an (DPE)" : null)}`}
    <h3>Bâtiment</h3>
    ${data.market_dia ? `
    <h3>Dynamique du marché (DIA)</h3>
    ${kv("Zone", `${data.market_dia.zone} (${data.market_dia.scope})`)}
    ${kv("Mises en vente (12 mois)", `${data.market_dia.listings_12m}${data.market_dia.listings_3m ? ` — dont ${data.market_dia.listings_3m} au dernier trimestre` : ""}`)}
    ${kv("Prix médian demandé", data.market_dia.median_asking_eur ? `${data.market_dia.median_asking_eur.toLocaleString("fr-FR")} €${data.market_dia.median_asking_eur_m2 ? ` (${data.market_dia.median_asking_eur_m2.toLocaleString("fr-FR")} €/m²)` : ""}` : null)}
    <p class="hint">${data.market_dia.note} Données ${data.market_dia.updated}.</p>` : ""}
    ${data.rnb ? kv("ID-RNB", `<a href="${data.rnb.url}" target="_blank" rel="noopener" title="Fiche du bâtiment dans le Référentiel National des Bâtiments">${data.rnb.rnb_id}</a>`) : ""}
    ${kv("Année de construction", b.construction_year)}
    ${kv("Hauteur moyenne", b.height_m ? b.height_m + " m" : null)}
    ${kv("Logements", b.dwellings)}
    ${kv("Murs", b.wall_material)}
    ${kv("Toit", b.roof_material)}
    <h3>Risques</h3>
    ${kv("Retrait-gonflement argiles", b.risks?.clay_shrink_swell)}
    ${risksHtml}
    ${sectionRapportRisques(data)}
    ${b.cooling?.has_cooling ? `<h3>Climatisation</h3>
    ${kv("Générateur", b.cooling.generator_type)}
    ${kv("Ancienneté", b.cooling.generator_age)}` : ""}
    ${sectionNappe(data)}
    ${sectionFiscalite(data)}
    ${sectionEcoles(data)}
    ${sectionEau(data)}
    <h3>Solaire</h3>
    ${kv("Favorable au solaire thermique", b.solar?.thermal_favourable === true ? "oui" : b.solar?.thermal_favourable === false ? "non" : null)}
    ${kv("Potentiel annuel", b.solar?.thermal_potential_kwh_y ? b.solar.thermal_potential_kwh_y + " kWh/an" : null)}
    ${kv("Productible photovoltaïque", data.solar_pv?.yield_kwh_per_kwc_y ? Math.round(data.solar_pv.yield_kwh_per_kwc_y) + " kWh/an par kWc (PVGIS)" : null)}
    ${sectionPrix(data)}
    ${sectionCommune(data)}
    <p><button id="report-btn" class="report-link" data-url="${API}/report/${encodeURIComponent(b.bdnb_id)}.pdf${reportParams.length ? "?" + reportParams.join("&") : ""}">📄 Obtenir la fiche PDF</button></p>
    <p class="hint" id="report-quota" hidden></p>
    <div id="streetview"></div>
    ${pendingHtml}
    <p class="hint">ID BDNB : ${b.bdnb_id}</p>
  `, opts);
  const pdfBtn = document.getElementById("report-btn");
  if (pdfBtn) pdfBtn.onclick = () => downloadReport(pdfBtn);
  // Fiche PAR LOGEMENT (#311) : chaque bloc porte son bouton, qui réutilise
  // l'URL du bouton principal avec le numéro de DPE en plus. Même parcours,
  // même pré-vol, même quota — seul le document change.
  document.querySelectorAll(".fiche-logement").forEach((f) => {
    if (!pdfBtn) return;
    const base = pdfBtn.dataset.url;
    f.dataset.url = base + (base.includes("?") ? "&" : "?")
      + "dpe=" + encodeURIComponent(f.dataset.dpe);
    f.onclick = () => downloadReport(f);
  });
  compteurFiches(b.bdnb_id);
  loadStreetview(data.query?.lon, data.query?.lat);
}

// --- Le compteur PRÈS DU BOUTON (#290, seconde moitié). L'en-tête porte déjà
// le solde, mais c'est le bouton qu'on regarde au moment de décider — et
// l'en-tête ne dit rien au visiteur sans compte. Même pré-vol (lecture seule)
// que downloadReport : ce que le compteur annonce est ce que la barrière fera.
async function compteurFiches(bdnbId) {
  const el = document.getElementById("report-quota");
  if (!el) return;
  try {
    const headers = window.ecoToken ? { Authorization: "Bearer " + window.ecoToken() } : {};
    const q = await (await fetch(`${API}/quota`, { headers })).json();
    if ((q.free_again || []).includes(bdnbId)) {
      // Rouvrir un document déjà servi ne décompte rien : le dire évite de
      // « garder » ses fiches par peur d'un compteur qui ne bougera pas.
      el.textContent = "Fiche déjà obtenue — la rouvrir ne décompte rien.";
    } else if (q.reports_left == null) {
      return;                      // offre sans plafond : rien à annoncer
    } else if (q.reports_left === 0) {
      el.textContent = q.period === "day"
        ? "Limite du jour atteinte — elle rouvre demain."
        : "Limite du mois atteinte.";
    } else {
      const n = q.reports_left;
      el.textContent = `${n} fiche${n > 1 ? "s" : ""} restante${n > 1 ? "s" : ""} ${periodeQuota(q)}${window.ecoToken ? "" : " (sans compte)"}`;
    }
    el.hidden = false;
  } catch { /* cosmétique : jamais casser la fiche pour un compteur */ }
}

// --- Account quota (#206): a signed-in user sees what is left of the free
// monthly allowance, and subscribers see their plan instead of a limit.

// « ce mois » ou « aujourd'hui » : l'API dit laquelle, on ne la devine pas.
// Le droit d'un compte gratuit est devenu QUOTIDIEN (#290) ; l'écrire en dur
// aurait laissé l'utilisateur croire à un plafond mensuel qu'il ne pouvait pas
// dépasser, alors que son compteur repart le lendemain.
function periodeQuota(u) {
  return u?.period === "day" ? "aujourd'hui" : "ce mois";
}

async function refreshQuota() {
  const el = document.getElementById("userlabel");
  if (!el || !window.ecoToken) return;
  try {
    const r = await fetch(`${API}/usage`, { headers: { Authorization: "Bearer " + window.ecoToken() } });
    if (!r.ok) return;
    const u = await r.json();
    window.ecoQuota = u;
    const badge = u.plan === "pro"
      ? "Pro"
      : `${u.reports_left} fiche${u.reports_left > 1 ? "s" : ""} restante${u.reports_left > 1 ? "s" : ""} ${periodeQuota(u)}`;
    el.textContent = el.textContent.split(" · ")[0] + " · " + badge;
    // Upsell only when the plan is actually purchasable: ECO_PRO_ENABLED is
    // false in production until RULES.md #7 is met, and a visible button that
    // 503s would be worse than no button at all.
    const go = document.getElementById("gopro");
    if (go && window.ECO_PRO_ENABLED) {
      go.hidden = false;
      // Abonné : « Passer Pro » n'a plus de sens — le bouton devient l'accès
      // au changement de palier (panneau compte), jamais un second checkout.
      if (u.plan === "pro") {
        go.textContent = "Changer d'offre";
        go.title = "Changer de palier (prorata immédiat)";
        go.onclick = (e) => { e.preventDefault(); showAccount(); };
      }
    }
  } catch { /* quota display is cosmetic: never break the app */ }
}

// --- Account panel (#220): the product promises "une clé API" — this is where
// a user actually gets it, sees their plan and their consumption.
async function showAccount() {
  if (!window.ecoToken) return;
  const auth = { Authorization: "Bearer " + window.ecoToken() };
  showPanel('<p class="hint loading">Chargement de votre compte…</p>');
  try {
    const [usage, keys] = await Promise.all([
      fetch(`${API}/usage`, { headers: auth }).then((r) => r.json()),
      fetch(`${API}/keys`, { headers: auth }).then((r) => r.json()),
    ]);
    const quota = usage.plan === "pro"
      ? `<p>Offre <strong>${usage.tier_label || "Pro"}</strong> (${usage.cost_eur} €/mois) —
         ${usage.reports_included == null
           ? `${usage.reports_used} fiche${usage.reports_used > 1 ? "s" : ""} ce mois (illimité, usage raisonnable)`
           : `<strong>${usage.reports_left}</strong> fiches restantes sur ${usage.reports_included} ${periodeQuota(usage)}`}.</p>`
      : `<p>Compte gratuit — <strong>${usage.reports_left}</strong> fiches restantes sur ${usage.reports_included} ${periodeQuota(usage)}.</p>`;
    const p = await ecoPricing();
    const tiers = p?.tiers || {};
    const switchers = usage.plan === "pro"
      ? `<h3>Changer d'offre</h3><p>${Object.entries(tiers)
          .filter(([t]) => t !== usage.tier)
          .map(([t, v]) => `<button class="report-link tier-switch" data-tier="${t}">
            ${v.label} — ${v.eur} €/mois${v.fiches_month ? ` (${v.fiches_month} fiches)` : " (illimité)"}</button>`)
          .join(" ")}</p>
         <p class="hint">Changement immédiat, prorata géré par le prestataire de paiement.</p>`
      : "";
    const list = (keys.keys || []).length
      ? `<ul class="keys">${keys.keys.map((k) => `<li><code>${k.masked}</code> <span class="hint">créée le ${String(k.created || "").slice(0, 10)}</span></li>`).join("")}</ul>`
      : '<p class="hint">Aucune clé API pour le moment.</p>';
    showPanel(`<h2>Mon compte</h2>${quota}${switchers}
      <h3>Clés API</h3>${list}
      <p><button id="newkey" class="report-link">Générer une clé API</button></p>
      <div id="keyout"></div>
      <p class="hint">Passez la clé en en-tête <code>X-API-Key</code>.
      Documentation : <a href="/api/v1/docs">/api/v1/docs</a>.<br>
      Une question ? <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20aide">contact@confinia.io</a></p>`);
    document.querySelectorAll(".tier-switch").forEach((b) => {
      b.onclick = async () => {
        const t = b.dataset.tier;
        if (!confirm(`Passer à ${b.textContent.trim()} ? Le changement est immédiat (prorata).`)) return;
        b.disabled = true; b.textContent = "Changement en cours…";
        try {
          const r = await fetch(`${API}/pro/upgrade?tier=${t}`,
            { method: "POST", headers: auth });
          if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || r.status);
          track("tier_switch", { tier: t });
          await refreshQuota();
          showAccount();                       // re-rendu avec le nouveau palier
        } catch (e) {
          // « Réessayer » est une impasse quand le refus vient du fournisseur
          // de paiement : le second essai échouera comme le premier. On donne
          // la seule issue réelle — nous écrire — plutôt qu'un bouton qui
          // tourne en rond au moment précis où le client accepte de payer.
          b.replaceWith(Object.assign(document.createElement("p"), {
            className: "hint",
            innerHTML: 'Le changement d\'offre n\'a pas pu aboutir. '
              + 'Écrivez-nous, nous le faisons manuellement sous 24 h : '
              + '<a href="mailto:contact@confinia.io?subject='
              + encodeURIComponent("EcoBuilding — changement d'offre vers " + t.toUpperCase())
              + '">contact@confinia.io</a>',
          }));
        }
      };
    });
    const btn = document.getElementById("newkey");
    if (btn) btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Génération…";
      try {
        const r = await fetch(`${API}/keys`, { method: "POST", headers: auth });
        const d = await r.json();
        // The value is shown ONCE: the listing only ever returns it masked.
        document.getElementById("keyout").innerHTML =
          `<p class="keynew"><strong>Votre nouvelle clé (copiez-la maintenant, elle ne sera plus affichée)</strong><br>
           <code id="kv">${d.api_key}</code>
           <button id="copykey" class="report-link">Copier</button></p>`;
        document.getElementById("copykey").onclick = () => {
          navigator.clipboard?.writeText(d.api_key);
          document.getElementById("copykey").textContent = "Copiée ✓";
        };
        track("api_key_created");
      } catch {
        document.getElementById("keyout").innerHTML =
          '<p class="hint">Échec de la génération. Réessayez ou écrivez à contact@confinia.io</p>';
      }
      btn.disabled = false; btn.textContent = "Générer une clé API";
    };
  } catch {
    showPanel('<p class="hint">Compte indisponible. Réessayez, ou écrivez à contact@confinia.io</p>');
  }
}

// --- Panel loading narration (#150 follow-up): with 9 upstream sources per
// click, the spinner names what is actually being gathered — honest fan-out
// narration, not fake progress.
const LOADING_SOURCES = [
  "Bâtiment (BDNB)…", "Risques (Géorisques)…", "Nappe phréatique (Hub'Eau)…",
  "Solaire (PVGIS)…", "Prix de vente (DVF)…", "DPE officiel (ADEME)…",
  "Fiscalité locale (DGFiP)…", "Écoles (annuaire)…", "Eau potable (SISPEA)…",
];
let loadingTimer = null;
function showLoadingPanel(first) {
  let i = 0;
  showPanel(`<p class="hint loading">${first}<br><span id="loading-src" class="hint">${LOADING_SOURCES[0]}</span></p>`, { keepLoadingFx: true });
  clearInterval(loadingTimer);
  loadingTimer = setInterval(() => {
    const el = document.getElementById("loading-src");
    if (!el) { clearInterval(loadingTimer); return; }
    i = (i + 1) % LOADING_SOURCES.length;
    el.textContent = LOADING_SOURCES[i];
  }, 550);
}

// --- PDF generation feedback (#150) ------------------------------------------
// The fiche takes 10-45 s server-side (upstream data + 3D render + layout). A
// raw link opens a blank tab for that whole time. Staged labels timed on real
// p50 durations are honest feedback; a smooth percent bar would be fiction —
// a single server render exposes no progress.
const PDF_STAGES = [
  [0, "Collecte des données…"],
  [3000, "Rendu de la carte 3D…"],
  [12000, "Mise en page du PDF…"],
];
function pdfStage(elapsedMs) {
  let label = PDF_STAGES[0][1];
  for (const [t, l] of PDF_STAGES) if (elapsedMs >= t) label = l;
  return label;
}

const NEXT_TIER = { s: "m", m: "l" };
function showQuotaPanel(p, signedIn, q) {
  const free = p?.free_tiers?.free_account_reports_day
    ?? p?.free_tiers?.free_account_reports_month;
  const anon = p?.free_tiers?.anonymous_reports_month;
  const tierS = p?.tiers?.s;
  // Un ABONNÉ qui atteint le quota de son palier n'est pas un compte gratuit :
  // lui dire « votre compte gratuit » et lui proposer « passer Pro » alors
  // qu'il paie déjà était faux, et le laissait sans issue (vécu sur sandbox).
  if (q?.plan === "pro") {
    const up = NEXT_TIER[q.tier];
    const upT = up && p?.tiers?.[up];
    showPanel(`<h2>Quota de votre offre atteint</h2>
      <p>Votre offre <strong>${q.tier_label || q.tier?.toUpperCase() || "Pro"}</strong>
      couvre ${q.reports_included ?? "vos"} fiches par mois, toutes utilisées.</p>
      ${upT ? `<p><button class="report-link" id="quota-upgrade" data-tier="${up}">
        Passer à ${upT.label} : ${upT.eur} €/mois
        (${upT.fiches_month ?? "illimité, usage raisonnable"}${upT.fiches_month ? " fiches" : ""})
        </button></p>
      <p class="hint">Changement immédiat, prorata géré automatiquement.</p>`
      : `<p class="hint">Votre offre est déjà la plus large.
         Écrivez-nous : <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20volume">contact@confinia.io</a></p>`}`);
    const b = document.getElementById("quota-upgrade");
    if (b) b.onclick = () => { location.href = "/?gopro=" + b.dataset.tier; };
    return;
  }
  showPanel(`<h2>Limite atteinte</h2>
    <p>${signedIn
      ? `Votre compte gratuit couvre ${free ?? "vos"} fiches par jour. Le compteur repart demain.`
      : `Sans compte, ${anon ?? "quelques"} fiches par mois sont offertes.`}</p>
    <p>${signedIn
      ? (window.ECO_PRO_ENABLED
        ? `<a class="report-link" href="/offres.html">Passer Pro : dès ${tierS?.eur ?? 9} €/mois (${tierS?.fiches_month ?? 30} fiches)</a>`
        // Les offres Pro ne sont pas encore ouvertes : proposer un bouton qui
        // finit en « momentanément indisponible » est pire que ne rien
        // proposer. Quelqu'un qui atteint le mur ET veut payer est le signal
        // le plus fort qu'on puisse recevoir — on le recueille au lieu de le
        // perdre dans une boîte d'alerte.
        : `<a class="report-link" onclick="fetch('${API}/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:'pro_interest'})})" href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20besoin%20de%20volume&body=${
             encodeURIComponent("Bonjour,\n\nJ'ai atteint la limite mensuelle et j'ai besoin de plus de fiches.\n\nMon usage : ")
           }">J'ai besoin de plus de fiches — écrivez-nous</a>`)
      : `<a class="report-link" href="/?login=1">Se connecter</a>`}</p>
    ${signedIn && !window.ECO_PRO_ENABLED
      ? `<p class="hint">Les offres payantes ne sont pas encore ouvertes. Dites-nous
         votre volume : c'est ce qui décide de leur ouverture.</p>` : ""}
    ${signedIn ? "" : `<p><a href="/?signup=1">Pas encore de compte ? En créer un (30 s, sans carte)</a></p>
      <p class="hint">Le compte gratuit offre le même nombre de fiches, mais un
      quota qui vous suit d'un appareil à l'autre, et une clé API.</p>`}
    <p class="hint">Une question ? <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20aide">contact@confinia.io</a></p>`);
}

async function downloadReport(btn) {
  const url = btn.dataset.url;
  const original = btn.textContent;
  // Open the tab synchronously (inside the user gesture) so popup blockers
  // allow it; it navigates to the PDF blob once ready.
  const tab = window.open("", "_blank");
  // PRÉ-VOL (lecture seule, ~50 ms) : bloquer AVANT le cérémonial de
  // génération — le message de limite arrivait après 25 s d'attente pour
  // rien. La tab est DÉJÀ ouverte (contrainte anti-popup : window.open doit
  // rester dans le geste, avant tout await) ; si le quota est épuisé, elle
  // se referme aussitôt et le panneau s'affiche immédiatement.
  try {
    const headers = window.ecoToken ? { Authorization: "Bearer " + window.ecoToken() } : {};
    const q = await (await fetch(`${API}/quota`, { headers })).json();
    if (q.reports_left === 0) {
      if (tab) tab.close();
      showQuotaPanel(await ecoPricing(), !!window.ecoToken, q);
      track("report_blocked_preflight");
      return;
    }
  } catch { /* pré-vol indisponible : le serveur reste la barrière (429) */ }
  if (tab) tab.document.write(`<!doctype html><title>Fiche EcoBuilding</title>
<body style="font-family:system-ui,sans-serif;display:flex;min-height:90vh;align-items:center;justify-content:center;background:#f6f8f6">
<div style="text-align:center;max-width:26em">
  <div style="font-size:1.3em;font-weight:700;color:#2b7a4b">EcoBuilding</div>
  <div style="margin:1.2em auto;width:34px;height:34px;border:4px solid #2b7a4b;border-top-color:transparent;border-radius:50%;animation:s .8s linear infinite"></div>
  <style>@keyframes s{to{transform:rotate(360deg)}}</style>
  <div id="stage" style="font-weight:600">Collecte des données…</div>
  <div id="elapsed" style="color:#777;font-size:.9em;margin-top:.4em"></div>
  <p style="color:#555;font-size:.9em;margin-top:1.2em">La fiche assemble les données ouvertes, le rendu de la carte 3D
  et les photos de rue : comptez 10 à 45 secondes.</p>
</div></body>`);
  btn.disabled = true;
  const t0 = Date.now();
  const timer = setInterval(() => {
    const ms = Date.now() - t0;
    btn.textContent = "⏳ " + pdfStage(ms);
    try {  // the interstitial is same-origin (about:blank): mirror progress there
      if (tab && tab.document) {
        tab.document.getElementById("stage").textContent = pdfStage(ms);
        tab.document.getElementById("elapsed").textContent = Math.round(ms / 1000) + " s";
      }
    } catch (e) { /* tab closed or navigated: ignore */ }
  }, 500);
  track("report_click");
  try {
    // Signed-in users get their account allowance (#206); anonymous visitors
    // keep the 10/month IP tier.
    const headers = window.ecoToken ? { Authorization: "Bearer " + window.ecoToken() } : {};
    const r = await fetch(url, { headers });
    if (r.status === 429) {
      // Self-service: the app itself says what to do next (#212).
      const signedIn = !!window.ecoToken;
      const p = await ecoPricing();
      const anon = p.free_tiers?.anonymous_reports_month, free = p.free_tiers?.free_account_reports_month;
      showQuotaPanel(p, signedIn, window.ecoQuota);
      if (tab) tab.close();
      return;
    }
    if (!r.ok) {
      // Quota (429) and friends serve a friendly HTML page — show it as-is.
      if (tab) tab.location = url; else window.open(url, "_blank");
      return;
    }
    // On navigue vers l'URL RÉELLE, pas vers un blob.
    //
    // Un blob n'a aucun en-tête : le `Content-Disposition` du serveur était
    // perdu, et le navigateur nommait le fichier d'après l'identifiant du blob
    // — « 9e2a675e-ea29-4758….pdf » arrivait ainsi en pièce jointe. L'adresse
    // du bien est dans l'en-tête ; encore faut-il la laisser vivre.
    //
    // Le fetch ci-dessus n'a pas servi pour rien : il a attendu la génération
    // en montrant la progression, et la fiche est maintenant dans le cache
    // disque du serveur. Cette seconde requête revient en ~0,2 s et ne
    // consomme PAS de seconde fiche — le même document servi le même jour est
    // gratuit, comme sur mobile.
    await r.blob();                        // vide le corps, la fiche est en cache
    if (tab) tab.location = url; else window.open(url, "_blank");
  } catch (e) {
    if (tab) tab.close();
    btn.textContent = "Erreur de génération, réessayez";
    setTimeout(() => { btn.textContent = original; }, 4000);
    return;
  } finally {
    clearInterval(timer);
    refreshQuota();                       // the fiche just consumed one
    btn.disabled = false;
    if (btn.textContent.startsWith("⏳")) btn.textContent = original;
  }
}
