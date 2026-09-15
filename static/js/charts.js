(() => {
  const rangeButtons = [...document.querySelectorAll("[data-chart-range]")];
  const chartGrid = document.querySelector("[data-chart-grid]");
  const emptyState = document.querySelector("[data-chart-empty]");
  const errorState = document.querySelector("[data-chart-error]");
  const coverageLabels = document.querySelectorAll("[data-chart-coverage]");
  const charts = {};
  const awardLogos = new Map();
  let logoRedrawPending = false;
  function awardPointStyle(url, color) {
    if (!url) return 'rect';
    const key = `${color}:${url}`;
    if (!awardLogos.has(key)) {
      const cached = { icon: null };
      awardLogos.set(key, cached);
      const image = new Image();
      image.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 22;
        const context = canvas.getContext('2d');
        context.fillStyle = '#202020';
        context.fillRect(0, 0, 22, 22);
        const ratio = Math.min(20 / image.naturalWidth, 20 / image.naturalHeight);
        const width = image.naturalWidth * ratio;
        const height = image.naturalHeight * ratio;
        context.drawImage(image, (22 - width) / 2, (22 - height) / 2, width, height);
        context.strokeStyle = color;
        context.lineWidth = 1;
        context.strokeRect(0.5, 0.5, 21, 21);
        cached.icon = canvas;
        if (!logoRedrawPending) {
          logoRedrawPending = true;
          window.requestAnimationFrame(() => {
            logoRedrawPending = false;
            charts.allTime?.update('none');
          });
        }
      };
      image.src = url;
    }
    return awardLogos.get(key).icon || 'rect';
  }
  const allTimeStatus = document.querySelector('[data-all-time-status]');
  const allTimeCanvas = document.querySelector('[data-all-time-canvas]');
  const allTimeRefresh = document.querySelector('[data-all-time-refresh]');
  const metricButtons = [...document.querySelectorAll('[data-chart-metric]')];
  const awardToggles = [...document.querySelectorAll('[data-chart-awards]')];
  const visibleAwards = { mastery: true, beaten: true };
  let selectedMetric = 'hardcore_points';
  let allTimeData;
  let pollTimer;
  let weeklyGeneration = 0;
  let weeklyController;
  let allTimeGeneration = 0;
  let allTimeController;

  const palette = [
    "#ffcf21", "#2299ff", "#67b985", "#e87979", "#b58cff", "#ff9f43",
    "#4fd1c5", "#f687b3", "#90cdf4", "#c6e377", "#f6ad55", "#a0aec0",
  ];

  Chart.defaults.color = "#a4a4a4";
  Chart.defaults.borderColor = "rgba(255, 255, 255, 0.08)";
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';

  function seriesFromWeeks(weeks, field) {
    const identities = new Map();
    for (const week of weeks) {
      for (const user of week.users) {
        if (field === "rank" && (user.hardcore_points <= 0 || user.rank === null)) continue;
        identities.set(user.user_key, user.canonical_username);
      }
    }

    return [...identities.entries()].map(([userKey, username], index) => ({
      label: username,
      userKey,
      data: weeks.map((week) => {
        const user = week.users.find((item) => item.user_key === userKey);
        if (field === "rank") {
          if (!user || user.hardcore_points <= 0 || user.rank === null) {
            return { x: week.label, y: null, week: week.label };
          }
          return {
            x: week.label,
            y: user.rank,
            week: week.label,
            hardcorePoints: user.hardcore_points,
            retroPoints: user.retro_points,
          };
        }
        if (!user) return null;
        return user[field];
      }),
      borderColor: palette[index % palette.length],
      backgroundColor: palette[index % palette.length],
      pointBackgroundColor: "#202020",
      pointBorderColor: palette[index % palette.length],
      pointBorderWidth: 2,
      pointRadius: 3,
      pointHoverRadius: 5,
      borderWidth: 2,
      tension: field === "rank" ? 0.12 : 0.25,
      spanGaps: false,
    }));
  }

  function baseOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 10, boxHeight: 10, padding: 13, usePointStyle: true },
        },
        tooltip: {
          backgroundColor: "#111111",
          borderColor: "#383838",
          borderWidth: 1,
          titleColor: "#ffcf21",
          bodyColor: "#e8e8e8",
          padding: 10,
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.045)" },
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(255, 255, 255, 0.065)" },
          ticks: { precision: 0 },
        },
      },
    };
  }

  function replaceChart(name, canvasId, config) {
    if (charts[name]) charts[name].destroy();
    charts[name] = new Chart(document.getElementById(canvasId), config);
  }

  function renderCharts(data) {
    const weeks = data.weeks;
    const labels = weeks.map((week) => week.label);
    const coverage = `${weeks.length} completed week${weeks.length === 1 ? "" : "s"}`;
    coverageLabels.forEach((label) => { label.textContent = coverage; });

    replaceChart("hardcore", "hardcore-points-chart", {
      type: "line",
      data: { labels, datasets: seriesFromWeeks(weeks, "hardcore_points") },
      options: baseOptions(),
    });

    replaceChart("retro", "retro-points-chart", {
      type: "line",
      data: { labels, datasets: seriesFromWeeks(weeks, "retro_points") },
      options: baseOptions(),
    });

    const rankOptions = baseOptions();
    const largestRank = Math.max(
      1,
      ...weeks.flatMap((week) => week.users
        .filter((user) => user.hardcore_points > 0 && user.rank !== null)
        .map((user) => user.rank)),
    );
    const rankGutter = Math.max(0.5, largestRank * 0.04);
    rankOptions.scales.y = {
      reverse: true,
      min: 1 - rankGutter,
      max: largestRank + rankGutter,
      grid: { color: "rgba(255, 255, 255, 0.065)" },
      ticks: {
        precision: 0,
        stepSize: 1,
        callback: (value) => Number.isInteger(value) && value >= 1 && value <= largestRank ? value : '',
      },
      title: { display: true, text: "Weekly rank" },
    };
    rankOptions.plugins.tooltip.callbacks = {
      title(items) { return items[0]?.raw?.week || ""; },
      label(context) {
        const point = context.raw;
        return [
          context.dataset.label,
          `Rank: ${point.y}`,
          `Hardcore Points: ${point.hardcorePoints.toLocaleString()}`,
          `RetroPoints: ${point.retroPoints.toLocaleString()}`,
        ];
      },
    };
    replaceChart("rank", "rank-history-chart", {
      type: "line",
      data: { labels, datasets: seriesFromWeeks(weeks, "rank") },
      options: rankOptions,
    });
  }

  function renderAllTime(data) {
    allTimeData = data;
    const metricLabel = selectedMetric === 'hardcore_points' ? 'Hardcore Points' : 'RetroPoints';
    document.querySelector('[data-all-time-title]').textContent = `All-Time ${metricLabel}`;
    const pending = data.users.filter((user) => !user.ready).map((user) => user.username);
    const errors = data.users.filter((user) => user.error).map((user) => `${user.username}: ${user.error}`);
    let status;
    if (!data.configured) {
      status = 'Connect RetroAchievements in Settings to load account history.';
    } else if (!data.users.length) {
      status = 'Add players in Users to compare their lifetime scores.';
    } else if (data.building) {
      const progress = data.progress;
      status = `Building account history: ${progress.completed} / ${progress.total} monthly ranges saved. ${progress.current || ''}`;
    } else if (pending.length) {
      status = `History incomplete for ${pending.join(', ')}. Saved progress will resume on retry.`;
    } else if (data.needs_refresh) {
      status = 'Showing cached account history. Refresh to update the latest totals.';
    } else {
      const asOf = data.users.filter((user) => user.as_of).map((user) => Date.parse(user.as_of));
      status = `${data.ready_users} players · weekly-resolution history · totals refreshed ${new Date(Math.min(...asOf)).toLocaleString()}`;
    }
    if (errors.length) status += ` ${errors.join(' ')}`;
    allTimeStatus.textContent = status;
    allTimeRefresh.disabled = data.building || !data.configured || !data.users.length;
    const hasScores = data.users.some((user) => user.points.length);
    allTimeCanvas.hidden = !hasScores;
    metricButtons.forEach((button) => {
      const active = button.dataset.chartMetric === selectedMetric;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    if (!hasScores) {
      if (!data.building && data.users.length && data.ready_users === data.users.length) {
        allTimeStatus.textContent = 'No Hardcore scoring achievements have been recorded for these players yet.';
      }
      return;
    }
    const options = baseOptions();
    const formatDate = (value) => new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
    options.scales.x.type = 'linear';
    options.scales.x.min = Date.parse(data.start);
    options.scales.x.max = Date.parse(data.end);
    options.scales.x.ticks.callback = (value) => formatDate(value);
    options.scales.x.title = { display: true, text: 'Achievement history (UTC)' };
    options.scales.y.min = 0;
    options.scales.y.title = { display: true, text: metricLabel };
    // Logos are centered on their data point, including at the date/zero boundaries.
    // Reserve a pixel gutter and let award thumbnails draw into it instead of
    // clipping half an icon or inventing earlier dates / negative scores.
    options.layout = { padding: { left: 16, right: 16, top: 16, bottom: 16 } };
    options.scales.x.ticks.padding = 16;
    options.scales.y.ticks.padding = 16;
    options.plugins.tooltip.callbacks = {
      title: (items) => items[0]?.dataset.isAward
        ? `${new Date(items[0].parsed.x).toLocaleString(undefined, { timeZone: 'UTC' })} UTC`
        : formatDate(items[0]?.parsed.x),
      label: (context) => context.dataset.isAward
        ? `${context.dataset.label} · ${context.dataset.awardKind === 'mastery' ? 'Mastery' : 'Beaten'}: ${context.raw.gameTitle}`
        : `${context.dataset.label}: ${context.parsed.y.toLocaleString()} ${metricLabel}`,
    };
    const hiddenUsers = new Set(charts.allTime?.data.datasets
      .filter((dataset, index) => !dataset.isAward && !charts.allTime.isDatasetVisible(index))
      .map((dataset) => dataset.userKey) || []);
    const visibleStart = (datasets, isVisible) => {
      const starts = datasets
        .filter((dataset, index) => !dataset.isAward && isVisible(dataset, index) && dataset.data.length)
        .map((dataset) => dataset.data[0].x)
        .filter(Number.isFinite);
      return starts.length ? Math.min(...starts) : Date.parse(data.start);
    };
    const datasets = data.users.map((user, index) => ({
      label: user.ready ? user.username : `${user.username} (pending)`,
      userKey: user.user_key,
      hidden: hiddenUsers.has(user.user_key),
      data: user.points.map((point) => ({ x: Date.parse(point.date), y: point[selectedMetric] })),
      borderColor: palette[index % palette.length],
      backgroundColor: palette[index % palette.length],
      pointRadius: user.points.length === 1 ? 3 : 0,
      pointHoverRadius: 4,
      borderWidth: 2,
      order: 1,
      tension: 0,
      spanGaps: false,
    }));
    for (const user of data.users) {
      if (!user.ready) continue;
      const line = datasets.find((dataset) => dataset.userKey === user.user_key);
      if (!line.data.length) continue;
      for (const [kind, awards, color] of [
        ['mastery', user.masteries || [], '#ffcf21'],
        ['beaten', user.beaten || [], '#f2f2f2'],
      ]) {
        const markers = awards.flatMap((award) => {
          const x = Date.parse(award.date);
          if (!Number.isFinite(x) || x < line.data[0].x || x > line.data.at(-1).x) return [];
          const rightIndex = line.data.findIndex((point) => point.x >= x);
          const right = line.data[rightIndex];
          const left = line.data[Math.max(0, rightIndex - 1)];
          const fraction = right.x === left.x ? 0 : (x - left.x) / (right.x - left.x);
          return [{ x, y: left.y + fraction * (right.y - left.y),
            gameTitle: award.game_title || `Game #${award.game_id}`, gameImage: award.game_image }];
        });
        if (markers.length) datasets.push({
          type: 'scatter', label: user.username, userKey: user.user_key,
          isAward: true, isMastery: kind === 'mastery', awardKind: kind,
          clip: false,
          data: markers, hidden: hiddenUsers.has(user.user_key) || !visibleAwards[kind], order: 0,
          pointStyle: (context) => awardPointStyle(context.raw?.gameImage, color),
          pointRadius: 9, pointHoverRadius: 11, pointHitRadius: 5,
          backgroundColor: color, borderColor: '#202020', borderWidth: 1,
        });
      }
    }
    options.scales.x.min = visibleStart(datasets, (dataset) => !dataset.hidden);
    options.plugins.legend.labels.filter = (item, chartData) => !chartData.datasets[item.datasetIndex].isAward;
    options.plugins.legend.onClick = (_event, item, legend) => {
      const chart = legend.chart;
      const key = chart.data.datasets[item.datasetIndex].userKey;
      const visible = !chart.isDatasetVisible(item.datasetIndex);
      chart.data.datasets.forEach((dataset, index) => {
        if (dataset.userKey === key) chart.setDatasetVisibility(index,
          visible && (!dataset.isAward || visibleAwards[dataset.awardKind]));
      });
      chart.options.scales.x.min = visibleStart(chart.data.datasets, (_dataset, index) => chart.isDatasetVisible(index));
      chart.update();
    };
    replaceChart('allTime', 'all-time-score-chart', {
      type: 'line',
      data: { datasets },
      options,
    });
  }

  async function loadRange(range) {
    range = String(range);
    const generation = ++weeklyGeneration;
    weeklyController?.abort();
    weeklyController = new AbortController();
    rangeButtons.forEach((button) => {
      button.disabled = true;
      const active = button.dataset.chartRange === range;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    errorState.hidden = true;

    try {
      const endpoint = `/api/charts/weekly?weeks=${range}`;
      const response = await fetch(endpoint, {
        method: 'GET',
        headers: { Accept: "application/json" },
        signal: weeklyController.signal,
      });
      if (!response.ok) {
        const hint = response.status >= 500
          ? 'The backend failed to build the chart response. Check Settings → Recent Errors.'
          : 'The chart request was rejected by the server.';
        throw new Error(`HTTP ${response.status} from ${endpoint}. ${hint}`);
      }
      const data = await response.json();
      if (generation !== weeklyGeneration) return;
      const hasHistory = data.weeks.length > 0;
      emptyState.hidden = hasHistory;
      chartGrid.hidden = !hasHistory;
      if (hasHistory) renderCharts(data);

    } catch (error) {
      if (generation === weeklyGeneration && error.name !== "AbortError") {
        errorState.hidden = false;
        errorState.textContent = `Weekly chart could not be loaded. ${error.name}: ${error.message}`;
        chartGrid.hidden = true;
        emptyState.hidden = true;
        console.error(error);
      }
    } finally {
      if (generation === weeklyGeneration) rangeButtons.forEach((button) => { button.disabled = false; });
    }
  }

  async function loadAllTime(refresh = false) {
    const generation = ++allTimeGeneration;
    window.clearTimeout(pollTimer);
    allTimeController?.abort();
    allTimeController = new AbortController();
    const endpoint = `/api/charts/all-time${refresh ? '/refresh' : ''}`;
    try {
      const response = await fetch(endpoint, {
        method: refresh ? 'POST' : 'GET', headers: { Accept: 'application/json' },
        signal: allTimeController.signal,
      });
      if (!response.ok) {
        const hint = response.status === 404
          ? 'The backend serving this page does not have the All Time endpoint. Check that you opened the development instance, not the packaged app.'
          : response.status >= 500
            ? 'The backend failed to build the chart response. Check Settings → Recent Errors.'
            : 'The chart request was rejected by the server.';
        throw new Error(`HTTP ${response.status} from ${endpoint}. ${hint}`);
      }
      const data = await response.json();
      if (generation !== allTimeGeneration) return;
      renderAllTime(data);
      if (data.building) pollTimer = window.setTimeout(() => loadAllTime(), 5000);
    } catch (error) {
      if (generation === allTimeGeneration && error.name !== 'AbortError') {
        allTimeStatus.textContent = `Could not load account history. ${error.name}: ${error.message}`;
        allTimeRefresh.disabled = false;
        allTimeCanvas.hidden = true;
        console.error(error);
      }
    }
  }

  rangeButtons.forEach((button) => {
    button.addEventListener("click", () => loadRange(button.dataset.chartRange));
  });
  metricButtons.forEach((button) => button.addEventListener('click', () => {
    selectedMetric = button.dataset.chartMetric;
    if (allTimeData) renderAllTime(allTimeData);
  }));
  allTimeRefresh.addEventListener('click', () => loadAllTime(true));
  awardToggles.forEach((toggle) => toggle.addEventListener('change', () => {
    visibleAwards[toggle.dataset.chartAwards] = toggle.checked;
    if (allTimeData) renderAllTime(allTimeData);
  }));
  window.addEventListener('pagehide', () => {
    window.clearTimeout(pollTimer);
    weeklyController?.abort();
    allTimeController?.abort();
  });
  loadRange(8);
  loadAllTime();
})();
