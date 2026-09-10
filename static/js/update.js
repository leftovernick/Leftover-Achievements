(() => {
  const root = document.querySelector('[data-update-controls]');
  if (!root) return;

  const summary = root.querySelector('[data-update-summary]');
  const current = root.querySelector('[data-update-current]');
  const latest = root.querySelector('[data-update-latest]');
  const published = root.querySelector('[data-update-published]');
  const checked = root.querySelector('[data-update-checked]');
  const error = root.querySelector('[data-update-error]');
  const installNote = root.querySelector('[data-update-install-note]');
  const releaseDetails = root.querySelector('[data-update-release-details]');
  const releaseName = root.querySelector('[data-update-release-name]');
  const releaseNotes = root.querySelector('[data-update-release-notes]');
  const releaseLink = root.querySelector('[data-update-release-link]');
  const checkButton = root.querySelector('[data-update-check]');
  const installButton = root.querySelector('[data-update-install]');
  let updateRunning = false;

  const dateLabel = (value, includeTime = false) => value
    ? new Intl.DateTimeFormat(undefined, includeTime
      ? { dateStyle: 'medium', timeStyle: 'short' }
      : { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value))
    : 'Unavailable';

  const phaseLabel = (phase) => ({
    downloading: 'Downloading package…',
    validating: 'Validating package…',
    preparing: 'Preparing update…',
    installing: 'Installing dependencies…',
    applying: 'Applying system changes…',
    restarting: 'Restarting service…',
  }[phase] || 'Updating…');

  const render = (state) => {
    const wasRunning = updateRunning;
    updateRunning = Boolean(state.installing);
    current.textContent = state.installed_version || 'Development build';
    latest.textContent = state.latest_version || 'No stable release';
    published.textContent = dateLabel(state.latest_release_published_at);
    checked.textContent = state.last_checked_at ? dateLabel(state.last_checked_at, true) : 'Not yet checked';
    if (state.installing) summary.textContent = phaseLabel(state.install_phase);
    else if (state.install_phase === 'failed') summary.textContent = 'Update failed';
    else if (state.error) summary.textContent = 'Unable to check';
    else if (state.update_available && state.install_supported) summary.textContent = 'Update available';
    else if (state.update_available) summary.textContent = 'Update available · Manual install';
    else if (state.last_checked_at && state.latest_version) summary.textContent = 'Up to date';
    else if (state.last_checked_at) summary.textContent = 'No stable release';
    else summary.textContent = 'Checking…';

    const hasReleaseDetails = Boolean(state.latest_release_name || state.latest_release_notes || state.latest_release_url);
    releaseDetails.hidden = !hasReleaseDetails;
    releaseName.textContent = state.latest_release_name || state.latest_version || '';
    releaseNotes.hidden = !state.latest_release_notes;
    releaseNotes.textContent = state.latest_release_notes || '';
    const releaseLinkUrl = state.latest_release_asset_url || state.latest_release_url;
    releaseLink.hidden = !releaseLinkUrl;
    releaseLink.textContent = state.latest_release_asset_url ? 'Download packaged release' : 'View release on GitHub';
    if (releaseLinkUrl) releaseLink.href = releaseLinkUrl;
    else releaseLink.removeAttribute('href');

    error.hidden = !state.error;
    error.textContent = state.error || '';
    installNote.hidden = !state.update_available || state.install_supported;
    installNote.textContent = state.install_unavailable_reason || '';
    checkButton.disabled = state.checking || state.installing;
    checkButton.textContent = state.checking ? 'Checking…' : 'Check for Updates';
    installButton.hidden = (!state.update_available || !state.install_supported) && !state.installing;
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
      error.textContent = updateRunning ? 'The service is restarting. Reconnecting…' : requestError.message;
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
