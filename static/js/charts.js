(() => {
  const rangeButtons = [...document.querySelectorAll("[data-chart-range]")];
  const chartGrid = document.querySelector("[data-chart-grid]");
  const emptyState = document.querySelector("[data-chart-empty]");
  const errorState = document.querySelector("[data-chart-error]");
  const coverageLabels = document.querySelectorAll("[data-chart-coverage]");
  const activityPanel = document.querySelector('[data-chart-activity]');
  const activityCoverage = document.querySelector('[data-activity-coverage]');
  const activityTitle = document.querySelector('[data-activity-title]');
  const activityNote = document.querySelector('[data-activity-note]');
  const activityViewButtons = [...document.querySelectorAll('[data-activity-view]')];
  const charts = {};
  const awardLogos = new Map();
  let logoRedrawPending = false;
  function awardPointStyle(point, color) {
    const url = point?.gameImage;
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
    const icon = awardLogos.get(key).icon;
    if (!icon) return 'rect';
    const scale = awardPopScale(point);
    if (scale === 1) return icon;
    const size = Math.max(1, Math.round(22 * scale));
    if (point.popCanvas?.width === size) return point.popCanvas;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    canvas.getContext('2d').drawImage(icon, 0, 0, size, size);
    point.popCanvas = canvas;
    return canvas;
  }
  const allTimeStatus = document.querySelector('[data-all-time-status]');
  const allTimeCanvas = document.querySelector('[data-all-time-canvas]');
  const allTimeRefresh = document.querySelector('[data-all-time-refresh]');
  const allTimeScrollTrack = document.querySelector('[data-all-time-scroll-track]');
  const allTimeCanvasSurface = document.querySelector('[data-all-time-canvas-surface]');
  const timelinePlayButton = document.querySelector('[data-timeline-play]');
  const metricButtons = [...document.querySelectorAll('[data-chart-metric]')];
  const viewButtons = [...document.querySelectorAll('[data-chart-view]')];
  const awardToggles = [...document.querySelectorAll('[data-chart-awards]')];
  const visibleAwards = { mastery: true, beaten: true };
  let selectedMetric = 'hardcore_points';
  let selectedView = 'fit';
  let selectedActivityView = 'weekday';
  let timelineStart;
  let timelineMaxScroll = 0;
  let timelineFrame;
  let playbackTimer;
  let awardPopTimer;
  let playbackActive = false;
  let playbackRevealed = false;
  let playbackHead;
  let playbackStartedAt;
  let playbackStartedFrom;
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

  function renderActivity(data) {
    const monthly = selectedActivityView === 'monthly';
    const activity = (monthly ? data.monthly_activity : data.weekday_activity) || [];
    const coverageField = monthly ? 'eligible_months' : 'eligible_days';
    const periodLabel = monthly ? 'player-months' : 'player-days';
    const hasCoverage = activity.some((period) => period[coverageField] > 0);
    activityPanel.hidden = !hasCoverage;
    if (!hasCoverage) {
      if (charts.activity) charts.activity.destroy();
      delete charts.activity;
      return;
    }
    activityViewButtons.forEach((button) => {
      const active = button.dataset.activityView === selectedActivityView;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const playerLabel = `${data.ready_users} player${data.ready_users === 1 ? '' : 's'}`;
    const periods = activity.reduce((sum, period) => sum + period[coverageField], 0);
    activityTitle.textContent = monthly ? 'Achievements Earned by Month' : 'Achievements Earned by Day of Week';
    activityCoverage.textContent = `${playerLabel} · ${periods.toLocaleString()} ${periodLabel}`;
    activityNote.textContent = monthly
      ? "Average Hardcore achievements per eligible player-month, including months with no unlocks. Months use the server's local calendar."
      : "Average Hardcore achievements per eligible player-day, including days with no unlocks. Weekdays use the server's local calendar.";
    const options = baseOptions();
    options.plugins.legend.display = false;
    options.plugins.tooltip.callbacks = {
      label(context) {
        return `Average: ${context.parsed.y.toFixed(2)} achievements per player`;
      },
      afterLabel(context) {
        const period = activity[context.dataIndex];
        return `${period.achievements_earned.toLocaleString()} achievements across ${period[coverageField].toLocaleString()} ${periodLabel}`;
      },
    };
    options.scales.x.title = { display: true, text: monthly ? 'Month' : 'Day of week' };
    if (monthly) options.scales.x.ticks.maxTicksLimit = 12;
    options.scales.y.title = { display: true, text: `Average achievements per ${monthly ? 'player-month' : 'player-day'}` };
    options.scales.y.ticks = {
      callback: (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 }),
    };
    replaceChart('activity', 'achievement-activity-chart', {
      type: 'bar',
      data: {
        labels: activity.map((period) => monthly ? period.month : period.weekday),
        datasets: [{
          data: activity.map((period) => period.average),
          backgroundColor: 'rgba(255, 207, 33, 0.72)',
          borderColor: '#ffcf21',
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options,
    });
  }

  const TIMELINE_MONTH_MS = 30.4375 * 24 * 60 * 60 * 1000;
  const PLAYBACK_STEP_MS = 33;
  const FIT_PLAYBACK_MONTHS_PER_SECOND = 2.5;
  const TIMELINE_PLAYBACK_MONTHS_PER_SECOND = 0.25;
  const TIMELINE_PLAYHEAD_POSITION = 0.85;
  const AWARD_POP_MS = 650;

  function awardPopScale(point) {
    const started = point?.popStartedAt;
    if (!Number.isFinite(started)) return 1;
    const progress = Math.min(1, Math.max(0, (Date.now() - started) / AWARD_POP_MS));
    if (progress >= 1) return 1;
    if (progress < 0.65) {
      const growing = progress / 0.65;
      return 1.25 * (1 - (1 - growing) ** 3);
    }
    return 1.25 - ((progress - 0.65) / 0.35) * 0.25;
  }

  function awardPopRadius(context) {
    return 9 * awardPopScale(context.raw);
  }

  function setPlaybackButton(playing) {
    timelinePlayButton.textContent = playing ? '❚❚ Pause' : '▶ Play';
    timelinePlayButton.classList.toggle('playing', playing);
    timelinePlayButton.setAttribute('aria-pressed', String(playing));
  }

  function settleAwardPops(frames = Math.ceil(AWARD_POP_MS / PLAYBACK_STEP_MS)) {
    window.clearTimeout(awardPopTimer);
    if (!frames || !charts.allTime) return;
    charts.allTime.update('none');
    awardPopTimer = window.setTimeout(() => settleAwardPops(frames - 1), PLAYBACK_STEP_MS);
  }

  function stopPlayback(restore = false) {
    window.clearTimeout(playbackTimer);
    window.clearTimeout(awardPopTimer);
    playbackTimer = null;
    playbackActive = false;
    setPlaybackButton(false);
    if (restore && charts.allTime) {
      charts.allTime.data.datasets.forEach((dataset) => {
        if (dataset.timelineData) dataset.data = dataset.timelineData;
      });
      playbackRevealed = false;
      playbackHead = undefined;
    } else {
      settleAwardPops();
    }
  }

  function revealLineThrough(points, head) {
    const revealed = points.filter((point) => point.x <= head);
    const rightIndex = points.findIndex((point) => point.x > head);
    if (!revealed.length || rightIndex < 1) return revealed;
    const left = points[rightIndex - 1];
    const right = points[rightIndex];
    if (left.x === head || right.x === left.x) return revealed;
    const fraction = (head - left.x) / (right.x - left.x);
    return [...revealed, { x: head, y: left.y + fraction * (right.y - left.y) }];
  }

  function drawPlaybackFrame(head) {
    const chart = charts.allTime;
    if (!chart || !allTimeData?.start) return;
    const start = visiblePlaybackStart(chart);
    if (!Number.isFinite(start)) return;
    const end = Date.parse(allTimeData.end);
    const fullMaximum = datasetWindowMaximum(
      chart.data.datasets.map((dataset) => ({...dataset, data: dataset.timelineData || dataset.data})),
      (_dataset, index) => chart.isDatasetVisible(index), start, end,
    );
    const previousHead = playbackRevealed && Number.isFinite(playbackHead) ? playbackHead : start - 1;
    playbackHead = Math.max(start, Math.min(head, end));
    chart.data.datasets.forEach((dataset) => {
      if (!dataset.timelineData) return;
      if (dataset.isAward) {
        dataset.data = dataset.timelineData.filter((point) => point.x <= playbackHead);
        dataset.data.forEach((point) => {
          if (point.x > previousHead && point.x <= playbackHead) point.popStartedAt = Date.now();
        });
      } else {
        dataset.data = revealLineThrough(dataset.timelineData, playbackHead);
      }
    });
    playbackRevealed = true;
    if (selectedView === 'fit') {
      chart.options.scales.x.min = start;
      chart.options.scales.x.max = end;
      chart.options.scales.y.max = fullMaximum;
      allTimeCanvas.scrollLeft = 0;
    } else {
      const windowSize = Math.min(TIMELINE_MONTH_MS, Math.max(1, end - start));
      const windowStart = Math.max(
        start,
        Math.min(playbackHead - windowSize * TIMELINE_PLAYHEAD_POSITION, end - windowSize),
      );
      chart.options.scales.x.min = windowStart;
      chart.options.scales.x.max = windowStart + windowSize;
      chart.options.scales.y.max = timelineMaximum(chart, windowStart, windowStart + windowSize);
      if (timelineMaxScroll && end - windowSize > start) {
        allTimeCanvas.scrollLeft = ((windowStart - start) / (end - windowSize - start)) * timelineMaxScroll;
      }
    }
    chart.update('none');
  }

  function playbackTick() {
    if (!playbackActive) return;
    const elapsed = Date.now() - playbackStartedAt;
    const speed = selectedView === 'fit'
      ? FIT_PLAYBACK_MONTHS_PER_SECOND
      : TIMELINE_PLAYBACK_MONTHS_PER_SECOND;
    const head = playbackStartedFrom + elapsed * (TIMELINE_MONTH_MS / 1000) * speed;
    const end = Date.parse(allTimeData.end);
    drawPlaybackFrame(Math.min(head, end));
    if (head >= end) {
      stopPlayback(false);
      return;
    }
    playbackTimer = window.setTimeout(playbackTick, PLAYBACK_STEP_MS);
  }

  function visibleAllTimeStart(chart) {
    const starts = chart.data.datasets
      .filter((dataset, index) => !dataset.isAward && chart.isDatasetVisible(index) && dataset.data.length)
      .map((dataset) => dataset.data[0].x)
      .filter(Number.isFinite);
    return starts.length ? Math.min(...starts) : Date.parse(allTimeData.start);
  }

  function visiblePlaybackStart(chart) {
    const starts = chart.data.datasets
      .filter((dataset, index) => !dataset.isAward && chart.isDatasetVisible(index)
        && (dataset.timelineData || dataset.data).length)
      .map((dataset) => (dataset.timelineData || dataset.data)[0].x)
      .filter(Number.isFinite);
    return starts.length ? Math.min(...starts) : NaN;
  }

  function datasetWindowMaximum(datasets, isVisible, start, end) {
    const values = [];
    datasets.forEach((dataset, index) => {
      if (dataset.isAward || !isVisible(dataset, index) || !dataset.data.length) return;
      const points = dataset.data;
      points.forEach((point) => {
        if (point.x >= start && point.x <= end) values.push(point.y);
      });
      for (const boundary of [start, end]) {
        const rightIndex = points.findIndex((point) => point.x >= boundary);
        if (rightIndex <= 0) continue;
        const left = points[rightIndex - 1];
        const right = points[rightIndex];
        if (boundary > right.x) continue;
        const fraction = (boundary - left.x) / (right.x - left.x);
        values.push(left.y + fraction * (right.y - left.y));
      }
    });
    return Math.max(1, ...values) * 1.08;
  }

  function timelineMaximum(chart, start, end) {
    return datasetWindowMaximum(
      chart.data.datasets,
      (_dataset, index) => chart.isDatasetVisible(index),
      start,
      end,
    );
  }

  function applyAllTimeView(chart, reset = false) {
    if (!chart || !allTimeData?.start) return;
    const start = visibleAllTimeStart(chart);
    const end = Date.parse(allTimeData.end);
    if (selectedView === 'fit') {
      allTimeCanvas.classList.remove('timeline-view');
      allTimeScrollTrack.style.width = '100%';
      allTimeCanvasSurface.style.width = '100%';
      allTimeCanvas.scrollLeft = 0;
      chart.options.scales.x.min = start;
      chart.options.scales.x.max = end;
      chart.options.scales.y.max = timelineMaximum(chart, start, end);
      return;
    }

    allTimeCanvas.classList.add('timeline-view');
    const viewportWidth = allTimeCanvas.clientWidth || 800;
    const windowSize = Math.min(TIMELINE_MONTH_MS, Math.max(1, end - start));
    const latestStart = Math.max(start, end - windowSize);
    if (reset || !Number.isFinite(timelineStart)) timelineStart = start;
    timelineStart = Math.max(start, Math.min(timelineStart, latestStart));
    const monthCount = Math.max(1, (end - start) / TIMELINE_MONTH_MS);
    timelineMaxScroll = Math.max(0, (monthCount - 1) * viewportWidth);
    allTimeScrollTrack.style.width = `${viewportWidth + timelineMaxScroll}px`;
    allTimeCanvasSurface.style.width = `${viewportWidth}px`;
    allTimeCanvas.scrollLeft = latestStart === start
      ? 0
      : ((timelineStart - start) / (latestStart - start)) * timelineMaxScroll;
    chart.options.scales.x.min = timelineStart;
    chart.options.scales.x.max = timelineStart + windowSize;
    chart.options.scales.y.max = timelineMaximum(chart, timelineStart, timelineStart + windowSize);
  }

  function renderAllTime(data) {
    allTimeData = data;
    renderActivity(data);
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
          pointStyle: (context) => awardPointStyle(context.raw, color),
          pointRadius: awardPopRadius, pointHoverRadius: 11, pointHitRadius: 5,
          backgroundColor: color, borderColor: '#202020', borderWidth: 1,
        });
      }
    }
    datasets.forEach((dataset) => { dataset.timelineData = dataset.data; });
    const initialStart = visibleStart(datasets, (dataset) => !dataset.hidden);
    const initialEnd = Date.parse(data.end);
    options.scales.x.min = initialStart;
    options.scales.y.max = datasetWindowMaximum(datasets, (dataset) => !dataset.hidden, initialStart, initialEnd);
    if (selectedView === 'timeline') {
      const windowSize = Math.min(TIMELINE_MONTH_MS, Math.max(1, initialEnd - initialStart));
      const latestStart = Math.max(initialStart, initialEnd - windowSize);
      if (!Number.isFinite(timelineStart)) timelineStart = initialStart;
      timelineStart = Math.max(initialStart, Math.min(timelineStart, latestStart));
      options.scales.x.min = timelineStart;
      options.scales.x.max = timelineStart + windowSize;
      options.scales.y.max = datasetWindowMaximum(
        datasets, (dataset) => !dataset.hidden, timelineStart, timelineStart + windowSize,
      );
    }
    options.plugins.legend.labels.filter = (item, chartData) => !chartData.datasets[item.datasetIndex].isAward;
    options.plugins.legend.onClick = (_event, item, legend) => {
      const chart = legend.chart;
      stopPlayback(true);
      const key = chart.data.datasets[item.datasetIndex].userKey;
      const visible = !chart.isDatasetVisible(item.datasetIndex);
      chart.data.datasets.forEach((dataset, index) => {
        if (dataset.userKey === key) chart.setDatasetVisibility(index,
          visible && (!dataset.isAward || visibleAwards[dataset.awardKind]));
      });
      applyAllTimeView(chart, true);
      chart.update();
    };
    replaceChart('allTime', 'all-time-score-chart', {
      type: 'line',
      data: { datasets },
      options,
    });
    applyAllTimeView(charts.allTime);
    charts.allTime.update('none');
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
  activityViewButtons.forEach((button) => button.addEventListener('click', () => {
    selectedActivityView = button.dataset.activityView;
    if (allTimeData) renderActivity(allTimeData);
  }));
  metricButtons.forEach((button) => button.addEventListener('click', () => {
    stopPlayback(true);
    selectedMetric = button.dataset.chartMetric;
    if (allTimeData) renderAllTime(allTimeData);
  }));
  viewButtons.forEach((button) => button.addEventListener('click', () => {
    stopPlayback(true);
    selectedView = button.dataset.chartView;
    timelineStart = undefined;
    viewButtons.forEach((candidate) => {
      const active = candidate === button;
      candidate.classList.toggle('active', active);
      candidate.setAttribute('aria-pressed', String(active));
    });
    // Recreate the chart when changing scale modes. Chart.js retains resolved
    // scale bounds on some browsers when an existing scale is mutated in place.
    if (allTimeData) renderAllTime(allTimeData);
  }));
  timelinePlayButton.addEventListener('click', () => {
    if (playbackActive) {
      stopPlayback(false);
      return;
    }
    if (!charts.allTime || !allTimeData?.start) return;
    const start = visiblePlaybackStart(charts.allTime);
    if (!Number.isFinite(start)) return;
    const end = Date.parse(allTimeData.end);
    if (!playbackRevealed || !Number.isFinite(playbackHead) || playbackHead >= end) playbackHead = start;
    playbackActive = true;
    playbackStartedAt = Date.now();
    playbackStartedFrom = playbackHead;
    setPlaybackButton(true);
    drawPlaybackFrame(playbackHead);
    playbackTimer = window.setTimeout(playbackTick, PLAYBACK_STEP_MS);
  });
  allTimeCanvas.addEventListener('scroll', () => {
    if (selectedView !== 'timeline' || timelineFrame) return;
    timelineFrame = window.requestAnimationFrame(() => {
      timelineFrame = null;
      if (playbackActive) return;
      const chart = charts.allTime;
      if (!chart || !timelineMaxScroll) return;
      if (playbackRevealed) {
        chart.data.datasets.forEach((dataset) => {
          if (dataset.timelineData) dataset.data = dataset.timelineData;
        });
        playbackRevealed = false;
        playbackHead = undefined;
      }
      const start = visibleAllTimeStart(chart);
      const end = Date.parse(allTimeData.end);
      const windowSize = Math.min(TIMELINE_MONTH_MS, Math.max(1, end - start));
      timelineStart = start + (allTimeCanvas.scrollLeft / timelineMaxScroll) * Math.max(0, end - windowSize - start);
      chart.options.scales.x.min = timelineStart;
      chart.options.scales.x.max = timelineStart + windowSize;
      chart.options.scales.y.max = timelineMaximum(chart, timelineStart, timelineStart + windowSize);
      chart.update('none');
    });
  });
  allTimeRefresh.addEventListener('click', () => loadAllTime(true));
  awardToggles.forEach((toggle) => toggle.addEventListener('change', () => {
    stopPlayback(true);
    visibleAwards[toggle.dataset.chartAwards] = toggle.checked;
    if (allTimeData) renderAllTime(allTimeData);
  }));
  window.addEventListener('pagehide', () => {
    window.clearTimeout(pollTimer);
    stopPlayback(true);
    weeklyController?.abort();
    allTimeController?.abort();
  });
  window.addEventListener('resize', () => {
    if (selectedView === 'timeline' && charts.allTime) {
      applyAllTimeView(charts.allTime);
      charts.allTime.update('none');
    }
  });
  loadRange(8);
  loadAllTime();
})();
