(() => {
  const root = document.querySelector('[data-display-rotation]');
  if (!root) return;

  const carouselTrack = root.querySelector('[data-carousel-track]');
  const slides = Array.from(root.querySelectorAll('[data-slide]'));
  if (!carouselTrack || slides.length === 0) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const carouselTransitionDuration = reducedMotion ? 1 : 650;

  const firstSlideClone = slides[0].cloneNode(true);
  firstSlideClone.classList.remove('is-active');
  firstSlideClone.dataset.carouselClone = 'true';
  firstSlideClone.setAttribute('aria-hidden', 'true');
  carouselTrack.appendChild(firstSlideClone);

  const notification = document.querySelector('[data-achievement-notification]');
  const audioEnabled = root.dataset.audioEnabled === 'true';
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
  let carouselPosition = currentIndex;

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

  const playGeneratedAchievementSound = () => {
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
    if (!audioEnabled) return;

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
    if (!audioEnabled) return;

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
    const list = viewport?.querySelector('.display-ranking-list');
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

  const scheduleNextSlide = (durationOverride = null, preserveScroll = false) => {
    clearRotationTimers();

    rotationPaused = false;
    const activeSlide = slides[currentIndex];
    const duration = durationOverride ?? Number.parseInt(activeSlide.dataset.duration || '60000', 10);
    activeDuration = duration;
    slideStartedAt = window.performance.now();
    startLeaderboardScroll(activeSlide, preserveScroll);
    timerId = window.setTimeout(() => activateSlide(currentIndex + 1), duration);
  };

  const finishCarouselTransition = () => {
    window.clearTimeout(transitionTimerId);
    transitionTimerId = null;
    if (!carouselTransitioning) return;

    carouselTransitioning = false;
    if (carouselPosition === slides.length) setCarouselPosition(0, false);
  };

  const activateSlide = (nextIndex) => {
    clearRotationTimers();
    const previousIndex = currentIndex;
    const wrapping = nextIndex >= slides.length;
    currentIndex = nextIndex % slides.length;
    slides[previousIndex].classList.remove('is-active');
    slides[currentIndex].classList.add('is-active');

    carouselTransitioning = true;
    setCarouselPosition(wrapping ? slides.length : currentIndex);
    scheduleNextSlide();
    transitionTimerId = window.setTimeout(finishCarouselTransition, carouselTransitionDuration + 50);
  };

  const pauseRotation = () => {
    if (rotationPaused) return;
    rotationPaused = true;

    if (carouselTransitioning) {
      finishCarouselTransition();
    }

    const elapsed = window.performance.now() - slideStartedAt;
    remainingDuration = Math.max(500, activeDuration - elapsed);
    clearRotationTimers();
  };

  const resumeRotation = () => {
    if (!rotationPaused) return;
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
  };

  const renderMasteryNotification = (event) => {
    notification.classList.remove('is-beaten');
    notification.classList.add('is-mastery');
    setText('[data-achievement-heading]', 'Game Mastered');
    setText('[data-achievement-mode]', 'Mastery');
    setImage('[data-achievement-user-avatar]', event.avatar, `${event.username} avatar`);
    setImage('[data-achievement-badge]', event.game_image, `${event.game_title} image`);
    setText('[data-achievement-username]', event.username);
    setText('[data-achievement-title]', event.game_title);
    setText(
      '[data-achievement-description]',
      `${event.hardcore_achievements} / ${event.total_achievements} Hardcore achievements completed`
    );
    setText('[data-achievement-game]', 'Hardcore Mastery');
    setText('[data-achievement-points]', `${event.hardcore_points_display} / ${event.total_points_display}`);
    setText('[data-achievement-retro-points]', '');
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
      event.total_points ? `${event.hardcore_points_display} / ${event.total_points_display} points` : ''
    );
    setText('[data-achievement-retro-points]', '');
  };

  const showNextNotification = () => {
    if (!notification || notificationActive || notificationQueue.length === 0) return;

    const event = notificationQueue.shift();
    const eventType = event.type || 'achievement';
    notificationActive = true;
    pauseRotation();

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
        resumeRotation();
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

  slides.forEach((slide, index) => {
    slide.classList.toggle('is-active', index === currentIndex);
    const list = slide.querySelector('.display-ranking-list');
    if (list) list.style.transform = 'translate3d(0, 0, 0)';
  });

  setCarouselPosition(currentIndex, false);
  scheduleNextSlide();
  connectAchievementEvents();

  if (audioEnabled) {
    document.addEventListener('pointerdown', enableDisplayAudio, { once: true });
    document.addEventListener('keydown', enableDisplayAudio, { once: true });
  }

  window.setTimeout(() => {
    if (document.visibilityState === 'visible' && !notificationActive) {
      window.location.reload();
    }
  }, 15 * 60 * 1000);
})();
