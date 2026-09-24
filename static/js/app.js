(() => {
  const refreshSections = Array.from(document.querySelectorAll('[data-dashboard-refresh-section]'));
  if (refreshSections.length === 0) return;

  const REFRESH_INTERVAL_MS = 10 * 1000;
  let refreshInFlight = null;
  let categoryScope = 'weekly';

  const applyCategoryScope = () => {
    document.querySelectorAll('[data-category-scope]').forEach((button) => {
      const active = button.dataset.categoryScope === categoryScope;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    document.querySelectorAll('[data-category-content]').forEach((content) => {
      content.hidden = content.dataset.categoryContent !== categoryScope;
    });
    document.querySelectorAll('[data-category-note]').forEach((note) => {
      note.hidden = note.dataset.categoryNote !== categoryScope;
    });
    document.querySelectorAll('[data-category-period]').forEach((label) => {
      label.textContent = categoryScope === 'weekly' ? 'This week' : 'All time';
    });
  };

  const refreshDashboardActivity = () => {
    if (document.visibilityState !== 'visible') return Promise.resolve();
    if (refreshInFlight) return refreshInFlight;

    refreshInFlight = fetch('/', { cache: 'no-store', headers: { 'X-Dashboard-Refresh': 'activity' } })
      .then((response) => {
        if (!response.ok) throw new Error(`Dashboard refresh failed (${response.status})`);
        return response.text();
      })
      .then((html) => {
        const snapshot = new DOMParser().parseFromString(html, 'text/html');
        document.querySelectorAll('[data-dashboard-refresh-section]').forEach((section) => {
          const key = section.dataset.dashboardRefreshSection;
          const replacement = snapshot.querySelector(`[data-dashboard-refresh-section="${key}"]`);
          if (replacement) section.replaceWith(document.importNode(replacement, true));
        });
        applyCategoryScope();
      })
      .catch((error) => console.info('Could not refresh dashboard activity', error))
      .finally(() => { refreshInFlight = null; });
    return refreshInFlight;
  };

  const scheduleRefresh = () => {
    window.setTimeout(async () => {
      await refreshDashboardActivity();
      scheduleRefresh();
    }, REFRESH_INTERVAL_MS);
  };

  window.addEventListener('pageshow', refreshDashboardActivity);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refreshDashboardActivity();
  });
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-category-scope]');
    if (!button) return;
    categoryScope = button.dataset.categoryScope;
    applyCategoryScope();
  });
  applyCategoryScope();
  refreshDashboardActivity();
  scheduleRefresh();
})();
