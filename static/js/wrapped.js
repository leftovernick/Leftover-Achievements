(() => {
  const story = document.querySelector("[data-wrapped-story]");
  const cards = Array.from(document.querySelectorAll("[data-story-card]"));
  const progress = Array.from(document.querySelectorAll("[data-progress-index]"));
  const counter = document.querySelector("[data-current-card]");
  const previous = document.querySelector("[data-story-previous]");
  const next = document.querySelector("[data-story-next]");
  const slideResultPreview = document.querySelector("[data-slide-result-preview]");
  const exportButtons = Array.from(document.querySelectorAll("[data-wrapped-export]"));
  const exportStatus = document.querySelector("[data-wrapped-export-status]");

  if (!story || cards.length === 0) return;

  const desktopCanvas = { width: 1440, height: 810 };
  const mobileCanvas = { width: 540, height: 960 };
  let desktopMaximumScale;
  const updateCanvasScale = () => {
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.visualViewport?.height || window.innerHeight;

    if (window.matchMedia("(max-width: 800px)").matches) {
      document.documentElement.style.removeProperty("--wrapped-desktop-scale");
      document.documentElement.style.removeProperty("--wrapped-desktop-rendered-height");
      document.documentElement.style.removeProperty("--wrapped-desktop-page-height");
      document.documentElement.style.removeProperty("--wrapped-desktop-center-y");
      const scale = viewportWidth / mobileCanvas.width;
      document.documentElement.style.setProperty("--wrapped-mobile-scale", scale.toFixed(4));
      document.documentElement.style.setProperty(
        "--wrapped-mobile-rendered-height",
        `${(mobileCanvas.height * scale).toFixed(2)}px`,
      );
      return;
    }
    document.documentElement.style.removeProperty("--wrapped-mobile-scale");
    document.documentElement.style.removeProperty("--wrapped-mobile-rendered-height");
    const chromeBottom = Math.max(
      document.querySelector(".wrapped-chrome")?.getBoundingClientRect().bottom || 0,
      document.querySelector(".wrapped-progress")?.getBoundingClientRect().bottom || 0,
    );
    const bottomGap = 18;
    if (desktopMaximumScale === undefined) {
      const browserChromeHeight = Math.max(0, window.outerHeight - viewportHeight);
      const maximumViewportHeight = Math.max(
        viewportHeight,
        (window.screen?.availHeight || window.outerHeight) - browserChromeHeight,
      );
      desktopMaximumScale = Math.min(
        1,
        Math.max(
          0.1,
          (maximumViewportHeight - chromeBottom - bottomGap) / desktopCanvas.height,
        ),
      );
    }
    const scale = Math.min(desktopMaximumScale, viewportWidth / desktopCanvas.width);
    const renderedHeight = desktopCanvas.height * scale;
    const pageHeight = Math.max(
      viewportHeight,
      chromeBottom + renderedHeight + bottomGap,
    );
    const centerY = chromeBottom
      + (pageHeight - chromeBottom - bottomGap) / 2;
    document.documentElement.style.setProperty("--wrapped-desktop-scale", scale.toFixed(4));
    document.documentElement.style.setProperty(
      "--wrapped-desktop-rendered-height",
      `${renderedHeight.toFixed(2)}px`,
    );
    document.documentElement.style.setProperty(
      "--wrapped-desktop-page-height",
      `${pageHeight.toFixed(2)}px`,
    );
    document.documentElement.style.setProperty(
      "--wrapped-desktop-center-y",
      `${centerY.toFixed(2)}px`,
    );
  };

  window.addEventListener("resize", updateCanvasScale, { passive: true });
  window.visualViewport?.addEventListener("resize", updateCanvasScale, { passive: true });

  const recapHero = document.querySelector(".recap-layout .recap-art__hero");
  const classifyRecapCover = () => {
    if (!recapHero?.naturalWidth || !recapHero.naturalHeight) return;
    recapHero.closest(".recap-layout")?.classList.toggle(
      "recap-layout--portrait-art",
      recapHero.naturalHeight / recapHero.naturalWidth > 1.18,
    );
  };
  if (recapHero?.complete) classifyRecapCover();
  else recapHero?.addEventListener("load", classifyRecapCover, { once: true });

  document.documentElement.style.setProperty("--story-count", cards.length);
  story.style.setProperty("--story-count", cards.length);
  let activeIndex = 0;

  const setActive = (index) => {
    activeIndex = Math.max(0, Math.min(cards.length - 1, index));
    cards.forEach((card, cardIndex) => card.classList.toggle("is-active", cardIndex === activeIndex));
    progress.forEach((segment, segmentIndex) => {
      segment.classList.toggle("is-active", segmentIndex === activeIndex);
      segment.classList.toggle("is-complete", segmentIndex < activeIndex);
      if (segmentIndex === activeIndex) segment.setAttribute("aria-current", "step");
      else segment.removeAttribute("aria-current");
    });
    if (counter) counter.textContent = String(activeIndex + 1);
    if (slideResultPreview) {
      const slideType = cards[activeIndex]?.dataset.cardType || "";
      const selectedVariant = document.body.dataset.selectedSlideType === slideType
        ? document.body.dataset.selectedSlideVariant || ""
        : "";
      const resultValue = `${slideType}|${selectedVariant}`;
      if (Array.from(slideResultPreview.options).some((option) => option.value === resultValue)) {
        slideResultPreview.value = resultValue;
      }
    }
    if (previous) previous.disabled = activeIndex === 0;
    if (next) next.disabled = activeIndex === cards.length - 1;
  };

  const goTo = (index) => {
    const target = cards[Math.max(0, Math.min(cards.length - 1, index))];
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  progress.forEach((segment, index) => segment.addEventListener("click", () => goTo(index)));
  previous?.addEventListener("click", () => goTo(activeIndex - 1));
  next?.addEventListener("click", () => goTo(activeIndex + 1));
  slideResultPreview?.addEventListener("change", () => {
    const [slide, variant = ""] = slideResultPreview.value.split("|");
    const url = new URL(window.location.href);
    url.searchParams.set("year", document.body.dataset.wrappedYear);
    url.searchParams.set("slide", slide);
    if (variant) url.searchParams.set("variant", variant);
    else url.searchParams.delete("variant");
    url.searchParams.delete("special");
    window.location.assign(url);
  });

  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
    if (visible) setActive(cards.indexOf(visible.target));
  }, { threshold: [0.45, 0.6, 0.75] });

  cards.forEach((card) => observer.observe(card));

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(target.tagName))) return;
    const direction = ["ArrowDown", "ArrowRight", "PageDown"].includes(event.key) ? 1
      : ["ArrowUp", "ArrowLeft", "PageUp"].includes(event.key) ? -1
      : 0;
    if (!direction) return;
    event.preventDefault();
    goTo(activeIndex + direction);
  });

  const safeFilenamePart = (value) => value.trim().replace(/[^a-z0-9_-]+/gi, "-").replace(/^-|-$/g, "") || "player";

  // Packaging differs by platform. These explicit source-image trims keep
  // console banners and spines from displacing the actual cover artwork.
  const COVER_CROP_PROFILES = Object.freeze({
    "game boy": { left: 0.21, top: 0.02, right: 0, bottom: 0.02 },
    "game boy color": { left: 0.18, top: 0.02, right: 0, bottom: 0.02 },
    "playstation 2": { left: 0, top: 0.075, right: 0, bottom: 0 },
  });

  const normalizedConsole = (value) => (value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

  const imageDataUrl = async (source) => {
    const absolute = new URL(source, window.location.href);
    const requestUrl = absolute.origin === window.location.origin
      ? absolute.href
      : `/api/wrapped/image?url=${encodeURIComponent(absolute.href)}`;
    const response = await fetch(requestUrl);
    if (!response.ok) throw new Error(`Image request failed (${response.status})`);
    const blob = await response.blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  };

  const lockCoverAspectRatio = (recap) => {
    const image = recap?.querySelector(".recap-art__hero");
    const container = image?.closest(".recap-art");
    if (!image?.naturalWidth || !image.naturalHeight || !container) return;
    const bounds = container.getBoundingClientRect();
    const isPortrait = recap.classList.contains("recap-layout--portrait-art");
    const profile = COVER_CROP_PROFILES[normalizedConsole(recap.dataset.coverConsole)];
    const crop = profile || { left: 0, top: 0, right: 0, bottom: 0 };
    const visibleWidth = image.naturalWidth * (1 - crop.left - crop.right);
    const visibleHeight = image.naturalHeight * (1 - crop.top - crop.bottom);
    const overscan = profile ? 1 : (isPortrait ? 1.12 : 1);
    const scale = Math.max(bounds.width / visibleWidth, bounds.height / visibleHeight) * overscan;
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    const croppedWidth = visibleWidth * scale;
    const croppedHeight = visibleHeight * scale;
    image.style.position = "absolute";
    image.style.top = `${(bounds.height - croppedHeight) / 2 - crop.top * image.naturalHeight * scale - (!profile && isPortrait ? bounds.height * 0.06 : 0)}px`;
    image.style.left = `${(bounds.width - croppedWidth) / 2 - crop.left * image.naturalWidth * scale}px`;
    image.style.width = `${width}px`;
    image.style.height = `${height}px`;
    image.style.maxWidth = "none";
    image.style.objectFit = "fill";
    image.style.transform = "none";
  };

  const prepareExportStage = async (format) => {
    const finalCard = cards.find((card) => card.dataset.cardType === "final_recap");
    if (!finalCard) throw new Error("The final recap is unavailable.");
    const stage = document.createElement("div");
    stage.className = `wrapped-export-stage wrapped-export-stage--${format}`;
    const clone = finalCard.cloneNode(true);
    clone.classList.add("is-active");
    clone.querySelector(".wrapped-export-actions")?.remove();
    clone.querySelector(".wrapped-kicker")?.remove();
    const decoration = document.createElement("div");
    decoration.className = "wrapped-export-decoration";
    const upperSegment = document.createElement("span");
    upperSegment.className = "wrapped-export-decoration__segment wrapped-export-decoration__segment--upper";
    const lowerSegment = document.createElement("span");
    lowerSegment.className = "wrapped-export-decoration__segment wrapped-export-decoration__segment--lower";
    decoration.append(upperSegment, lowerSegment);
    clone.prepend(decoration);
    const recap = clone.querySelector(".recap-layout");
    if (recap) {
      const fade = document.createElement("div");
      fade.className = "wrapped-export-fade";
      recap.append(fade);
      if (format === "story") {
        const supportImages = Array.from(recap.querySelectorAll(".recap-art > .recap-art__support"));
        if (supportImages.length) {
          const supports = document.createElement("div");
          supports.className = "wrapped-export-supports";
          supports.append(...supportImages);
          recap.append(supports);
        }
      }
    }
    stage.append(clone);
    document.body.append(stage);
    const images = Array.from(stage.querySelectorAll("img"));
    await Promise.all(images.map(async (image) => {
      try {
        image.src = await imageDataUrl(image.src);
        await image.decode();
      } catch (error) {
        console.warn("Wrapped export omitted an unavailable image", error);
        image.remove();
      }
    }));
    await document.fonts?.ready;
    lockCoverAspectRatio(recap);
    if (recap) {
      const frame = clone.querySelector(".wrapped-card__frame");
      const frameRect = frame.getBoundingClientRect();
      const recapRect = recap.getBoundingClientRect();
      const shadow = document.createElement("div");
      shadow.className = "wrapped-export-recap-shadow";
      shadow.style.left = `${recapRect.left - frameRect.left + 18}px`;
      shadow.style.top = `${recapRect.top - frameRect.top + 18}px`;
      shadow.style.width = `${recapRect.width}px`;
      shadow.style.height = `${recapRect.height}px`;
      frame.prepend(shadow);
    }
    return stage;
  };

  const canvasBlob = (canvas) => new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Could not create PNG.")), "image/png");
  });

  const saveBlob = (blob, filename) => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  };

  const exportRecap = async (button) => {
    const format = button.dataset.wrappedExport;
    const dimensions = format === "story"
      ? { width: 1080, height: 1920, scale: 1 }
      : { width: 1440, height: 810, scale: 1600 / 1440 };
    const originalLabel = button.innerHTML;
    exportButtons.forEach((item) => { item.disabled = true; });
    button.textContent = "Creating PNG…";
    if (exportStatus) exportStatus.textContent = "Preparing your image…";
    let stage;
    try {
      stage = await prepareExportStage(format);
      const canvas = await window.html2canvas(stage, {
        backgroundColor: null,
        logging: false,
        scale: dimensions.scale,
        width: dimensions.width,
        height: dimensions.height,
        windowWidth: dimensions.width,
        windowHeight: dimensions.height,
      });
      const blob = await canvasBlob(canvas);
      const username = safeFilenamePart(document.body.dataset.wrappedUsername || "player");
      const year = document.body.dataset.wrappedYear || "wrapped";
      const filename = `${username}-${year}-wrapped-${format}.png`;
      saveBlob(blob, filename);
      if (exportStatus) exportStatus.textContent = format === "story" ? "Story PNG saved." : "Horizontal PNG saved.";
    } catch (error) {
      console.error("Wrapped PNG export failed", error);
      if (exportStatus) exportStatus.textContent = "Could not create the PNG. Please try again.";
    } finally {
      stage?.remove();
      button.innerHTML = originalLabel;
      exportButtons.forEach((item) => { item.disabled = false; });
    }
  };

  exportButtons.forEach((button) => button.addEventListener("click", () => exportRecap(button)));

  updateCanvasScale();
  const initialCardType = document.body.dataset.initialCardType;
  const initialCardIndex = initialCardType
    ? cards.findIndex((card) => card.dataset.cardType === initialCardType)
    : -1;
  setActive(initialCardIndex >= 0 ? initialCardIndex : 0);
  if (initialCardIndex >= 0) {
    requestAnimationFrame(() => {
      document.documentElement.style.scrollBehavior = "auto";
      cards[initialCardIndex].scrollIntoView({ block: "start" });
      requestAnimationFrame(() => document.documentElement.style.removeProperty("scroll-behavior"));
    });
  }
})();
