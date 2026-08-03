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
  const allowed = ['lon', 'lat', 'zoom', 'pitch', 'bearing', 'bdnb_id'];
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
    const png = await el.screenshot({ type: 'png' });
    res.type('png').send(png);
  } catch (e) {
    console.error('shot failed:', e.message);
    res.status(500).send(String(e.message));
  } finally { if (page) await page.close().catch(() => {}); }
});

app.listen(8040, () => console.log('render service on :8040'));
