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

// --- Auth (Keycloak, shared /auth) — progressive: UI hides if IdP is down ---
// Keycloak 26 ships the JS adapter as an ESM module (no server-hosted
// /auth/js/keycloak.js), so we import it dynamically from a pinned CDN.
(async function initAuth() {
  // The sign-in / sign-up buttons are the ONLY way a visitor becomes a user,
  // so they are shown FIRST and never depend on anything loading. Previously
  // a failed CDN import or a failed init silently returned and the auth UI
  // stayed hidden — the product looked like it had no accounts at all (#215).
  const realm = window.ECO_REALM || "confinia";
  const clientId = window.ECO_CLIENT || "ecobuilding-web";
  const show = (id, on) => { const el = document.getElementById(id); if (el) el.hidden = !on; };
  const authUrl = (action) =>
    `/auth/realms/${encodeURIComponent(realm)}/protocol/openid-connect/${action}` +
    `?client_id=${encodeURIComponent(clientId)}&response_type=code&scope=openid` +
    `&redirect_uri=${encodeURIComponent(location.origin + "/?welcome=1")}`;
  // Fallback wiring: plain Keycloak URLs work with no JS adapter at all.
  const signinEl = document.getElementById("signin");
  const signupEl = document.getElementById("signup");
  if (signinEl) signinEl.href = authUrl("auth");
  if (signupEl) signupEl.href = authUrl("registrations");
  show("signin", true); show("signup", true);

  let Keycloak;
  try {
    // Vendored same-origin (assets/keycloak/): a CDN in the auth path is a
    // single point of failure — the MapLibre lesson, applied to sign-up.
    ({ default: Keycloak } = await import("./assets/keycloak/keycloak.mjs"));
  } catch (e) {
    return;   // buttons already work through the direct URLs above
  }
  const kc = new Keycloak({ url: "/auth", realm, clientId });
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
        window.ecoToken = () => kc.token;
        setInterval(() => kc.updateToken(60).catch(() => {}), 30000);
        track("signed_in_view");
        refreshQuota();
        if (new URLSearchParams(location.search).get("welcome") === "1") {
          track("signup_completed");
          showPanel(`<h2>Bienvenue 🎉</h2>
            <p>Votre compte est actif : <strong>30 fiches PDF par mois</strong> (au lieu de 10),
            une clé API et le suivi de votre consommation.</p>
            <p class="hint">Cliquez un bâtiment sur la carte pour générer une fiche.
            Un problème ? <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20aide">contact@confinia.io</a></p>`);
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
      const go = document.getElementById("gopro");
      if (go) go.onclick = async (e) => {
        e.preventDefault(); track("gopro_click");
        try {
          const r = await fetch("/api/v1/pro/checkout", { headers: { Authorization: "Bearer " + kc.token } });
          if (!r.ok) throw new Error(r.status);
          window.location.href = (await r.json()).url;   // -> Polar hosted checkout
        } catch { alert("Le passage à l'offre Pro est momentanément indisponible : contact@confinia.io"); }
      };
      // Arriving from the quota page: open registration immediately.
      if (!authenticated && new URLSearchParams(location.search).get("signup") === "1") {
        track("signup_autostart");
        kc.register({ redirectUri: location.origin + "/?welcome=1" });
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
    tiles: ["https://api.bdnb.io/v1/bdnb/tuiles/batiment_groupe/{z}/{x}/{y}.pbf"],
    minzoom: 13,
    maxzoom: 14,
    attribution: "Bâtiments & DPE : BDNB (CSTB)",
  });
  map.addLayer({
    id: "bdnb-dpe-3d",
    source: "bdnb",
    "source-layer": "sql_statement",
    type: "fill-extrusion",
    minzoom: 13,
    paint: {
      "fill-extrusion-color": DPE_COLORS,
      "fill-extrusion-height": ["coalesce", ["get", "hauteur_mean"], 6],
      "fill-extrusion-opacity": 0.9,
    },
  });
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
    if (marker) marker.remove();
    openBuildingById(id, e.lngLat.lng, e.lngLat.lat);
  });
  map.on("mouseenter", "bdnb-dpe-3d", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "bdnb-dpe-3d", () => { map.getCanvas().style.cursor = ""; });
});

let marker = null;
const MARKER_COLOR = "#2b7a4b";

// Identifying pin (issue #113): drop it at a point immediately, then re-anchor
// onto the target building's footprint centroid once its tile is loaded, so the
// pin sits on top of the building instead of the off-centre BAN address point.
// Same helper (ecoGeo.featuresCenter) and color as the PDF render for parity.
let markerHeightM = 0;
function placeMarker(lon, lat, heightM) {
  if (marker) marker.remove();
  markerHeightM = heightM || 0;
  marker = new maplibregl.Marker({ color: MARKER_COLOR }).setLngLat([lon, lat]).addTo(map);
  updateMarkerElevation();
}
// MapLibre markers are screen-anchored with no altitude API (6.4), so the
// building height is converted to a pixel offset for the CURRENT camera:
// metres -> pixels at this latitude/zoom, foreshortened by the pitch. Kept in
// sync on every camera move so the pin stays on the roof (#222).
function updateMarkerElevation() {
  if (!marker || !markerHeightM) return;
  const lat = marker.getLngLat().lat;
  const metresPerPixel = 156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, map.getZoom());
  const dy = (markerHeightM / metresPerPixel) * Math.cos(map.getPitch() * Math.PI / 180);
  marker.setOffset([0, -dy]);
}
map.on("move", updateMarkerElevation);
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
      const r = await fetch(`${API}/suggest?q=${encodeURIComponent(q)}`);
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

async function select(s) {
  list.hidden = true;
  input.value = s.label;
  track("search", s.type || "unknown");
  if (marker) marker.remove();

  // City or street: just fly there (zoom 13.5+ reveals the DPE colors).
  if (s.type !== "housenumber") {
    const zoom = s.type === "municipality" ? 13.5 : 16.5;
    panel.hidden = true;
    map.flyTo({ center: [s.lon, s.lat], zoom, pitch: 45, duration: 2500 });
    return;
  }

  // Full address: fly to the building and open its record.
  map.flyTo({ center: [s.lon, s.lat], zoom: 17.5, pitch: 55, bearing: -18, duration: 2500 });
  placeMarker(s.lon, s.lat);
  showLoadingPanel('Chargement des données du bâtiment…');
  try {
    const r = await fetch(`${API}/lookup?ban_id=${encodeURIComponent(s.ban_id)}&lon=${s.lon}&lat=${s.lat}`);
    const data = await r.json();
    anchorMarkerToBuilding(data.buildings?.[0]?.bdnb_id);   // pin onto the building footprint
    renderPanel(s, data);
    track("lookup", data.buildings?.length ? "ok" : "no_building");
  } catch {
    showPanel('<p class="hint">Erreur de chargement. Réessayez.</p>');
  }
}

// --- Panel rendering -------------------------------------------------------------
const panel = document.getElementById("panel");
const content = document.getElementById("panel-content");
document.getElementById("close").onclick = () => { panel.hidden = true; setUrlBuilding(null); };

function showPanel(html) { content.innerHTML = html; panel.hidden = false; }

// Panoramax street-level photos near the building (issue #22).
async function loadStreetview(lon, lat) {
  const el = document.getElementById("streetview");
  if (!el || lon == null || lat == null) return;
  try {
    const r = await fetch(`${API}/streetview?lon=${lon}&lat=${lat}`);
    const { photos } = await r.json();
    if (!photos?.length) return;
    el.innerHTML = `<h3>Vue au sol (Panoramax)</h3><div class="pano-strip">` +
      photos.map((p) => `<a href="${p.viewer}" target="_blank" rel="noopener"><img src="${p.thumb}" loading="lazy" alt="Photo Panoramax"></a>`).join("") +
      `</div><p class="hint">Images Panoramax — CC-BY-SA</p>`;
  } catch { /* imagery is best-effort */ }
}

async function openBuildingById(id, lon, lat) {
  placeMarker(lon, lat);
  anchorMarkerToBuilding(id);   // id is the tile's batiment_groupe_id -> pin on the footprint
  showLoadingPanel('Chargement des données du bâtiment…');
  try {
    const r = await fetch(`${API}/buildings/${encodeURIComponent(id)}?lon=${lon}&lat=${lat}`);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    renderPanel({ label: data.query.address || "Bâtiment" }, data);
  } catch {
    showPanel('<p class="hint">Données indisponibles pour ce bâtiment.</p>');
  }
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

function renderPanel(s, data) {
  const b = data.buildings?.[0];
  if (b?.bdnb_id) setUrlBuilding(b.bdnb_id);
  // Now that the height is known, lift the pin onto the roof (#222).
  if (b?.height_m && marker) { markerHeightM = b.height_m; updateMarkerElevation(); }
  if (!b) {
    showPanel(`<h2>${s.label}</h2><p class="hint">Aucune fiche BDNB trouvée pour cette adresse.
      Le bâtiment existe peut-être sous une adresse voisine.</p>`);
    return;
  }
  const cls = b.energy?.dpe_class;
  const ban = b.energy?.rental_ban;
  const dpeBadge = `<span class="dpe-badge dpe-${cls || "unknown"}">${cls || "?"}</span>`;
  const banHtml = !cls ? "" : ban?.rental_ban_date
    ? `<div class="ban-warning">⚠ Location interdite à partir du <strong>${ban.rental_ban_date.slice(0, 4)}</strong> (loi Climat &amp; Résilience)</div>`
    : `<div class="ban-warning ban-ok">✓ Aucune interdiction de location prévue pour cette classe</div>`;

  const risks = (data.area_risks?.risques_naturels || []).concat(data.area_risks?.risques_technologiques || []);
  const risksHtml = risks.length
    ? `<div class="risk-block"><span class="k">Risques de la zone</span>
        <div class="risk-chips">${risks.map((r) => `<span class="chip">${humanizeRisk(r)}</span>`).join("")}</div></div>`
    : "";

  // Title with the address the user searched — a BDNB "bâtiment groupe" can
  // span several streets and its principal address then reads as the wrong
  // building (#146). The principal address stays visible as its own row.
  const searched = data.query?.address || s.label || b.address;
  const reportParams = [];
  if (data.query?.lon != null) reportParams.push(`lon=${data.query.lon}`, `lat=${data.query.lat}`);
  if (searched && searched !== b.address) reportParams.push(`address=${encodeURIComponent(searched)}`);
  showPanel(`
    <h2>${searched}</h2>
    ${b.address && b.address !== searched ? kv(`Adresse principale (groupe BDNB${b.dwellings ? `, ${b.dwellings} logements` : ""})`, b.address) : ""}
    <h3>Énergie (DPE)</h3>
    <p>${dpeBadge} ${b.energy?.consumption_kwh_m2y ? `&nbsp;${Math.round(b.energy.consumption_kwh_m2y)} kWh/m²/an` : ""}</p>
    ${banHtml}
    ${kv("Date du DPE", b.energy?.dpe_date ? String(b.energy.dpe_date).slice(0, 10) : null)}
    ${kv("GES", b.energy?.ghg_kgco2_m2y ? Math.round(b.energy.ghg_kgco2_m2y) + " kgCO₂/m²/an" : null)}
    ${kv("N° DPE officiel", data.official_dpe?.dpe_number)}
    ${kv("Surface habitable", data.official_dpe?.surface_habitable_m2 ? data.official_dpe.surface_habitable_m2 + " m²" : null)}
    ${kv("Coût annuel d'énergie", data.official_dpe?.annual_cost_eur ? Math.round(data.official_dpe.annual_cost_eur).toLocaleString("fr-FR") + " €/an (DPE)" : null)}
    <h3>Bâtiment</h3>
    ${kv("Année de construction", b.construction_year)}
    ${kv("Hauteur moyenne", b.height_m ? b.height_m + " m" : null)}
    ${kv("Logements", b.dwellings)}
    ${kv("Murs", b.wall_material)}
    ${kv("Toit", b.roof_material)}
    <h3>Risques</h3>
    ${kv("Retrait-gonflement argiles", b.risks?.clay_shrink_swell)}
    ${risksHtml}
    ${data.area_risks?.report_url ? `<p class="hint"><a href="${data.area_risks.report_url}" target="_blank" rel="noopener">Rapport Géorisques complet →</a></p>` : ""}
    ${b.cooling?.has_cooling ? `<h3>Climatisation</h3>
    ${kv("Générateur", b.cooling.generator_type)}
    ${kv("Ancienneté", b.cooling.generator_age)}` : ""}
    ${data.groundwater?.available ? `<h3>Eau souterraine</h3>
    ${kv("Profondeur de la nappe", data.groundwater.water_table_depth_m != null ? data.groundwater.water_table_depth_m + " m sous le sol" : null)}
    ${kv("Piézomètre le plus proche", data.groundwater.station_distance_m != null ? `à ${data.groundwater.station_distance_m} m` + (data.groundwater.station_commune ? ` (${data.groundwater.station_commune})` : "") : null)}
    ${kv("Mesuré le", data.groundwater.measured_on ? String(data.groundwater.measured_on).slice(0, 10) : null)}
    <p class="hint">${data.groundwater.note || ""} ${data.groundwater.well_regulation || ""}</p>` : ""}
    ${data.local_taxes ? `<h3>Fiscalité locale${data.local_taxes.year ? ` (${data.local_taxes.year})` : ""}</h3>
    ${kv("Taxe foncière (bâti), taux global", data.local_taxes.property_tax_built_pct != null ? data.local_taxes.property_tax_built_pct + " %" : null)}
    ${kv("Ordures ménagères (TEOM)", data.local_taxes.waste_tax_pct != null ? data.local_taxes.waste_tax_pct + " %" : null)}` : ""}
    ${data.schools?.within_2km ? `<h3>Écoles à proximité (${data.schools.within_2km} < 2 km)</h3>
    ${(data.schools.nearest || []).slice(0, 3).map((s) => kv(`${s.type || "Établissement"}${s.statut ? " · " + s.statut : ""}`, `${s.name} (${s.distance_m} m)`)).join("")}
    <p class="hint">Proximité ≠ sectorisation (carte scolaire).</p>` : ""}
    ${data.water_network ? `<h3>Eau potable (commune)</h3>
    ${kv(`Rendement du réseau${data.water_network.year ? ` (${data.water_network.year})` : ""}`, data.water_network.efficiency_pct != null ? data.water_network.efficiency_pct + " %" : null)}
    ${kv("Part perdue en fuites", data.water_network.losses_pct != null ? data.water_network.losses_pct + " %" : null)}
    ${kv("Prix de l'eau (120 m³)", data.water_network.price_eur_m3 != null ? data.water_network.price_eur_m3 + " €/m³" : null)}` : ""}
    <h3>Solaire</h3>
    ${kv("Favorable au solaire thermique", b.solar?.thermal_favourable === true ? "oui" : b.solar?.thermal_favourable === false ? "non" : null)}
    ${kv("Potentiel annuel", b.solar?.thermal_potential_kwh_y ? b.solar.thermal_potential_kwh_y + " kWh/an" : null)}
    ${kv("Productible photovoltaïque", data.solar_pv?.yield_kwh_per_kwc_y ? Math.round(data.solar_pv.yield_kwh_per_kwc_y) + " kWh/an par kWc (PVGIS)" : null)}
    ${data.prices?.available ? `<h3>Prix de vente (DVF)</h3>
    ${kv("Médiane commune, maison", data.prices.commune_eur_m2?.Maison?.median ? data.prices.commune_eur_m2.Maison.median.toLocaleString("fr-FR") + " €/m²" : null)}
    ${kv("Médiane commune, appartement", data.prices.commune_eur_m2?.Appartement?.median ? data.prices.commune_eur_m2.Appartement.median.toLocaleString("fr-FR") + " €/m²" : null)}
    ${(data.prices.sales || []).slice(0, 3).map((s) => kv(`Vente ${String(s.date || "").slice(0, 10)}`, `${(s.valeur_fonciere || 0).toLocaleString("fr-FR")} € (${s.type_local || "?"}${s.surface_m2 ? ", " + Math.round(s.surface_m2) + " m²" : ""})`)).join("")}
    <p class="hint">Transactions réelles DGFiP (DVF) : parcelle du bâtiment et médianes communales.</p>` : ""}
    <p><button id="report-btn" class="report-link" data-url="${API}/report/${encodeURIComponent(b.bdnb_id)}.pdf${reportParams.length ? "?" + reportParams.join("&") : ""}">📄 Fiche PDF normalisée</button></p>
    <div id="streetview"></div>
    <p class="hint">ID BDNB : ${b.bdnb_id}</p>
  `);
  const pdfBtn = document.getElementById("report-btn");
  if (pdfBtn) pdfBtn.onclick = () => downloadReport(pdfBtn);
  loadStreetview(data.query?.lon, data.query?.lat);
}

// --- Account quota (#206): a signed-in user sees what is left of the free
// monthly allowance, and subscribers see their plan instead of a limit.
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
      : `${u.reports_left} fiche${u.reports_left > 1 ? "s" : ""} restante${u.reports_left > 1 ? "s" : ""} ce mois`;
    el.textContent = el.textContent.split(" · ")[0] + " · " + badge;
    // Upsell only when the plan is actually purchasable: ECO_PRO_ENABLED is
    // false in production until RULES.md #7 is met, and a visible button that
    // 503s would be worse than no button at all.
    const go = document.getElementById("gopro");
    if (go && window.ECO_PRO_ENABLED && u.plan !== "pro") go.hidden = false;
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
      ? `<p>Offre <strong>Pro</strong> — ${usage.credits} crédits ce mois, ${usage.cost_eur} € (plafond ${usage.monthly_cap_eur} €).</p>`
      : `<p>Compte gratuit — <strong>${usage.reports_left}</strong> fiches restantes sur ${usage.reports_included} ce mois.</p>`;
    const list = (keys.keys || []).length
      ? `<ul class="keys">${keys.keys.map((k) => `<li><code>${k.masked}</code> <span class="hint">créée le ${String(k.created || "").slice(0, 10)}</span></li>`).join("")}</ul>`
      : '<p class="hint">Aucune clé API pour le moment.</p>';
    showPanel(`<h2>Mon compte</h2>${quota}
      <h3>Clés API</h3>${list}
      <p><button id="newkey" class="report-link">Générer une clé API</button></p>
      <div id="keyout"></div>
      <p class="hint">Passez la clé en en-tête <code>X-API-Key</code>.
      Documentation : <a href="/api/v1/docs">/api/v1/docs</a>.<br>
      Une question ? <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20aide">contact@confinia.io</a></p>`);
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
  showPanel(`<p class="hint loading">${first}<br><span id="loading-src" class="hint">${LOADING_SOURCES[0]}</span></p>`);
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

async function downloadReport(btn) {
  const url = btn.dataset.url;
  const original = btn.textContent;
  // Open the tab synchronously (inside the user gesture) so popup blockers
  // allow it; it navigates to the PDF blob once ready.
  const tab = window.open("", "_blank");
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
      showPanel(`<h2>Limite atteinte</h2>
        <p>${signedIn
          ? "Votre compte gratuit couvre 30 fiches par mois."
          : "Sans compte, 10 fiches par mois sont offertes."}</p>
        <p>${signedIn
          ? '<a class="report-link" href="/offres.html">Voir l\'offre Pro (9 €/mois)</a>'
          : '<a class="report-link" href="/?signup=1">Créer un compte gratuit (30 fiches/mois)</a>'}</p>
        <p class="hint">Une question ? <a href="mailto:contact@confinia.io?subject=EcoBuilding%20-%20aide">contact@confinia.io</a></p>`);
      if (tab) tab.close();
      return;
    }
    if (!r.ok) {
      // Quota (429) and friends serve a friendly HTML page — show it as-is.
      if (tab) tab.location = url; else window.open(url, "_blank");
      return;
    }
    const blobUrl = URL.createObjectURL(await r.blob());
    if (tab) tab.location = blobUrl; else window.open(blobUrl, "_blank");
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
