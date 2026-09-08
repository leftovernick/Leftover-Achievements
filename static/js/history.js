(() => {
  const list = document.querySelector("[data-week-list]");
  const sentinel = document.querySelector("[data-week-sentinel]");
  const endMessage = document.querySelector("[data-week-list-end]");
  if (!list || !sentinel || sentinel.hidden) return;

  let offset = Number(list.dataset.nextOffset || 5);
  let loading = false;

  async function loadMoreWeeks() {
    if (loading || sentinel.hidden) return;
    loading = true;
    sentinel.disabled = true;
    sentinel.textContent = "Loading…";

    try {
      const response = await fetch(`/history/weeks?offset=${offset}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`History request failed: ${response.status}`);

      const data = await response.json();
      for (const week of data.items) {
        const link = document.createElement("a");
        link.href = `/history?week=${encodeURIComponent(week.week_start)}`;
        link.textContent = week.label;
        if (week.week_start === list.dataset.selectedWeek) {
          link.className = "active";
          link.setAttribute("aria-current", "page");
        }
        list.insertBefore(link, sentinel);
      }

      offset += data.items.length;
      if (!data.has_more || data.items.length === 0) {
        sentinel.hidden = true;
        endMessage.hidden = false;
        observer.disconnect();
      }
    } catch (error) {
      sentinel.textContent = "Try loading again";
      console.error(error);
      return;
    } finally {
      loading = false;
      sentinel.disabled = false;
      if (!sentinel.hidden && sentinel.textContent !== "Try loading again") {
        sentinel.textContent = "Load more weeks";
      }
    }
  }

  sentinel.addEventListener("click", loadMoreWeeks);
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMoreWeeks();
    },
    { root: list, rootMargin: "0px 0px 80px 0px" },
  );
  observer.observe(sentinel);
})();
