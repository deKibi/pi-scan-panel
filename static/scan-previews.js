// Start image requests after the document loads so previews do not hold up the page.
window.addEventListener("load", () => {
  const previewQueue = new Set();
  const observed = new Set();
  const previewMargin = 200;
  const maxActivePreviews = 2;
  let activePreviews = 0;

  function loadNextPreviews() {
    for (const image of previewQueue) {
      if (!image.isConnected) previewQueue.delete(image);
    }
    const candidates = [...previewQueue].map((image) => {
      const bounds = image.getBoundingClientRect();
      return {
        image,
        top: bounds.top,
        bottom: bounds.bottom,
        visible: bounds.bottom > 0 && bounds.top < window.innerHeight,
      };
    }).filter((item) => (
      item.bottom >= -previewMargin && item.top <= window.innerHeight + previewMargin
    )).sort((first, second) => (
      Number(second.visible) - Number(first.visible) || first.top - second.top
    ));

    for (const { image, visible } of candidates) {
      if (activePreviews >= maxActivePreviews) {
        break;
      }

      previewQueue.delete(image);
      previewObserver.unobserve(image);
      activePreviews += 1;
      image.fetchPriority = visible ? "high" : "low";

      function finishPreview(loaded) {
        const preview = image.closest(".scan-preview");
        if (loaded) {
          preview.classList.add("is-loaded");
        } else {
          preview.classList.add("is-error");
          preview.title = preview.tagName === "A"
            ? "Прев’ю недоступне. Відкрити оригінал."
            : "Прев’ю недоступне.";
          preview.setAttribute("aria-label", `${image.alt}: ${preview.title}`);
        }
        activePreviews -= 1;
        loadNextPreviews();
      }

      image.addEventListener("load", () => finishPreview(true), { once: true });
      image.addEventListener("error", () => finishPreview(false), { once: true });
      image.src = image.dataset.previewSrc;
    }
  }

  const previewObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        previewQueue.add(entry.target);
      } else {
        previewQueue.delete(entry.target);
      }
    }
    loadNextPreviews();
  }, { rootMargin: `${previewMargin}px 0px` });

  function observePreviews() {
    for (const image of observed) {
      if (!image.isConnected) {
        previewObserver.unobserve(image);
        previewQueue.delete(image);
        observed.delete(image);
      }
    }
    document.querySelectorAll("img[data-preview-src]").forEach((image) => {
      if (observed.has(image)) return;
      observed.add(image);
      previewObserver.observe(image);
    });
  }

  document.addEventListener("scan-previews:update", observePreviews);
  observePreviews();

}, { once: true });
