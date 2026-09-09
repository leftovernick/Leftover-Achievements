(() => {
  const root = document.querySelector('[data-update-controls]');
  if (!root) return;

  const summary = root.querySelector('[data-update-summary]');
  const current = root.querySelector('[data-update-current]');
  const latest = root.querySelector('[data-update-latest]');
  const checked = root.querySelector('[data-update-checked]');
  const error = root.querySelector('[data-update-error]');
  const checkButton = root.querySelector('[data-update-check]');
  const installButton = root.querySelector('[data-update-install]');
  let updateRunning = false;

  const commitLabel = (commit) => {
    if (!commit) return 'Unavailable';
    const date = commit.committed_at
      ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(commit.committed_at))
      : '';
    return [commit.short_commit, date, commit.message].filter(Boolean).join(' · ');
  };

  const checkedLabel = (value) => value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
    : 'Not yet checked';

  const phaseLabel = (phase) => ({
    preparing: 'Preparing update…',
    installing: 'Installing dependencies…',
    restarting: 'Restarting service…',
  }[phase] || 'Updating…');

  const render = (state) => {
    const wasRunning = updateRunning;
    updateRunning = Boolean(state.installing);
    current.textContent = commitLabel(state.current);
    latest.textContent = commitLabel(state.latest);
    checked.textContent = checkedLabel(state.last_checked_at);
    if (state.installing) summary.textContent = phaseLabel(state.install_phase);
    else if (state.install_phase === 'failed') summary.textContent = 'Update failed';
    else if (state.error) summary.textContent = 'Unable to check';
    else if (state.update_available) summary.textContent = 'Update available';
    else if (state.last_checked_at) summary.textContent = 'Up to date';
    else summary.textContent = 'Checking…';

    error.hidden = !state.error;
    error.textContent = state.error || '';
    checkButton.disabled = state.checking || state.installing;
    checkButton.textContent = state.checking ? 'Checking…' : 'Check for Updates';
    installButton.hidden = !state.update_available && !state.installing;
    installButton.disabled = state.installing;
    installButton.textContent = state.installing ? phaseLabel(state.install_phase) : 'Update Now';
    if (wasRunning && !state.installing && !state.error) window.setTimeout(() => window.location.reload(), 700);
  };

  const request = async (url, options = {}) => {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    render(payload);
    return payload;
  };

  const poll = async () => {
    try {
      await request('/api/update/status');
    } catch (requestError) {
      summary.textContent = updateRunning ? 'Reconnecting…' : 'Unable to check';
      error.hidden = false;
      error.textContent = updateRunning ? 'The service is restarting. This page will reconnect automatically.' : requestError.message;
    }
    window.setTimeout(poll, updateRunning ? 2000 : 60000);
  };

  checkButton.addEventListener('click', async () => {
    checkButton.disabled = true;
    try { await request('/api/update/check', { method: 'POST' }); }
    catch (requestError) { error.hidden = false; error.textContent = requestError.message; checkButton.disabled = false; }
  });

  installButton.addEventListener('click', async () => {
    if (updateRunning || !window.confirm('Install this update and restart LeftoverAchievements?')) return;
    installButton.disabled = true;
    try { await request('/api/update/install', { method: 'POST' }); }
    catch (requestError) { error.hidden = false; error.textContent = requestError.message; installButton.disabled = false; }
  });

  try { render(JSON.parse(root.dataset.initialUpdate || '{}')); }
  catch (error) { console.info('Initial update status unavailable', error); }
  poll();
})();
