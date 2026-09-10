(() => {
  const root = document.querySelector('[data-display-rotation]');
  if (!root) return;

  const carouselTrack = root.querySelector('[data-carousel-track]');
  let slides = Array.from(root.querySelectorAll('[data-slide]'));
  if (!carouselTrack || slides.length === 0) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const carouselTransitionDuration = reducedMotion ? 1 : 650;
  const GESTURE = Object.freeze({
    edgeSize: 64,
    horizontalDistance: 72,
    verticalDistance: 64,
    horizontalDominance: 1.2,
    verticalDominance: 1.15,
  });
  const ROTATION_SPEEDS = Object.freeze({ slow: 1.5, normal: 1, fast: 0.5 });
  const STORAGE_KEYS = Object.freeze({
    muted: 'leftover-display-muted',
    speed: 'leftover-display-rotation-speed',
  });

  const appendCarouselClones = () => {
    const firstSlideClone = slides[0].cloneNode(true);
    firstSlideClone.classList.remove('is-active');
    firstSlideClone.dataset.carouselClone = 'true';
    firstSlideClone.setAttribute('aria-hidden', 'true');
    carouselTrack.appendChild(firstSlideClone);
    const lastSlideClone = slides[slides.length - 1].cloneNode(true);
    lastSlideClone.classList.remove('is-active');
    lastSlideClone.dataset.carouselClone = 'true';
    lastSlideClone.setAttribute('aria-hidden', 'true');
    carouselTrack.prepend(lastSlideClone);
  };
  appendCarouselClones();

  const notification = document.querySelector('[data-achievement-notification]');
  const dashboardPanel = document.querySelector('[data-dashboard-panel]');
  const dashboardQr = document.querySelector('[data-dashboard-qr]');
  const dashboardQrError = document.querySelector('[data-dashboard-qr-error]');
  const settingsPanel = document.querySelector('[data-settings-panel]');
  const audioState = document.querySelector('[data-audio-state]');
  const rotationState = document.querySelector('[data-rotation-state]');
  const updateIndicator = document.querySelector('[data-update-indicator]');
  const updateState = document.querySelector('[data-display-update-state]');
  const updateDetail = document.querySelector('[data-display-update-detail]');
  const updateCheckButton = document.querySelector('[data-display-update-check]');
  const updateInstallButton = document.querySelector('[data-display-update-install]');
  const updateOverlay = document.querySelector('[data-update-overlay]');
  const updateOverlayTitle = document.querySelector('[data-update-overlay-title]');
  const updateOverlayDetail = document.querySelector('[data-update-overlay-detail]');
  const audioEnabled = root.dataset.audioEnabled === 'true';
  const autoReloadEnabled = root.dataset.autoReload === 'true';
  let customAudioSources = {};
  try {
    customAudioSources = JSON.parse(root.dataset.audioSources || '{}');
  } catch (error) {
    console.info('Custom audio settings unavailable', error);
  }
  const notificationQueue = [];
  const audioSourcesByType = {
    achievement: [
      '/static/audio/achievement-unlocked.mp3',
      '/static/audio/achievement-unlocked.wav',
      '/static/audio/achievement-unlocked.ogg',
    ],
    mastery: [
      '/static/audio/game-mastered.mp3',
      '/static/audio/mastery.wav',
      '/static/audio/mastery.ogg',
    ],
    beaten: [
      '/static/audio/game-beaten.mp3',
      '/static/audio/game-beaten.wav',
      '/static/audio/game-beaten.ogg',
    ],
  };
  let notificationActive = false;
  let currentIndex = Math.max(0, slides.findIndex((slide) => slide.classList.contains('is-active')));
  let timerId = null;
  let transitionTimerId = null;
  let scrollAnimationFrameId = null;
  let slideStartedAt = 0;
  let activeDuration = 0;
  let remainingDuration = 0;
  let scrollCycleElapsed = 0;
  let scrollLastFrameAt = 0;
  let rotationPaused = false;
  let carouselTransitioning = false;
  let carouselPosition = currentIndex + 1;
  let openPanel = null;
  const pauseReasons = new Set();
  let audioMuted = false;
  let rotationSpeed = 'normal';
  let updateRunning = false;

  dashboardQr?.addEventListener('error', () => {
    dashboardQr.hidden = true;
    if (dashboardQrError) dashboardQrError.classList.add('is-visible');
  });

  try {
    audioMuted = window.localStorage.getItem(STORAGE_KEYS.muted) === 'true';
    const savedSpeed = window.localStorage.getItem(STORAGE_KEYS.speed);
    if (savedSpeed && Object.prototype.hasOwnProperty.call(ROTATION_SPEEDS, savedSpeed)) rotationSpeed = savedSpeed;
  } catch (error) {
    console.info('Display preferences are unavailable', error);
  }

  const setText = (selector, value) => {
    const element = notification?.querySelector(selector);
    if (element) element.textContent = value || '';
  };

  const setImage = (selector, src, alt) => {
    const element = notification?.querySelector(selector);
    if (!element) return;
    if (src) {
      element.src = src;
      element.alt = alt || '';
      element.hidden = false;
    } else {
      element.removeAttribute('src');
      element.alt = '';
      element.hidden = true;
    }
  };

  const setNotificationProgress = (startPercentage, endPercentage) => {
    const start = Number(startPercentage);
    const end = Number(endPercentage);
    const hasProgress = startPercentage !== null
      && startPercentage !== undefined
      && endPercentage !== null
      && endPercentage !== undefined
      && Number.isFinite(start)
      && Number.isFinite(end);
    notification?.classList.toggle('has-progress', hasProgress);
    if (!notification || !hasProgress) return;

    notification.style.setProperty('--notification-progress-start', Math.min(1, Math.max(0, start / 100)));
    notification.style.setProperty('--notification-progress-end', Math.min(1, Math.max(0, end / 100)));
  };

  const playGeneratedAchievementSound = () => {
    if (audioMuted) return;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) return;

      const context = new AudioContext();
      const startSound = () => {
        const gain = context.createGain();
        gain.gain.setValueAtTime(0.0001, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.16, context.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 1.1);
        gain.connect(context.destination);

        [523.25, 659.25, 783.99].forEach((frequency, index) => {
          const oscillator = context.createOscillator();
          oscillator.type = 'triangle';
          oscillator.frequency.setValueAtTime(frequency, context.currentTime + index * 0.12);
          oscillator.connect(gain);
          oscillator.start(context.currentTime + index * 0.12);
          oscillator.stop(context.currentTime + 0.85 + index * 0.08);
        });

        window.setTimeout(() => context.close(), 1400);
      };

      if (context.state === 'suspended') {
        context.resume().then(startSound).catch(() => context.close());
      } else {
        startSound();
      }
    } catch (error) {
      console.info('Generated achievement sound unavailable', error);
    }
  };

  const enableDisplayAudio = async () => {
    if (!audioEnabled || audioMuted) return;

    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        const context = new AudioContext();
        await context.resume();
        await context.close();
      }

      const bootstrapSource = customAudioSources.achievement || audioSourcesByType.achievement[0];
      const bootstrapAudio = new Audio(bootstrapSource);
      bootstrapAudio.muted = true;
      await bootstrapAudio.play();
      bootstrapAudio.pause();
      bootstrapAudio.currentTime = 0;

    } catch (error) {
      console.info('Display audio still needs browser permission', error);
    }
  };

  const playAchievementSound = async (type = 'achievement', event = {}) => {
    if (!audioEnabled || audioMuted) return;

    if (event.audio_sources && typeof event.audio_sources === 'object') {
      customAudioSources = event.audio_sources;
    }
    const defaultSources = audioSourcesByType[type] || audioSourcesByType.achievement;
    const customSource = customAudioSources[type];
    const audioSources = customSource ? [customSource, ...defaultSources] : defaultSources;
    for (const source of audioSources) {
      try {
        const audio = new Audio(source);
        audio.volume = 0.85;
        await audio.play();
        return;
      } catch (error) {
        // Try the next source, then fall back to a generated chime.
      }
    }
    playGeneratedAchievementSound();
  };

  const clearRotationTimers = () => {
    window.clearTimeout(timerId);
    timerId = null;
    if (scrollAnimationFrameId !== null) {
      window.cancelAnimationFrame(scrollAnimationFrameId);
      scrollAnimationFrameId = null;
    }
  };

  const startLeaderboardScroll = (slide, preservePosition = false) => {
    const viewport = slide.querySelector('[data-scroll-list]');
    const list = viewport?.querySelector('.display-ranking-list, .display-activity-list');
    if (!viewport || !list) return;

    if (!preservePosition) {
      scrollCycleElapsed = 0;
      list.style.transform = 'translate3d(0, 0, 0)';
    }
    if (reducedMotion) return;

    const maxScroll = Math.max(0, list.scrollHeight - viewport.clientHeight);
    if (maxScroll === 0) return;

    const topHold = 4500;
    const bottomHold = 4500;
    const resetHold = 700;
    const pixelsPerSecond = 46;
    const scrollDuration = (maxScroll / pixelsPerSecond) * 1000;
    const cycleDuration = topHold + scrollDuration + bottomHold + resetHold;
    scrollLastFrameAt = window.performance.now();

    const animate = (now) => {
      scrollCycleElapsed = (scrollCycleElapsed + (now - scrollLastFrameAt)) % cycleDuration;
      scrollLastFrameAt = now;

      let offset = 0;
      if (scrollCycleElapsed <= topHold) {
        offset = 0;
      } else if (scrollCycleElapsed <= topHold + scrollDuration) {
        offset = ((scrollCycleElapsed - topHold) / scrollDuration) * maxScroll;
      } else if (scrollCycleElapsed <= topHold + scrollDuration + bottomHold) {
        offset = maxScroll;
      }

      list.style.transform = `translate3d(0, -${offset}px, 0)`;
      if (!rotationPaused) scrollAnimationFrameId = window.requestAnimationFrame(animate);
    };

    scrollAnimationFrameId = window.requestAnimationFrame(animate);
  };

  const setCarouselPosition = (position, animate = true) => {
    carouselPosition = position;
    carouselTrack.classList.toggle('is-jumping', !animate);
    carouselTrack.style.transform = `translate3d(-${position * 100}%, 0, 0)`;
    if (!animate) {
      void carouselTrack.offsetWidth;
      carouselTrack.classList.remove('is-jumping');
    }
  };

  const slideDuration = (slide = slides[currentIndex]) => {
    const normalDuration = Number.parseInt(slide.dataset.duration || '60000', 10);
    return Math.round(normalDuration * ROTATION_SPEEDS[rotationSpeed]);
  };

  const scheduleNextSlide = (durationOverride = null, preserveScroll = false) => {
    clearRotationTimers();

    rotationPaused = false;
    const activeSlide = slides[currentIndex];
    const duration = durationOverride ?? slideDuration(activeSlide);
    activeDuration = duration;
    remainingDuration = duration;
    slideStartedAt = window.performance.now();
    startLeaderboardScroll(activeSlide, preserveScroll);
    timerId = window.setTimeout(() => activateSlide(currentIndex + 1), duration);
  };

  const finishCarouselTransition = () => {
    window.clearTimeout(transitionTimerId);
    transitionTimerId = null;
    if (!carouselTransitioning) return;

    carouselTransitioning = false;
    if (carouselPosition === slides.length + 1) setCarouselPosition(1, false);
    if (carouselPosition === 0) setCarouselPosition(slides.length, false);
  };

  const activateSlide = (nextIndex) => {
    if (carouselTransitioning) return;
    clearRotationTimers();
    const previousIndex = currentIndex;
    const wrappingForward = nextIndex >= slides.length;
    const wrappingBackward = nextIndex < 0;
    currentIndex = (nextIndex + slides.length) % slides.length;
    slides[previousIndex].classList.remove('is-active');
    slides[currentIndex].classList.add('is-active');

    carouselTransitioning = true;
    setCarouselPosition(wrappingForward ? slides.length + 1 : (wrappingBackward ? 0 : currentIndex + 1));
    activeDuration = slideDuration();
    remainingDuration = activeDuration;
    slideStartedAt = window.performance.now();
    scrollCycleElapsed = 0;
    const list = slides[currentIndex].querySelector('.display-ranking-list, .display-activity-list');
    if (list) list.style.transform = 'translate3d(0, 0, 0)';
    if (pauseReasons.size === 0) {
      scheduleNextSlide();
    } else {
      rotationPaused = true;
    }
    transitionTimerId = window.setTimeout(finishCarouselTransition, carouselTransitionDuration + 50);
  };

  const pauseRotation = (reason) => {
    if (pauseReasons.has(reason)) return;
    const wasRunning = pauseReasons.size === 0;
    pauseReasons.add(reason);
    if (!wasRunning) return;
    rotationPaused = true;

    if (carouselTransitioning) {
      finishCarouselTransition();
    }

    const elapsed = window.performance.now() - slideStartedAt;
    remainingDuration = Math.max(500, activeDuration - elapsed);
    clearRotationTimers();
  };

  const resumeRotation = (reason) => {
    pauseReasons.delete(reason);
    if (pauseReasons.size > 0 || !rotationPaused) return;
    scheduleNextSlide(remainingDuration, true);
  };

  const renderAchievementNotification = (event) => {
    notification.classList.remove('is-mastery');
    notification.classList.remove('is-beaten');
    setText('[data-achievement-heading]', 'Achievement Unlocked');
    setText('[data-achievement-mode]', 'Hardcore');
    setImage('[data-achievement-user-avatar]', event.avatar, `${event.username} avatar`);
    setImage('[data-achievement-badge]', event.achievement_badge, `${event.achievement_title} badge`);
    setText('[data-achievement-username]', event.username);
    setText('[data-achievement-title]', event.achievement_title);
    setText('[data-achievement-description]', event.achievement_description);
    setText('[data-achievement-game]', event.game_title);
    setText('[data-achievement-points]', event.points_display);
    setText('[data-achievement-retro-points]', event.retro_points ? `(${event.retro_points_display})` : '');
    setNotificationProgress(event.completion_before_percentage, event.completion_after_percentage);
  };

  const renderMasteryNotification = (event) => {
    notification.classList.remove('is-beaten');
    notification.classList.add('is-mastery');
    setText('[data-achievement-heading]', 'MASTERED');
    setText('[data-achievement-mode]', 'Mastery');
    setImage('[data-achievement-user-avatar]', event.avatar, `${event.username} avatar`);
    setImage('[data-achievement-badge]', event.game_image, `${event.game_title} image`);
    setText('[data-achievement-username]', event.username);
    setText('[data-achievement-title]', event.game_title);
    setText(
      '[data-achievement-description]',
      `100% · ${event.hardcore_achievements} / ${event.total_achievements} Hardcore achievements completed`
    );
    setText('[data-achievement-game]', 'Hardcore Mastery');
    setText('[data-achievement-points]', `${event.hardcore_points_display} / ${event.total_points_display}`);
    setText('[data-achievement-retro-points]', '');
    setNotificationProgress(0, 100);
  };

  const renderBeatenNotification = (event) => {
    notification.classList.remove('is-mastery');
    notification.classList.add('is-beaten');
    setText('[data-achievement-heading]', 'Game Beaten');
    setText('[data-achievement-mode]', 'Hardcore');
    setImage('[data-achievement-user-avatar]', event.avatar, `${event.username} avatar`);
    setImage('[data-achievement-badge]', event.game_image, `${event.game_title} image`);
    setText('[data-achievement-username]', event.username);
    setText('[data-achievement-title]', event.game_title);
    setText(
      '[data-achievement-description]',
      event.total_achievements
        ? `${event.hardcore_achievements} / ${event.total_achievements} Hardcore achievements earned`
        : 'Canonical Hardcore game completion achieved'
    );
    setText('[data-achievement-game]', 'Hardcore Game Beaten');
    setText(
      '[data-achievement-points]',
      event.total_points ? `${event.hardcore_points_display} / ${event.total_points_display}` : ''
    );
    setText('[data-achievement-retro-points]', '');
    setNotificationProgress(
      0,
      event.total_achievements ? (event.hardcore_achievements / event.total_achievements) * 100 : null
    );
  };

  const showNextNotification = () => {
    if (!notification || notificationActive || notificationQueue.length === 0) return;

    const event = notificationQueue.shift();
    const eventType = event.type || 'achievement';
    notificationActive = true;
    pauseRotation('notification');
    if (openPanel) closePanel();

    if (eventType === 'mastery') {
      renderMasteryNotification(event);
    } else if (eventType === 'beaten') {
      renderBeatenNotification(event);
    } else {
      renderAchievementNotification(event);
    }

    notification.classList.add('is-visible');
    playAchievementSound(eventType, event);

    window.setTimeout(() => {
      notification.classList.remove('is-visible');
      notificationActive = false;
      if (notificationQueue.length > 0) {
        window.setTimeout(showNextNotification, 250);
      } else {
        resumeRotation('notification');
      }
    }, event.duration_ms || 10000);
  };

  const connectAchievementEvents = () => {
    if (!window.EventSource || !notification) return;

    const events = new EventSource('/display/events');
    const enqueueEvent = (message) => {
      try {
        notificationQueue.push(JSON.parse(message.data));
        showNextNotification();
      } catch (error) {
        console.error('Could not parse display event', error);
      }
    };

    events.addEventListener('achievement', enqueueEvent);
    events.addEventListener('beaten', enqueueEvent);
    events.addEventListener('mastery', enqueueEvent);
  };

  const storePreference = (key, value) => {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      console.info('Could not save display preference', error);
    }
  };

  const updateQuickSettings = () => {
    if (audioState) audioState.textContent = !audioEnabled ? 'Disabled in dashboard' : (audioMuted ? 'Muted' : 'On');
    if (rotationState) rotationState.textContent = pauseReasons.has('manual') ? 'Paused' : 'Rotating';
    document.querySelectorAll('[data-speed]').forEach((button) => {
      const selected = button.dataset.speed === rotationSpeed;
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    const audioButton = document.querySelector('[data-audio-toggle]');
    if (audioButton) {
      audioButton.disabled = !audioEnabled;
      audioButton.setAttribute('aria-pressed', String(audioMuted));
    }
    const rotationButton = document.querySelector('[data-rotation-toggle]');
    if (rotationButton) rotationButton.setAttribute('aria-pressed', String(pauseReasons.has('manual')));
  };

  const updatePhaseLabel = (phase) => ({
    preparing: 'Preparing update',
    installing: 'Installing dependencies',
    restarting: 'Restarting service',
  }[phase] || 'Updating');

  const renderUpdateState = (state) => {
    const wasRunning = updateRunning;
    updateRunning = Boolean(state.installing);
    if (updateIndicator) updateIndicator.hidden = !state.update_available || Boolean(state.error) || updateRunning;
    if (updateState) {
      if (state.installing) updateState.textContent = updatePhaseLabel(state.install_phase);
      else if (state.install_phase === 'failed') updateState.textContent = 'Update failed';
      else if (state.error) updateState.textContent = 'Unable to check';
      else if (state.update_available && state.install_supported) updateState.textContent = 'Update available';
      else if (state.update_available) updateState.textContent = 'Update available · Manual install';
      else if (state.last_checked_at && state.latest_version) updateState.textContent = 'Up to date';
      else if (state.last_checked_at) updateState.textContent = 'No stable release';
      else updateState.textContent = 'Checking…';
    }
    if (updateDetail) {
      if (state.error) updateDetail.textContent = state.error;
      else if (state.update_available && !state.install_supported) updateDetail.textContent = state.install_unavailable_reason || 'Open Settings for download details';
      else if (state.update_available) updateDetail.textContent = `${state.installed_version || 'Development build'} → ${state.latest_version}`;
      else updateDetail.textContent = state.installed_version || state.latest_version || 'Development build';
    }
    if (updateCheckButton) updateCheckButton.disabled = state.checking || state.installing;
    if (updateInstallButton) {
      updateInstallButton.hidden = (!state.update_available || !state.install_supported) && !state.installing;
      updateInstallButton.disabled = state.installing;
      updateInstallButton.textContent = state.installing ? 'Updating…' : 'Update';
    }

    if (state.installing) {
      pauseRotation('update');
      if (updateOverlay) updateOverlay.hidden = false;
      if (updateOverlayTitle) updateOverlayTitle.textContent = 'Updating…';
      if (updateOverlayDetail) updateOverlayDetail.textContent = updatePhaseLabel(state.install_phase);
    } else if (wasRunning && state.error) {
      if (updateOverlay) updateOverlay.hidden = true;
      resumeRotation('update');
    } else if (wasRunning) {
      if (updateOverlay) updateOverlay.hidden = false;
      if (updateOverlayTitle) updateOverlayTitle.textContent = 'Update complete';
      if (updateOverlayDetail) updateOverlayDetail.textContent = 'Reloading display…';
      window.setTimeout(() => window.location.reload(), 700);
    } else {
      if (updateOverlay) updateOverlay.hidden = true;
      resumeRotation('update');
    }
  };

  const updateRequest = async (url, options = {}) => {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    renderUpdateState(payload);
    return payload;
  };

  const pollUpdateState = async () => {
    try {
      await updateRequest('/api/update/status');
    } catch (error) {
      if (updateRunning) {
        if (updateOverlay) updateOverlay.hidden = false;
        if (updateOverlayTitle) updateOverlayTitle.textContent = 'Reconnecting…';
        if (updateOverlayDetail) updateOverlayDetail.textContent = 'Waiting for the updated service';
      } else {
        if (updateState) updateState.textContent = 'Unable to check';
        if (updateDetail) updateDetail.textContent = error.message;
        if (updateIndicator) updateIndicator.hidden = true;
      }
    }
    window.setTimeout(pollUpdateState, updateRunning ? 2000 : 90000);
  };

  const refreshDisplaySlides = async () => {
    const response = await fetch('/display', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Display refresh failed (${response.status})`);
    const documentSnapshot = new DOMParser().parseFromString(await response.text(), 'text/html');
    const incomingTrack = documentSnapshot.querySelector('[data-carousel-track]');
    const incomingSlides = Array.from(incomingTrack?.querySelectorAll('[data-slide]') || []);
    if (incomingSlides.length === 0) throw new Error('Display refresh returned no slides');

    const activeType = slides[currentIndex]?.dataset.slide;
    const activeTypePosition = slides
      .slice(0, currentIndex + 1)
      .filter((slide) => slide.dataset.slide === activeType).length - 1;

    clearRotationTimers();
    window.clearTimeout(transitionTimerId);
    transitionTimerId = null;
    carouselTransitioning = false;
    carouselTrack.replaceChildren(
      ...incomingSlides.map((slide) => document.importNode(slide, true))
    );
    slides = Array.from(carouselTrack.querySelectorAll('[data-slide]'));

    let matchingTypePosition = -1;
    const matchingIndex = slides.findIndex((slide) => {
      if (slide.dataset.slide !== activeType) return false;
      matchingTypePosition += 1;
      return matchingTypePosition === activeTypePosition;
    });
    currentIndex = matchingIndex >= 0 ? matchingIndex : Math.min(currentIndex, slides.length - 1);
    slides.forEach((slide, index) => {
      slide.classList.toggle('is-active', index === currentIndex);
      const list = slide.querySelector('.display-ranking-list, .display-activity-list');
      if (list) list.style.transform = 'translate3d(0, 0, 0)';
    });
    appendCarouselClones();
    setCarouselPosition(currentIndex + 1, false);
    activeDuration = slideDuration();
    remainingDuration = activeDuration;
    scrollCycleElapsed = 0;
    if (pauseReasons.size === 0) {
      scheduleNextSlide();
    } else {
      rotationPaused = true;
    }
  };

  const showPanel = (panel) => {
    if (!panel || notificationActive || notificationQueue.length > 0 || openPanel) return;
    openPanel = panel;
    pauseRotation('panel');
    panel.classList.add('is-open');
    panel.setAttribute('aria-hidden', 'false');
    panel.querySelector('.display-close-button')?.focus({ preventScroll: true });
  };

  const closePanel = () => {
    if (!openPanel) return;
    const panel = openPanel;
    openPanel = null;
    panel.classList.remove('is-open');
    panel.setAttribute('aria-hidden', 'true');
    resumeRotation('panel');
    root.focus({ preventScroll: true });
  };

  document.querySelectorAll('[data-close-panel]').forEach((button) => {
    button.addEventListener('click', closePanel);
  });

  updateIndicator?.addEventListener('click', () => showPanel(settingsPanel));
  updateCheckButton?.addEventListener('click', async () => {
    updateCheckButton.disabled = true;
    try {
      await updateRequest('/api/update/check', { method: 'POST' });
    } catch (error) {
      if (updateState) updateState.textContent = 'Unable to check';
      if (updateDetail) updateDetail.textContent = error.message;
      updateCheckButton.disabled = false;
    }
  });
  updateInstallButton?.addEventListener('click', async () => {
    if (updateRunning || !window.confirm('Install this update and restart LeftoverAchievements?')) return;
    updateInstallButton.disabled = true;
    try {
      await updateRequest('/api/update/install', { method: 'POST' });
    } catch (error) {
      if (updateState) updateState.textContent = 'Update failed';
      if (updateDetail) updateDetail.textContent = error.message;
      updateInstallButton.disabled = false;
    }
  });

  document.querySelector('[data-audio-toggle]')?.addEventListener('click', () => {
    audioMuted = !audioMuted;
    storePreference(STORAGE_KEYS.muted, String(audioMuted));
    updateQuickSettings();
    if (!audioMuted) enableDisplayAudio();
  });

  document.querySelector('[data-rotation-toggle]')?.addEventListener('click', () => {
    if (pauseReasons.has('manual')) {
      resumeRotation('manual');
    } else {
      pauseRotation('manual');
    }
    updateQuickSettings();
  });

  document.querySelectorAll('[data-speed]').forEach((button) => {
    button.addEventListener('click', () => {
      const selectedSpeed = button.dataset.speed;
      if (!Object.prototype.hasOwnProperty.call(ROTATION_SPEEDS, selectedSpeed)) return;
      rotationSpeed = selectedSpeed;
      storePreference(STORAGE_KEYS.speed, rotationSpeed);
      activeDuration = slideDuration();
      remainingDuration = activeDuration;
      updateQuickSettings();
    });
  });

  let pointerGesture = null;
  root.addEventListener('pointerdown', (event) => {
    if (openPanel || notificationActive || event.isPrimary === false || (event.pointerType === 'mouse' && event.button !== 0)) return;
    pointerGesture = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      fromTop: event.clientY <= GESTURE.edgeSize,
      fromBottom: event.clientY >= window.innerHeight - GESTURE.edgeSize,
    };
    root.setPointerCapture?.(event.pointerId);
  });

  root.addEventListener('pointerup', (event) => {
    if (!pointerGesture || pointerGesture.id !== event.pointerId) return;
    const gesture = pointerGesture;
    pointerGesture = null;
    if (root.hasPointerCapture?.(event.pointerId)) root.releasePointerCapture(event.pointerId);
    if (notificationActive || notificationQueue.length > 0) return;

    const deltaX = event.clientX - gesture.x;
    const deltaY = event.clientY - gesture.y;
    const absX = Math.abs(deltaX);
    const absY = Math.abs(deltaY);
    const horizontal = absX >= GESTURE.horizontalDistance && absX > absY * GESTURE.horizontalDominance;
    if (horizontal) {
      activateSlide(currentIndex + (deltaX < 0 ? 1 : -1));
      return;
    }

    const vertical = absY >= GESTURE.verticalDistance && absY > absX * GESTURE.verticalDominance;
    if (vertical && gesture.fromTop && deltaY > 0) showPanel(settingsPanel);
    if (vertical && gesture.fromBottom && deltaY < 0) showPanel(dashboardPanel);
  });

  root.addEventListener('pointercancel', () => { pointerGesture = null; });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closePanel();
  });

  slides.forEach((slide, index) => {
    slide.classList.toggle('is-active', index === currentIndex);
    const list = slide.querySelector('.display-ranking-list, .display-activity-list');
    if (list) list.style.transform = 'translate3d(0, 0, 0)';
  });

  root.tabIndex = -1;
  setCarouselPosition(currentIndex + 1, false);
  scheduleNextSlide();
  connectAchievementEvents();
  updateQuickSettings();
  pollUpdateState();

  if (audioEnabled) {
    document.addEventListener('pointerdown', enableDisplayAudio, { once: true });
    document.addEventListener('keydown', enableDisplayAudio, { once: true });
  }

  const refreshWhenIdle = async () => {
    if (document.visibilityState !== 'visible' || notificationActive || notificationQueue.length > 0 || openPanel) {
      window.setTimeout(refreshWhenIdle, 60 * 1000);
      return;
    }
    if (autoReloadEnabled) {
      window.location.reload();
      return;
    }
    try {
      await refreshDisplaySlides();
      window.setTimeout(refreshWhenIdle, 15 * 60 * 1000);
    } catch (error) {
      console.info('Could not refresh display data', error);
      window.setTimeout(refreshWhenIdle, 60 * 1000);
    }
  };
  window.setTimeout(refreshWhenIdle, 15 * 60 * 1000);
})();
