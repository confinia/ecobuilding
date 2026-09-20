// Pure geometry helper shared by app.js, render.html (browser <script>) and
// the node test (#97). Computes centers over GeoJSON Polygon/MultiPolygon
// features — used to put the pin ON the focused building instead of the
// off-center BAN address point.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ecoGeo = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  function ringBoxCenter(ring) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, seen = false;
    for (const c of ring) {
      const x = c[0], y = c[1];
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      seen = true;
    }
    return seen ? [(minX + maxX) / 2, (minY + maxY) / 2] : null;
  }
  // Outer ring of every polygon of every feature (holes don't move a center).
  function outerRings(features) {
    const rings = [];
    for (const f of features || []) {
      const g = f && f.geometry;
      if (!g) continue;
      if (g.type === 'Polygon' && g.coordinates[0]) rings.push(g.coordinates[0]);
      else if (g.type === 'MultiPolygon') {
        for (const poly of g.coordinates) if (poly[0]) rings.push(poly[0]);
      }
    }
    return rings;
  }
  function featuresCenter(features) {
    const rings = outerRings(features);
    if (!rings.length) return null;
    return ringBoxCenter(rings.flat());
  }
  // Un « bâtiment groupe » BDNB peut réunir plusieurs corps (un îlot de
  // lotissement : quatorze maisons, #441). Le centre GLOBAL tombe alors au
  // milieu du lot, sur la pelouse. Ici : le centre du CORPS le plus proche
  // du point demandé — l'adresse ou le clic dit quelle maison est la sienne.
  function nearestRingCenter(features, point) {
    if (!point || point[0] == null || point[1] == null) return featuresCenter(features);
    const k = Math.cos(point[1] * Math.PI / 180);
    let best = null, bestD = Infinity;
    for (const ring of outerRings(features)) {
      const c = ringBoxCenter(ring);
      if (!c) continue;
      const d = ((c[0] - point[0]) * k) ** 2 + (c[1] - point[1]) ** 2;
      if (d < bestD) { best = c; bestD = d; }
    }
    return best;
  }
  return { featuresCenter, nearestRingCenter };
}));
