// Unit test for the shared centroid helper (#97, RULES.md #9). Run: node geo.test.js
const assert = require('assert');
const { featuresCenter } = require('./geo');

// Single Polygon: bbox [0,0]-[2,2] -> centre [1,1].
assert.deepStrictEqual(
  featuresCenter([{ geometry: { type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] } }]),
  [1, 1]);

// MultiPolygon across two boxes -> centre of the overall bbox.
assert.deepStrictEqual(
  featuresCenter([{ geometry: { type: 'MultiPolygon', coordinates: [
    [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    [[[3, 3], [5, 3], [5, 5], [3, 5], [3, 3]]]] } }]),
  [2.5, 2.5]);

// No usable geometry -> null (caller falls back to the address point).
assert.strictEqual(featuresCenter([]), null);
assert.strictEqual(featuresCenter([{ geometry: null }]), null);

console.log('geo.test.js: all assertions passed');

// #441: a multi-body groupe — the pin goes to the body nearest the point,
// never to the global bbox centre (mid-lot, on the lawn).
const { nearestRingCenter } = require('./geo');
const ilot = [{ geometry: { type: 'MultiPolygon', coordinates: [
  [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
  [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]]] } }];
assert.deepStrictEqual(nearestRingCenter(ilot, [0.5, 0.5]), [1, 1]);
assert.deepStrictEqual(nearestRingCenter(ilot, [11, 11]), [11, 11]);
// Without a point, the historical behaviour stands (largest-extent framing).
assert.deepStrictEqual(nearestRingCenter(ilot, null), featuresCenter(ilot));

console.log('geo.test.js: #441 assertions passed');
