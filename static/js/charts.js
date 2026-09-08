(() => {
  const rangeButtons = [...document.querySelectorAll("[data-chart-range]")];
  const chartGrid = document.querySelector("[data-chart-grid]");
  const emptyState = document.querySelector("[data-chart-empty]");
  const errorState = document.querySelector("[data-chart-error]");
  const coverageLabels = document.querySelectorAll("[data-chart-coverage]");
  const charts = {};
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

  async function loadRange(range) {
    if (requestController) requestController.abort();
    requestController = new AbortController();
    rangeButtons.forEach((button) => { button.disabled = true; });
    errorState.hidden = true;

    try {
      const response = await fetch(`/api/charts/weekly?weeks=${range}`, {
        headers: { Accept: "application/json" },
        signal: requestController.signal,
      });
      if (!response.ok) throw new Error(`Chart request failed: ${response.status}`);
      const data = await response.json();
      const hasHistory = data.weeks.length > 0;
      emptyState.hidden = hasHistory;
      chartGrid.hidden = !hasHistory;
      if (hasHistory) renderCharts(data);

      rangeButtons.forEach((button) => {
        const active = Number(button.dataset.chartRange) === data.range_weeks;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    } catch (error) {
      if (error.name !== "AbortError") {
        errorState.hidden = false;
        chartGrid.hidden = true;
        emptyState.hidden = true;
        console.error(error);
      }
    } finally {
      rangeButtons.forEach((button) => { button.disabled = false; });
    }
  }

  rangeButtons.forEach((button) => {
    button.addEventListener("click", () => loadRange(Number(button.dataset.chartRange)));
  });
  loadRange(8);
})();
