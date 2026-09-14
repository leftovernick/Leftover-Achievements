// Run with: node tests/charts_frontend.cjs
// Exercise the shipped controller without adding a browser dependency to the app.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(dataset = {}) {
    this.dataset = dataset;
    this.listeners = {};
    this.classes = new Set();
    this.classList = { toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name) };
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  click() { return this.listeners.click(); }
}
const ranges = ['4', '8', '12', 'all'].map((value) => new Element({ chartRange: value }));
const metrics = ['hardcore_points', 'retro_points'].map((value) => new Element({ chartMetric: value }));
const elements = new Map();
function element(key) {
  if (!elements.has(key)) elements.set(key, new Element());
  return elements.get(key);
}
class Chart {
  static defaults = { font: {} };
  constructor(canvas, config) {
    this.data = config.data;
    this.options = config.options;
    canvas.chart = this;
  }
  destroy() { this.destroyed = true; }
  isDatasetVisible(index) { return !this.data.datasets[index].hidden; }
  setDatasetVisibility(index, visible) { this.data.datasets[index].hidden = !visible; }
  update() {}
}
const allTime = {
  configured: true, ready_users: 2, building: false, needs_refresh: false,
  start: '2010-01-01T00:00:00Z', end: '2026-09-14T00:00:00Z', progress: {},
  users: [
    { username: 'First', user_key: '1', ready: true, as_of: '2026-09-14T00:00:00Z', points: [
      { date: '2010-01-01T00:00:00Z', hardcore_points: 0, retro_points: 0 },
      { date: '2026-09-14T00:00:00Z', hardcore_points: 100, retro_points: 300 },
    ] },
    { username: 'Later', user_key: '2', ready: true, as_of: '2026-09-14T00:00:00Z', points: [
      { date: '2018-01-01T00:00:00Z', hardcore_points: 0, retro_points: 0 },
      { date: '2026-09-14T00:00:00Z', hardcore_points: 50, retro_points: 200 },
    ] },
  ],
};
const weekly = { range_weeks: 8, weeks: [{ label: 'Week', users: [
  { user_key: '1', canonical_username: 'First', hardcore_points: 10, retro_points: 30, rank: 1 },
] }] };
let nextAllTime = allTime;
let responseStatus = 200;
const requests = [];
const consoleErrors = [];
const timers = new Map();
let timerId = 0;
const context = {
  Chart, AbortController, console: { ...console, error: (error) => consoleErrors.push(error) },
  document: {
    querySelector: element,
    querySelectorAll: (selector) => selector === '[data-chart-range]' ? ranges : selector === '[data-chart-metric]' ? metrics : [],
    getElementById: element,
  },
  window: {
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    addEventListener() {},
  },
  fetch: async (url, options) => {
    requests.push({ url, method: options.method });
    return { ok: responseStatus === 200, status: responseStatus, json: async () => url.includes('all-time') ? nextAllTime : weekly };
  },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/charts.js'), 'utf8'), context);

(async () => {
  await new Promise(setImmediate);
  assert.equal(element('hardcore-points-chart').chart.data.datasets[0].data[0], 10);
  await ranges[3].click();
  let chart = element('all-time-score-chart').chart;
  assert.equal(chart.data.datasets.length, 2);
  assert.equal(chart.options.scales.y.min, 0);
  assert.equal(chart.options.scales.x.min, Date.parse(allTime.start));
  assert.equal(chart.data.datasets[1].data[0].x, Date.parse('2018-01-01T00:00:00Z'));
  assert.equal(chart.data.datasets[0].data[0].y, 0);
  chart.options.plugins.legend.onClick(null, { datasetIndex: 0 }, { chart });
  assert.equal(chart.options.scales.x.min, Date.parse('2018-01-01T00:00:00Z'));
  metrics[1].click();
  chart = element('all-time-score-chart').chart;
  assert.equal(chart.data.datasets[0].hidden, true);
  assert.equal(chart.options.scales.x.min, Date.parse('2018-01-01T00:00:00Z'));
  chart.options.plugins.legend.onClick(null, { datasetIndex: 1 }, { chart });
  assert.equal(chart.options.scales.x.min, Date.parse(allTime.start), 'all-hidden state must have a finite fallback');
  chart.options.plugins.legend.onClick(null, { datasetIndex: 0 }, { chart });
  chart.options.plugins.legend.onClick(null, { datasetIndex: 1 }, { chart });
  assert.equal(chart.options.scales.x.min, Date.parse(allTime.start));
  chart.data.datasets[1].hidden = true;
  const requestCount = requests.length;
  metrics[1].click();
  chart = element('all-time-score-chart').chart;
  assert.equal(requests.length, requestCount, 'metric toggle must not fetch');
  assert.equal(chart.data.datasets[0].data.at(-1).y, 300);
  assert.equal(chart.data.datasets[1].hidden, true);
  assert.equal(element('[data-all-time-title]').textContent, 'All-Time RetroPoints');
  await ranges[1].click();
  assert.equal(element('[data-chart-all-time]').hidden, true);
  assert.equal(element('[data-chart-grid]').hidden, false);
  nextAllTime = { ...allTime, ready_users: 0, building: true,
    progress: { completed: 2, total: 100, current: 'First · Jan 2010' },
    users: allTime.users.map((user) => ({ ...user, points: [], ready: false })),
  };
  await ranges[3].click();
  assert.equal(element('[data-all-time-canvas]').hidden, true);
  assert.match(element('[data-all-time-status]').textContent, /2 \/ 100/);
  assert.equal(timers.size, 1);
  await ranges[0].click();
  assert.equal(timers.size, 0, 'weekly navigation cancels backfill polling');
  nextAllTime = allTime;
  await element('[data-all-time-refresh]').click();
  assert.equal(requests.at(-1).method, 'POST');
  assert.equal(element('[data-all-time-canvas]').hidden, false);
  responseStatus = 404;
  await ranges[3].click();
  assert.equal(element('[data-chart-error]').hidden, false);
  assert.match(element('[data-chart-error]').textContent, /HTTP 404 from \/api\/charts\/all-time/);
  assert.match(element('[data-chart-error]').textContent, /does not have the All Time endpoint/);
  assert.equal(ranges[3].classes.has('active'), true);
  assert.equal(ranges[2].classes.has('active'), false);
  assert.equal(element('[data-all-time-canvas]').hidden, true);
  responseStatus = 500;
  await ranges[3].click();
  assert.match(element('[data-chart-error]').textContent, /HTTP 500/);
  assert.match(element('[data-chart-error]').textContent, /Recent Errors/);
  responseStatus = 200;
  await ranges[3].click();
  assert.equal(element('[data-chart-error]').hidden, true);
  assert.equal(consoleErrors.length, 2);
  console.log('Charts frontend: metric toggle, shared timeline, zero axis, pending state, polling cancellation, and refresh passed.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
