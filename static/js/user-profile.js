(() => {
  const panel = document.querySelector("[data-profile-history-chart]");
  if (!panel || typeof Chart === "undefined") return;

  const status = panel.querySelector("[data-profile-chart-status]");
  const canvasWrap = panel.querySelector("[data-profile-chart-canvas]");
  const canvas = panel.querySelector("#profile-all-time-chart");
  const expectedKey = `ulid:${panel.dataset.profileUlid.toLowerCase()}`;
  const expectedUsername = panel.dataset.profileUsername.toLowerCase();
  let chart;
  let retryTimer;

  Chart.defaults.color = "#a4a4a4";
  Chart.defaults.borderColor = "rgba(255, 255, 255, 0.08)";
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';

  const formatDate = (value) => new Date(value).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric", timeZone: "UTC",
  });

  function render(user, end) {
    const points = user.points
      .map((point) => ({ x: Date.parse(point.date), y: point.hardcore_points }))
      .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
    if (!points.length) {
      canvasWrap.hidden = true;
      status.textContent = "No Hardcore scoring achievements have been recorded yet.";
      return;
    }

    canvasWrap.hidden = false;
    chart?.destroy();
    chart = new Chart(canvas, {
      type: "line",
      data: {
        datasets: [{
          label: user.username,
          data: points,
          borderColor: "#ffcf21",
          backgroundColor: "#ffcf21",
          borderWidth: 2,
          pointRadius: points.length === 1 ? 3 : 0,
          pointHoverRadius: 4,
          tension: 0,
          spanGaps: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "nearest", intersect: false },
        layout: { padding: { left: 10, right: 10, top: 12, bottom: 8 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => formatDate(items[0]?.parsed.x),
              label: (context) => `${context.parsed.y.toLocaleString()} Hardcore Points`,
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            min: points[0].x,
            max: Number.isFinite(Date.parse(end)) ? Date.parse(end) : points.at(-1).x,
            ticks: { callback: (value) => formatDate(value) },
            title: { display: true, text: "Achievement history (UTC)" },
          },
          y: {
            min: 0,
            ticks: { precision: 0 },
            title: { display: true, text: "Hardcore Points" },
          },
        },
      },
    });
  }

  async function load() {
    window.clearTimeout(retryTimer);
    try {
      const response = await fetch("/api/charts/all-time", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const user = data.users.find((item) => item.user_key.toLowerCase() === expectedKey)
        || data.users.find((item) => item.username.toLowerCase() === expectedUsername);

      if (!data.configured) {
        status.textContent = "Connect RetroAchievements in Settings to load account history.";
        return;
      }
      if (!user) {
        status.textContent = "Account history is not available for this player.";
        return;
      }
      if (user.points.length) render(user, data.end);

      if (data.building || !user.ready) {
        const progress = data.progress || {};
        status.textContent = data.building
          ? `Building account history: ${progress.completed || 0} / ${progress.total || 0} monthly ranges saved.`
          : (user.error || "Account history is incomplete. Reload to retry.");
        if (data.building) retryTimer = window.setTimeout(load, 5000);
        return;
      }

      if (!user.points.length) {
        status.textContent = "No Hardcore scoring achievements have been recorded yet.";
      } else if (data.needs_refresh) {
        status.textContent = "Showing cached history while the latest totals refresh.";
      } else {
        status.textContent = "Weekly-resolution lifetime history";
      }
    } catch (error) {
      canvasWrap.hidden = true;
      status.textContent = `Could not load account history. ${error.message}`;
    }
  }

  load();
})();
