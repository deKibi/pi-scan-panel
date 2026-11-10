// Confirmed submissions bubble here after the shared confirmation dialog.
(() => {
  const list = document.querySelector("#file-list");
  if (!list) return;
  const actionForms = ".action-form, .trash-action";
  const notice = document.querySelector("#action-notice");
  const noticeText = document.querySelector("#action-notice-text");
  const loginLink = document.querySelector("#action-login");
  let busy = false;
  let noticeTimer = null;

  function hideNotice() {
    clearTimeout(noticeTimer);
    noticeTimer = null;
    notice.hidden = true;
  }

  function showNotice(message, error = false, login = false, duration = error ? 10000 : 6000) {
    clearTimeout(noticeTimer);
    noticeTimer = null;
    noticeText.textContent = message;
    notice.classList.toggle("error", error);
    loginLink.hidden = !login;
    notice.hidden = false;
    if (duration > 0) {
      noticeTimer = setTimeout(hideNotice, duration);
    }
  }

  notice.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    hideNotice();
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("#scan-per-page, #trash-per-page")) {
      event.target.form.requestSubmit();
    }
  });

  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (event.defaultPrevented || !form.matches(actionForms) || !list.contains(form)) return;
    event.preventDefault();
    if (busy) return;
    busy = true;

    const submitter = event.submitter || form.querySelector("button[type='submit']");
    const row = form.closest(".scan-item");
    const rowIndex = [...list.querySelectorAll(".scan-item")].indexOf(row);
    // Build the body before disabling controls so confirmed trash IDs are retained.
    const body = new FormData(form);
    const buttons = [...list.querySelectorAll("button")].filter((button) => !button.disabled);
    buttons.forEach((button) => { button.disabled = true; });
    list.setAttribute("aria-busy", "true");
    showNotice("Виконуємо дію…", false, false, 0);

    let focusTarget = submitter;
    let restoreFocus = false;
    try {
      const response = await fetch(form.action, {
        method: "POST", body, headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (response.status === 401) {
        showNotice("Сесію завершено. Увійдіть знову.", true, true);
        return;
      }
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
        throw new Error("Unexpected action response");
      }
      const data = await response.json();
      if (typeof data.success !== "boolean" || typeof data.message !== "string") {
        throw new Error("Invalid action response");
      }

      const active = document.activeElement;
      restoreFocus = active === submitter || active === document.body;
      const x = window.scrollX;
      const y = window.scrollY;
      const anchors = [...list.querySelectorAll(".scan-item")].map((item) => ({
        id: item.dataset.fileId, top: item.getBoundingClientRect().top,
      })).sort((first, second) => Math.abs(first.top) - Math.abs(second.top));

      if (typeof data.list_html === "string") {
        restoreFocus ||= list.contains(active);
        list.innerHTML = data.list_html;
        list.dataset.page = data.page;
        list.dataset.perPage = data.per_page;
        history.replaceState(history.state, "", data.url);
        if (typeof data.last_scan_html === "string") {
          document.querySelector("#last-scan-actions").innerHTML = data.last_scan_html;
        }
        const rows = [...list.querySelectorAll(".scan-item")];
        const anchor = anchors.find((item) => rows.some((candidate) => candidate.dataset.fileId === item.id));
        const newAnchor = anchor && rows.find((item) => item.dataset.fileId === anchor.id);
        const top = newAnchor ? window.scrollY + newAnchor.getBoundingClientRect().top - anchor.top : y;
        window.scrollTo({ left: x, top, behavior: "instant" });
        const nextRow = rows[Math.min(Math.max(rowIndex, 0), rows.length - 1)];
        focusTarget = nextRow?.querySelector("button, a") || document.querySelector("#file-list-heading");
      } else if (data.file && row && data.file.id === row.dataset.fileId) {
        row.querySelector(".scan-meta > span").textContent = data.file.metadata;
        const image = row.querySelector("img[data-preview-src]");
        const replacement = image.cloneNode(false);
        replacement.removeAttribute("src");
        replacement.dataset.previewSrc = data.file.preview_url;
        const preview = image.closest(".scan-preview");
        preview.classList.remove("is-loaded", "is-error");
        preview.removeAttribute("title");
        preview.removeAttribute("aria-label");
        image.replaceWith(replacement);
        window.scrollTo({ left: x, top: y, behavior: "instant" });
      }
      document.dispatchEvent(new Event("scan-previews:update"));
      showNotice(data.message, !data.success);
    } catch (error) {
      showNotice("Не вдалося отримати результат дії. Вона могла виконатися. Оновіть список перед повторною спробою.", true);
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
      list.removeAttribute("aria-busy");
      busy = false;
      restoreFocus ||= document.activeElement === submitter || document.activeElement === document.body;
      if (restoreFocus && focusTarget?.isConnected) focusTarget.focus({ preventScroll: true });
    }
  });
})();
