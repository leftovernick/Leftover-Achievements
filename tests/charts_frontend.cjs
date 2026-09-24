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
    this.classList = {
      toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name),
      add: (name) => this.classes.add(name),
      remove: (name) => this.classes.delete(name),
    };
    this.style = {};
    this.clientWidth = 800;
    this.scrollLeft = 0;
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  click() { return this.listeners.click(); }
}
const ranges = ['4', '8', '12'].map((value) => new Element({ chartRange: value }));
const metrics = ['hardcore_points', 'retro_points'].map((value) => new Element({ chartMetric: value }));
const views = ['fit', 'timeline'].map((value) => new Element({ chartView: value }));
const activityViews = ['weekday', 'monthly'].map((value) => new Element({ activityView: value }));
const awards = ['mastery', 'beaten'].map((value) => Object.assign(new Element({chartAwards: value}), {checked: true}));
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
  weekday_activity: [
    {weekday: 'Monday', achievements_earned: 42, eligible_days: 100, average: 0.42},
    {weekday: 'Tuesday', achievements_earned: 30, eligible_days: 100, average: 0.30},
    {weekday: 'Wednesday', achievements_earned: 25, eligible_days: 100, average: 0.25},
    {weekday: 'Thursday', achievements_earned: 20, eligible_days: 100, average: 0.20},
    {weekday: 'Friday', achievements_earned: 35, eligible_days: 100, average: 0.35},
    {weekday: 'Saturday', achievements_earned: 60, eligible_days: 100, average: 0.60},
    {weekday: 'Sunday', achievements_earned: 50, eligible_days: 100, average: 0.50},
  ],
  monthly_activity: [
    {month: 'January', achievements_earned: 80, eligible_months: 10, average: 8},
    {month: 'February', achievements_earned: 70, eligible_months: 10, average: 7},
    {month: 'March', achievements_earned: 90, eligible_months: 10, average: 9},
    {month: 'April', achievements_earned: 60, eligible_months: 10, average: 6},
    {month: 'May', achievements_earned: 100, eligible_months: 10, average: 10},
    {month: 'June', achievements_earned: 110, eligible_months: 10, average: 11},
    {month: 'July', achievements_earned: 120, eligible_months: 10, average: 12},
    {month: 'August', achievements_earned: 130, eligible_months: 10, average: 13},
    {month: 'September', achievements_earned: 140, eligible_months: 10, average: 14},
    {month: 'October', achievements_earned: 150, eligible_months: 10, average: 15},
    {month: 'November', achievements_earned: 160, eligible_months: 10, average: 16},
    {month: 'December', achievements_earned: 170, eligible_months: 10, average: 17},
  ],
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
const logoImages = [];
const logoDraws = [];
const timers = new Map();
let timerId = 0;
let clock = Date.now();
class TestDate extends Date { static now() { return clock; } }
const context = {
  Chart, Date: TestDate, AbortController, Image: class {
    naturalWidth = 40;
    naturalHeight = 20;
    set src(url) { logoImages.push(url); this.onload?.(); }
  },
  console: { ...console, error: (error) => consoleErrors.push(error) },
  document: {
    querySelector: element,
    querySelectorAll: (selector) => selector === '[data-chart-range]' ? ranges : selector === '[data-chart-metric]' ? metrics : selector === '[data-chart-view]' ? views : selector === '[data-chart-awards]' ? awards : selector === '[data-activity-view]' ? activityViews : [],
    getElementById: element,
    createElement: () => ({getContext: () => ({fillRect() {}, strokeRect() {}, drawImage: (...args) => logoDraws.push(args)})}),
  },
  window: {
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    addEventListener() {},
    requestAnimationFrame: (callback) => callback(),
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
  let activityChart = element('achievement-activity-chart').chart;
  assert.equal(activityChart.data.labels[0], 'Monday');
  assert.equal(activityChart.data.datasets[0].data[5], 0.60);
  assert.equal(activityChart.options.plugins.legend.display, false);
  assert.match(activityChart.options.plugins.tooltip.callbacks.afterLabel({dataIndex: 0}), /42 achievements across 100 player-days/);
  assert.equal(element('[data-chart-activity]').hidden, false);
  const activityRequestCount = requests.length;
  activityViews[1].click();
  activityChart = element('achievement-activity-chart').chart;
  assert.equal(requests.length, activityRequestCount, 'activity toggle must not fetch');
  assert.equal(activityViews[1].classes.has('active'), true);
  assert.equal(element('[data-activity-title]').textContent, 'Achievements Earned by Month');
  const monthlyActivityChart = activityChart;
  assert.equal(monthlyActivityChart.data.labels[0], 'January');
  assert.equal(monthlyActivityChart.data.datasets[0].data[11], 17);
  assert.equal(monthlyActivityChart.options.plugins.legend.display, false);
  assert.match(monthlyActivityChart.options.plugins.tooltip.callbacks.afterLabel({dataIndex: 0}), /80 achievements across 10 player-months/);
  activityViews[0].click();
  const rankChart = element('rank-history-chart').chart;
  assert.ok(rankChart.options.scales.y.min < 1);
  assert.ok(rankChart.options.scales.y.max > 1);
  assert.equal(rankChart.options.scales.y.ticks.callback(0), '');
  assert.equal(rankChart.options.scales.y.ticks.callback(1), 1);
  let chart = element('all-time-score-chart').chart;
  assert.equal(chart.data.datasets.length, 2);
  assert.equal(chart.options.scales.y.min, 0);
  assert.equal(chart.options.scales.x.min, Date.parse(allTime.start));
  assert.equal(chart.data.datasets[1].data[0].x, Date.parse('2018-01-01T00:00:00Z'));
  assert.equal(chart.data.datasets[0].data[0].y, 0);
  views[1].click();
  chart = element('all-time-score-chart').chart;
  const monthWidth = 30.4375 * 24 * 60 * 60 * 1000;
  assert.ok(Math.abs((chart.options.scales.x.max - chart.options.scales.x.min) - monthWidth) < 1);
  assert.ok(chart.options.scales.y.max < 10, 'the visible month sets the vertical scale instead of the lifetime maximum');
  assert.equal(chart.options.scales.y.min, 0);
  assert.ok(parseFloat(element('[data-all-time-scroll-track]').style.width) > 800);
  assert.equal(element('[data-all-time-canvas]').classes.has('timeline-view'), true);
  const firstWindowStart = chart.options.scales.x.min;
  element('[data-all-time-canvas]').scrollLeft = 800;
  element('[data-all-time-canvas]').listeners.scroll();
  assert.ok(chart.options.scales.x.min > firstWindowStart, 'horizontal scrolling advances the date window');
  views[0].click();
  chart = element('all-time-score-chart').chart;
  assert.equal(chart.options.scales.x.min, Date.parse(allTime.start));
  assert.equal(chart.options.scales.x.max, Date.parse(allTime.end));
  assert.ok(chart.options.scales.y.max > 100, 'Fit History restores a vertical range for all visible scores');
  assert.equal(element('[data-all-time-canvas]').classes.has('timeline-view'), false);
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
  assert.notEqual(element('[data-chart-all-time]').hidden, true);
  assert.equal(element('[data-chart-grid]').hidden, false);
  nextAllTime = { ...allTime, ready_users: 0, building: true,
    progress: { completed: 2, total: 100, current: 'First · Jan 2010' },
    users: allTime.users.map((user) => ({ ...user, points: [], ready: false })),
  };
  await element('[data-all-time-refresh]').click();
  assert.equal(element('[data-all-time-canvas]').hidden, true);
  assert.match(element('[data-all-time-status]').textContent, /2 \/ 100/);
  assert.equal(timers.size, 1);
  await ranges[0].click();
  assert.equal(timers.size, 1, 'weekly navigation must not cancel independent all-time polling');
  nextAllTime = allTime;
  await element('[data-all-time-refresh]').click();
  assert.equal(requests.at(-1).method, 'POST');
  assert.equal(element('[data-all-time-canvas]').hidden, false);
  responseStatus = 404;
  await element('[data-all-time-refresh]').click();
  assert.equal(element('[data-chart-error]').hidden, true);
  assert.match(element('[data-all-time-status]').textContent, /HTTP 404 from \/api\/charts\/all-time\/refresh/);
  assert.match(element('[data-all-time-status]').textContent, /does not have the All Time endpoint/);
  assert.equal(ranges[0].classes.has('active'), true);
  assert.equal(element('[data-all-time-canvas]').hidden, true);
  responseStatus = 500;
  await element('[data-all-time-refresh]').click();
  assert.match(element('[data-all-time-status]').textContent, /HTTP 500/);
  assert.match(element('[data-all-time-status]').textContent, /Recent Errors/);
  responseStatus = 200;
  await element('[data-all-time-refresh]').click();
  assert.equal(consoleErrors.length, 2);
  allTime.users[0].masteries = [{ game_id: 1, game_title: 'Example Game', game_image: 'https://example.test/logo.png', date: '2020-01-01T00:00:00Z' }];
  await element('[data-all-time-refresh]').click();
  chart = element('all-time-score-chart').chart;
  let marker = chart.data.datasets.find((dataset) => dataset.isMastery);
  assert.equal(marker.clip, false, 'edge award thumbnails must not be clipped at the plot boundary');
  assert.ok(chart.options.layout.padding.left >= 11);
  assert.ok(chart.options.layout.padding.right >= 11);
  assert.ok(chart.options.layout.padding.bottom >= 11);
  assert.ok(chart.options.scales.x.ticks.padding >= 11, 'keep bottom thumbnails clear of date labels');
  assert.equal(marker.data[0].x, Date.parse('2020-01-01T00:00:00Z'));
  assert.equal(marker.data[0].gameTitle, 'Example Game');
  const logo = marker.pointStyle({raw: marker.data[0]});
  assert.equal(logo.width, 22);
  assert.equal(logo.height, 22);
  assert.equal(logoDraws[0][3] / logoDraws[0][4], 2, 'square framing preserves the artwork aspect ratio');
  assert.equal(marker.pointStyle({raw: marker.data[0]}), logo);
  assert.equal(marker.pointRadius({raw: marker.data[0]}), 9);
  assert.equal(logoImages.length, 1, 'game logo is cached across redraws');
  assert.equal(marker.pointStyle({raw: {}}), 'rect');
  assert.match(chart.options.plugins.tooltip.callbacks.label({ dataset: marker, raw: marker.data[0] }), /Mastery: Example Game/);
  assert.equal(chart.options.plugins.legend.labels.filter({datasetIndex: 2}, chart.data), false);
  timers.clear();
  const play = element('[data-timeline-play]');
  play.click();
  chart = element('all-time-score-chart').chart;
  assert.equal(views[0].classes.has('active'), true, 'Fit History playback stays in Fit History');
  assert.equal(play.textContent, '❚❚ Pause');
  assert.equal(chart.data.datasets.find((dataset) => dataset.isMastery).data.length, 0);
  clock += 11 * 365.25 / 30.4375 / 2.5 * 1000;
  [...timers.values()].at(-1)();
  const poppedMastery = chart.data.datasets.find((dataset) => dataset.isMastery);
  assert.equal(poppedMastery.data.length, 1,
    'mastery marker appears only when playback reaches its date');
  assert.equal(poppedMastery.pointRadius({raw: poppedMastery.data[0]}), 0,
    'new award marker starts collapsed');
  assert.equal(poppedMastery.pointStyle({raw: poppedMastery.data[0]}).width, 1,
    'canvas-image marker itself starts collapsed');
  clock += 400;
  assert.ok(poppedMastery.pointRadius({raw: poppedMastery.data[0]}) > 9,
    'award marker visibly overshoots its normal size');
  assert.ok(poppedMastery.pointStyle({raw: poppedMastery.data[0]}).width > 22,
    'canvas-image marker dimensions participate in the overshoot');
  clock += 300;
  assert.equal(poppedMastery.pointRadius({raw: poppedMastery.data[0]}), 9,
    'award marker settles at its normal size');
  assert.equal(poppedMastery.pointStyle({raw: poppedMastery.data[0]}).width, 22);
  assert.equal(element('[data-all-time-canvas]').scrollLeft, 0, 'Fit History playback does not scroll');
  play.click();
  assert.equal(play.textContent, '▶ Play');
  timers.clear();
  views[1].click();
  play.click();
  clock += 5000;
  [...timers.values()].at(-1)();
  assert.ok(element('[data-all-time-canvas]').scrollLeft > 0, 'Monthly Timeline playback follows the playhead');
  const monthlyChart = element('all-time-score-chart').chart;
  const monthlyLineEnd = monthlyChart.data.datasets
    .filter((dataset) => !dataset.isAward && dataset.data.length)
    .map((dataset) => dataset.data.at(-1).x)
    .reduce((latest, value) => Math.max(latest, value), 0);
  assert.ok(monthlyChart.options.scales.x.max > monthlyLineEnd,
    'Monthly playback leaves visible space ahead of the drawing line');
  play.click();
  views[0].click();
  chart = element('all-time-score-chart').chart;
  marker = chart.data.datasets.find((dataset) => dataset.isMastery);
  if (!chart.isDatasetVisible(1)) chart.options.plugins.legend.onClick(null, {datasetIndex: 1}, {chart});
  chart.options.plugins.legend.onClick(null, {datasetIndex: 0}, {chart});
  assert.equal(marker.hidden, true);
  assert.equal(chart.options.scales.x.min, Date.parse('2018-01-01T00:00:00Z'));
  timers.clear();
  play.click();
  assert.equal(chart.options.scales.x.min, Date.parse('2018-01-01T00:00:00Z'),
    'playback starts with the earliest visible player, not a hidden player');
  assert.equal(chart.data.datasets[1].data[0].x, Date.parse('2018-01-01T00:00:00Z'));
  play.click();
  metrics[0].click();
  chart = element('all-time-score-chart').chart;
  marker = chart.data.datasets.find((dataset) => dataset.isMastery);
  assert.equal(marker.hidden, true);
  assert.ok(marker.data[0].y < 100, 'marker score follows the selected metric');
  chart.options.plugins.legend.onClick(null, {datasetIndex: 0}, {chart});
  assert.equal(marker.hidden, false);
  allTime.users[0].beaten = [{date: '2021-01-01T00:00:00Z', game_id: 88, game_title: 'Beaten Game', game_image: 'https://example.test/beaten.png'}];
  await element('[data-all-time-refresh]').click();
  chart = element('all-time-score-chart').chart;
  let beaten = chart.data.datasets.find((dataset) => dataset.awardKind === 'beaten');
  assert.equal(beaten.backgroundColor, '#f2f2f2');
  assert.equal(beaten.clip, false);
  assert.match(chart.options.plugins.tooltip.callbacks.label({dataset: beaten, raw: beaten.data[0]}), /Beaten: Beaten Game/);
  const beforeToggleRequests = requests.length;
  awards[0].checked = false;
  awards[0].listeners.change();
  chart = element('all-time-score-chart').chart;
  assert.equal(chart.data.datasets.find((dataset) => dataset.isMastery).hidden, true);
  assert.equal(chart.data.datasets.find((dataset) => dataset.awardKind === 'beaten').hidden, false);
  chart.options.plugins.legend.onClick(null, {datasetIndex: 0}, {chart});
  chart.options.plugins.legend.onClick(null, {datasetIndex: 0}, {chart});
  assert.equal(chart.data.datasets.find((dataset) => dataset.isMastery).hidden, true);
  awards[1].checked = false;
  awards[1].listeners.change();
  await metrics[1].click();
  chart = element('all-time-score-chart').chart;
  assert.equal(chart.data.datasets[0].hidden, false);
  assert.equal(chart.data.datasets.filter((dataset) => dataset.isAward).every((dataset) => dataset.hidden), true);
  awards[0].checked = true;
  awards[0].listeners.change();
  chart = element('all-time-score-chart').chart;
  assert.equal(chart.data.datasets.find((dataset) => dataset.isMastery).hidden, false);
  assert.equal(chart.data.datasets.find((dataset) => dataset.awardKind === 'beaten').hidden, true);
  assert.equal(requests.length, beforeToggleRequests);
  nextAllTime = {...allTime, start: null, users: allTime.users.map((user) => ({...user, points: []}))};
  await element('[data-all-time-refresh]').click();
  assert.equal(element('[data-all-time-canvas]').hidden, true);
  assert.match(element('[data-all-time-status]').textContent, /No Hardcore scoring achievements/);
  console.log('Charts frontend: permanent all-time panel, independent loading, metric/award toggles, and refresh passed.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
