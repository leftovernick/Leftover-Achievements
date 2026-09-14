(() => {
  const rangeButtons = [...document.querySelectorAll("[data-chart-range]")];
  const chartGrid = document.querySelector("[data-chart-grid]");
  const emptyState = document.querySelector("[data-chart-empty]");
  const errorState = document.querySelector("[data-chart-error]");
  const coverageLabels = document.querySelectorAll("[data-chart-coverage]");
  const charts = {};
  const allTimePanel = document.querySelector('[data-chart-all-time]');
  const allTimeStatus = document.querySelector('[data-all-time-status]');
  const allTimeCanvas = document.querySelector('[data-all-time-canvas]');
  const allTimeRefresh = document.querySelector('[data-all-time-refresh]');
  const metricButtons = [...document.querySelectorAll('[data-chart-metric]')];
  let selectedRange = '8';
  let selectedMetric = 'hardcore_points';
  let allTimeData;
  let pollTimer;
  let requestGeneration = 0;
  let requestController;

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
    rankOptions.scales.y = {
      reverse: true,
      min: 1,
      max: largestRank,
      grid: { color: "rgba(255, 255, 255, 0.065)" },
      ticks: { precision: 0, stepSize: 1 },
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
      status = `${data.ready_users} players · monthly history · totals refreshed ${new Date(Math.min(...asOf)).toLocaleString()}`;
    }
    if (errors.length) status += ` ${errors.join(' ')}`;
    allTimeStatus.textContent = status;
    allTimeRefresh.disabled = data.building || !data.configured || !data.users.length;
    allTimeCanvas.hidden = data.ready_users === 0;
    metricButtons.forEach((button) => {
      const active = button.dataset.chartMetric === selectedMetric;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    if (!data.ready_users) return;
    const options = baseOptions();
    const formatDate = (value) => new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
    options.scales.x.type = 'linear';
    options.scales.x.min = Date.parse(data.start);
    options.scales.x.max = Date.parse(data.end);
    options.scales.x.ticks.callback = (value) => formatDate(value);
    options.scales.x.title = { display: true, text: 'Account history (UTC)' };
    options.scales.y.min = 0;
    options.scales.y.title = { display: true, text: metricLabel };
    options.plugins.tooltip.callbacks = {
      title: (items) => formatDate(items[0]?.parsed.x),
      label: (context) => `${context.dataset.label}: ${context.parsed.y.toLocaleString()} ${metricLabel}`,
    };
    const hiddenUsers = new Set(charts.allTime?.data.datasets
      .filter((dataset, index) => !charts.allTime.isDatasetVisible(index))
      .map((dataset) => dataset.userKey) || []);
    const visibleStart = (datasets, isVisible) => {
      const starts = datasets
        .filter((dataset, index) => isVisible(dataset, index) && dataset.data.length)
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
      pointRadius: 0,
      pointHoverRadius: 4,
      borderWidth: 2,
      tension: 0,
      spanGaps: false,
    }));
    options.scales.x.min = visibleStart(datasets, (dataset) => !dataset.hidden);
    options.plugins.legend.onClick = (_event, item, legend) => {
      const chart = legend.chart;
      chart.setDatasetVisibility(item.datasetIndex, !chart.isDatasetVisible(item.datasetIndex));
      chart.options.scales.x.min = visibleStart(chart.data.datasets, (_dataset, index) => chart.isDatasetVisible(index));
      chart.update();
    };
    replaceChart('allTime', 'all-time-score-chart', {
      type: 'line',
      data: { datasets },
      options,
    });
  }

  async function loadRange(range, refresh = false) {
    range = String(range);
    selectedRange = range;
    const generation = ++requestGeneration;
    window.clearTimeout(pollTimer);
    if (requestController) requestController.abort();
    requestController = new AbortController();
    rangeButtons.forEach((button) => {
      button.disabled = true;
      const active = button.dataset.chartRange === range;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    errorState.hidden = true;

    try {
      const allTime = range === 'all';
      allTimePanel.hidden = !allTime;
      if (allTime) {
        chartGrid.hidden = true;
        emptyState.hidden = true;
      }
      const endpoint = allTime
        ? `/api/charts/all-time${refresh ? '/refresh' : ''}`
        : `/api/charts/weekly?weeks=${range}`;
      const response = await fetch(endpoint, {
        method: refresh && allTime ? 'POST' : 'GET',
        headers: { Accept: "application/json" },
        signal: requestController.signal,
      });
      if (!response.ok) {
        const hint = response.status === 404 && allTime
          ? 'The backend serving this page does not have the All Time endpoint. Check that you opened the development instance, not the packaged app.'
          : response.status >= 500
            ? 'The backend failed to build the chart response. Check Settings → Recent Errors.'
            : 'The chart request was rejected by the server.';
        throw new Error(`HTTP ${response.status} from ${endpoint}. ${hint}`);
      }
      const data = await response.json();
      if (generation !== requestGeneration) return;
      if (allTime) {
        renderAllTime(data);
        if (data.building) pollTimer = window.setTimeout(() => {
          if (selectedRange === 'all') loadRange('all');
        }, 5000);
      } else {
        const hasHistory = data.weeks.length > 0;
        emptyState.hidden = hasHistory;
        chartGrid.hidden = !hasHistory;
        if (hasHistory) renderCharts(data);
      }

    } catch (error) {
      if (generation === requestGeneration && error.name !== "AbortError") {
        errorState.hidden = false;
        errorState.textContent = `${range === 'all' ? 'All Time' : 'Weekly'} chart could not be loaded. ${error.name}: ${error.message}`;
        chartGrid.hidden = true;
        emptyState.hidden = true;
        if (range === 'all') {
          allTimeStatus.textContent = 'Could not load account history. Try Refresh / Retry.';
          allTimeRefresh.disabled = false;
          allTimeCanvas.hidden = true;
        }
        console.error(error);
      }
    } finally {
      if (generation === requestGeneration) rangeButtons.forEach((button) => { button.disabled = false; });
    }
  }

  rangeButtons.forEach((button) => {
    button.addEventListener("click", () => loadRange(button.dataset.chartRange));
  });
  metricButtons.forEach((button) => button.addEventListener('click', () => {
    selectedMetric = button.dataset.chartMetric;
    if (allTimeData) renderAllTime(allTimeData);
  }));
  allTimeRefresh.addEventListener('click', () => loadRange('all', true));
  window.addEventListener('pagehide', () => {
    window.clearTimeout(pollTimer);
    requestController?.abort();
  });
  loadRange(8);
})();
