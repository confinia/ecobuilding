// EcoBuilding render service (#88): headless-Chromium screenshot of the
// DPE-3D building map, for embedding in the PDF report. Public sources only
// (OpenFreeMap + BDNB tiles); no auth. GET /shot?lon&lat&zoom&pitch&bearing&bdnb_id
// -> image/png. ufw blocks the published port; the API reaches it via the host
// gateway (host.containers.internal:8040), same pattern as bdnb-rest / Keycloak.
const express = require('express');
const puppeteer = require('puppeteer');
const path = require('path');

const app = express();

// MapLibre 6.x is ESM-only and its tile-worker chunk MUST be served same-origin
// (loading it from a CDN like esm.sh silently breaks the worker → the map never
// fires load/idle). So we serve render.html + the vendored maplibre dist over
// http from this same server, and puppeteer navigates to http://localhost, not
// file://. render.html and geo.js live in __dirname; the dist ships in
// node_modules via the maplibre-gl dependency.
const MAPLIBRE_DIST = path.join(__dirname, 'node_modules', 'maplibre-gl', 'dist');
app.use('/vendor/maplibre', express.static(MAPLIBRE_DIST));
app.get('/render.html', (_req, res) => res.sendFile(path.join(__dirname, 'render.html')));
app.get('/geo.js', (_req, res) => res.sendFile(path.join(__dirname, 'geo.js')));

let browserP;
function browser() {
  if (!browserP) browserP = puppeteer.launch({
    headless: 'new',
    // Software WebGL via SwiftShader. Chrome 119+ gates it behind this flag;
    // adding --use-gl=angle here actually breaks context creation (probed).
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
           '--enable-unsafe-swiftshader'],
  });
  return browserP;
}

app.get('/healthz', (_req, res) => res.type('text').send('ok'));

app.get('/shot', async (req, res) => {
  // `tiles` : gabarit d'URL des tuiles bâtiments, fourni par l'API (son cache).
  const allowed = ['lon', 'lat', 'zoom', 'pitch', 'bearing', 'bdnb_id', 'tiles'];
  const qs = allowed.filter(k => req.query[k] != null)
    .map(k => `${k}=${encodeURIComponent(req.query[k])}`).join('&');
  if (req.query.lon == null || req.query.lat == null) return res.status(400).send('lon/lat required');
  const url = 'http://127.0.0.1:8040/render.html?' + qs;   // same-origin (see MAPLIBRE_DIST note)
  let page;
  try {
    page = await (await browser()).newPage();
    await page.setViewport({ width: 960, height: 540, deviceScaleFactor: 2 });
    await page.goto(url, { waitUntil: 'load', timeout: 30000 });
    await page.waitForFunction('window.__ready===true || window.__error', { timeout: 30000 });
    const err = await page.evaluate('window.__error || null');
    if (err) throw new Error('map error: ' + err);
    await new Promise(r => setTimeout(r, 800));   // let tiles settle
    const el = await page.$('#map');
    // JPEG et non PNG : la capture pesait 0,6 à 1,3 Mo (960×540 à l'échelle 2)
    // et ces octets se payaient trois fois — composition WeasyPrint (~5 s
    // mesurées, #280), poids du PDF téléchargé, place au cache. Une carte en
    // aplats souffre peu du JPEG à cette qualité.
    const img = await el.screenshot({ type: 'jpeg', quality: 85 });
    res.type('jpeg').send(img);
  } catch (e) {
    console.error('shot failed:', e.message);
    res.status(500).send(String(e.message));
  } finally { if (page) await page.close().catch(() => {}); }
});

// GARDIEN DE CHALEUR (#337). Le premier cliché après une période calme
// coûtait ~48 s (mesuré : p95 render_3d à 48,8 s un dimanche à minuit,
// toutes les autres étapes à ~5 s) — le navigateur, ses tuiles de fond et
// le style se réchauffent à la première demande, et c'est un VRAI
// utilisateur qui payait. Un cliché factice au démarrage puis toutes les dix
// minutes garde tout tiède ; toujours la même vue, donc coût marginal.
const CHAUFFE_MS = 10 * 60 * 1000;
let chauffeEnCours = false;
async function chauffe() {
  if (chauffeEnCours) return;
  chauffeEnCours = true;
  const t0 = Date.now();
  try {
    const r = await fetch('http://127.0.0.1:8040/shot?lon=2.3488&lat=48.8534&zoom=18&pitch=60&bearing=-30');
    console.log(`chauffe: ${r.status} en ${Date.now() - t0} ms`);
  } catch (e) {
    console.error('chauffe échouée:', e.message);
  } finally { chauffeEnCours = false; }
}

app.listen(8040, () => {
  console.log('render service on :8040');
  setTimeout(chauffe, 2000);            // dès le démarrage
  setInterval(chauffe, CHAUFFE_MS);
});
