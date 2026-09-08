(() => {
  const panel = document.querySelector("[data-history-maintenance]");
  if (!panel) return;

  const button = panel.querySelector("[data-history-check]");
  const progress = panel.querySelector("[data-history-progress]");
  const status = panel.querySelector("[data-history-status]");
  const percent = panel.querySelector("[data-history-percent]");
  const current = panel.querySelector("[data-history-current]");
  const fields = {
    checked: panel.querySelector("[data-history-checked]"),
    existing: panel.querySelector("[data-history-existing]"),
    missing: panel.querySelector("[data-history-missing]"),
    fetched: panel.querySelector("[data-history-fetched]"),
    live: panel.querySelector("[data-history-live]"),
    failed: panel.querySelector("[data-history-failed]"),
  };
  let pollTimer = null;

  function isActive(data) {
    return ["queued", "scanning", "running"].includes(data.state);
  }

  function render(data) {
    const active = isActive(data);
    button.disabled = active;
    button.textContent = active ? "Checking History…" : "Check & Fill Missing Data";
    status.textContent = data.message || "Ready to check history.";
    current.textContent = data.current ? `Now fetching: ${data.current}` : "";

    if (["queued", "scanning"].includes(data.state)) {
      progress.removeAttribute("value");
      percent.textContent = "Scanning…";
    } else {
      progress.value = data.percent || 0;
      percent.textContent = `${data.percent || 0}%`;
    }

    fields.checked.textContent = data.total_checks || 0;
    fields.existing.textContent = data.existing || 0;
    fields.missing.textContent = data.missing || 0;
    fields.fetched.textContent = data.fetched || 0;
    fields.live.textContent = data.live_refreshed || 0;
    fields.failed.textContent = data.failed || 0;

    if (active) schedulePoll();
  }

  function schedulePoll() {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(fetchStatus, 800);
  }

  async function fetchStatus() {
    try {
      const response = await fetch("/admin/history-backfill/status", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
      render(await response.json());
    } catch (error) {
      button.disabled = false;
      status.textContent = "Could not read history-check status. Try again.";
      console.error(error);
    }
  }

  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Starting history check…";
    try {
      const response = await fetch("/admin/history-backfill", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`History check failed to start: ${response.status}`);
      render(await response.json());
      schedulePoll();
    } catch (error) {
      button.disabled = false;
      status.textContent = "Could not start the history check. Try again.";
      console.error(error);
    }
  });

  fetchStatus();
})();
