// Pure geometry helper shared by render.html (browser <script>) and the node
// test (#97). Computes the center of the bounding box over a list of GeoJSON
// Polygon/MultiPolygon features — used to recenter the 3D map on the focused
// building instead of the off-center BAN address point.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ecoGeo = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  function featuresCenter(features) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, seen = false;
    const addRing = (ring) => {
      for (const c of ring) {
        const x = c[0], y = c[1];
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
        seen = true;
      }
    };
    for (const f of features || []) {
      const g = f && f.geometry;
      if (!g) continue;
      if (g.type === 'Polygon') g.coordinates.forEach(addRing);
      else if (g.type === 'MultiPolygon') g.coordinates.forEach((poly) => poly.forEach(addRing));
    }
    return seen ? [(minX + maxX) / 2, (minY + maxY) / 2] : null;
  }
  return { featuresCenter };
}));
