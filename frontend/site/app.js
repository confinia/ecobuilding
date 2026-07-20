/* EcoBuilding frontend — MapLibre GL + EcoBuilding API (/api/v1). */

const API = "/api/v1";

// --- Usage beacon (anonymous, no cookies) ------------------------------------
function track(event, meta) {
  const body = JSON.stringify({ event, meta: meta || null });
  navigator.sendBeacon?.(`${API}/events`, new Blob([body], { type: "application/json" })) ||
    fetch(`${API}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body });
}
track("page_view");

// --- Map ----------------------------------------------------------------------
const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/liberty",
  center: [2.3522, 48.8566],
  zoom: 5.2,
  pitch: 0,
  hash: true,   // position in URL (#zoom/lat/lng/bearing/pitch), shareable & restored on load
  attributionControl: { compact: true },
});
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
  showPanel('<p class="hint">Recherche du bâtiment à votre position…</p>');
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

  // Click any building -> full record (BDNB id comes from the tile itself).
  map.on("click", "bdnb-dpe-3d", async (e) => {
    const f = e.features && e.features[0];
    const id = f && f.properties.batiment_groupe_id;
    if (!id) return;
    track("building_click");
    if (marker) marker.remove();
    showPanel('<p class="hint">Chargement des données du bâtiment…</p>');
    try {
      const r = await fetch(`${API}/buildings/${encodeURIComponent(id)}?lon=${e.lngLat.lng}&lat=${e.lngLat.lat}`);
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      renderPanel({ label: data.query.address || "Bâtiment" }, data);
    } catch {
      showPanel('<p class="hint">Données indisponibles pour ce bâtiment.</p>');
    }
  });
  map.on("mouseenter", "bdnb-dpe-3d", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "bdnb-dpe-3d", () => { map.getCanvas().style.cursor = ""; });
});

let marker = null;

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
  marker = new maplibregl.Marker({ color: "#2b7a4b" }).setLngLat([s.lon, s.lat]).addTo(map);
  showPanel('<p class="hint">Chargement des données du bâtiment…</p>');
  try {
    const r = await fetch(`${API}/lookup?ban_id=${encodeURIComponent(s.ban_id)}&lon=${s.lon}&lat=${s.lat}`);
    const data = await r.json();
    renderPanel(s, data);
    track("lookup", data.buildings?.length ? "ok" : "no_building");
  } catch {
    showPanel('<p class="hint">Erreur de chargement. Réessayez.</p>');
  }
}

// --- Panel rendering -------------------------------------------------------------
const panel = document.getElementById("panel");
const content = document.getElementById("panel-content");
document.getElementById("close").onclick = () => (panel.hidden = true);

function showPanel(html) { content.innerHTML = html; panel.hidden = false; }

function kv(k, v) {
  return v === null || v === undefined || v === "" ? "" :
    `<div class="kv"><span class="k">${k}</span><span>${v}</span></div>`;
}

function renderPanel(s, data) {
  const b = data.buildings?.[0];
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

  showPanel(`
    <h2>${b.address || s.label}</h2>
    <h3>Énergie (DPE)</h3>
    <p>${dpeBadge} ${b.energy?.consumption_kwh_m2y ? `&nbsp;${b.energy.consumption_kwh_m2y} kWh/m²/an` : ""}</p>
    ${banHtml}
    ${kv("Date du DPE", b.energy?.dpe_date)}
    ${kv("GES", b.energy?.ghg_kgco2_m2y ? b.energy.ghg_kgco2_m2y + " kgCO₂/m²/an" : null)}
    <h3>Bâtiment</h3>
    ${kv("Année de construction", b.construction_year)}
    ${kv("Hauteur moyenne", b.height_m ? b.height_m + " m" : null)}
    ${kv("Logements", b.dwellings)}
    ${kv("Murs", b.wall_material)}
    ${kv("Toit", b.roof_material)}
    <h3>Risques</h3>
    ${kv("Retrait-gonflement argiles", b.risks?.clay_shrink_swell)}
    ${risks.length ? kv("Risques de la zone", risks.join(", ")) : ""}
    ${data.area_risks?.report_url ? `<p class="hint"><a href="${data.area_risks.report_url}" target="_blank" rel="noopener">Rapport Géorisques complet →</a></p>` : ""}
    <h3>Solaire</h3>
    ${kv("Favorable au solaire thermique", b.solar?.thermal_favourable === true ? "oui" : b.solar?.thermal_favourable === false ? "non" : null)}
    ${kv("Potentiel annuel", b.solar?.thermal_potential_kwh_y ? b.solar.thermal_potential_kwh_y + " kWh/an" : null)}
    <p class="hint">ID BDNB : ${b.bdnb_id}</p>
  `);
}
