// Confirmed submissions bubble here after the shared confirmation dialog.
(() => {
  const list = document.querySelector("#file-list");
  if (!list) return;
  const actionForms = ".action-form, .trash-action";
  const notice = document.querySelector("#action-notice");
  const noticeText = document.querySelector("#action-notice-text");
  const loginLink = document.querySelector("#action-login");
  const revertButton = document.querySelector("#action-revert");
  const closeButton = document.querySelector("#action-close");
  let busy = false;
  let noticeTimer = null;
  let noticeRemaining = null;
  let noticeStarted = 0;
  let pointerInside = false;
  let revertAction = null;
  let noticeFocusTarget = null;

  function hideNotice() {
    clearTimeout(noticeTimer);
    noticeTimer = null;
    noticeRemaining = null;
    revertAction = null;
    revertButton.hidden = true;
    if (notice.contains(document.activeElement)) {
      const target = noticeFocusTarget?.isConnected ? noticeFocusTarget : document.querySelector("#file-list-heading");
      target?.focus({ preventScroll: true });
    }
    notice.hidden = true;
  }

  function pauseNotice() {
    if (noticeTimer === null) return;
    noticeRemaining = Math.max(0, noticeRemaining - (performance.now() - noticeStarted));
    clearTimeout(noticeTimer);
    noticeTimer = null;
  }

  function resumeNotice() {
    if (notice.hidden || noticeRemaining === null || noticeTimer !== null
        || pointerInside || document.hidden || notice.contains(document.activeElement)) return;
    if (noticeRemaining <= 0) {
      hideNotice();
      return;
    }
    noticeStarted = performance.now();
    noticeTimer = setTimeout(hideNotice, noticeRemaining);
  }

  function showNotice(message, error = false, login = false, duration = error ? 10000 : 6000, revert = null) {
    clearTimeout(noticeTimer);
    noticeTimer = null;
    noticeRemaining = duration > 0 ? duration : null;
    revertAction = revert;
    noticeText.textContent = message;
    notice.classList.toggle("error", error);
    loginLink.hidden = !login;
    revertButton.hidden = !revert;
    notice.hidden = false;
    resumeNotice();
  }

  closeButton.addEventListener("click", hideNotice);
  notice.addEventListener("pointerenter", (event) => {
    // Touch does not have a persistent hover state after the finger is lifted.
    if (event.pointerType === "touch") return;
    pointerInside = true;
    pauseNotice();
  });
  notice.addEventListener("pointerleave", () => {
    pointerInside = false;
    resumeNotice();
  });
  notice.addEventListener("pointerdown", pauseNotice);
  notice.addEventListener("pointerup", resumeNotice);
  notice.addEventListener("pointercancel", resumeNotice);
  notice.addEventListener("focusin", pauseNotice);
  notice.addEventListener("focusout", (event) => {
    if (!notice.contains(event.relatedTarget)) queueMicrotask(resumeNotice);
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) pauseNotice();
    else resumeNotice();
  });

  revertButton.addEventListener("click", async () => {
    if (busy || !revertAction) return;
    const action = revertAction;
    const body = new FormData();
    Object.entries(action.fields).forEach(([name, value]) => body.append(name, value));
    const row = [...list.querySelectorAll(".scan-item")].find((item) => item.dataset.fileId === action.file_id);
    await performAction(action.url, body, revertButton, row, true);
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
    const submitter = event.submitter || form.querySelector("button[type='submit']");
    // Build the body before disabling controls so confirmed trash IDs are retained.
    await performAction(form.action, new FormData(form), submitter, form.closest(".scan-item"));
  });

  async function performAction(url, body, submitter, row, reverting = false) {
    if (busy) return;
    busy = true;

    const rowIndex = [...list.querySelectorAll(".scan-item")].indexOf(row);
    const buttons = [...list.querySelectorAll("button"), revertButton].filter((button) => !button.disabled);
    buttons.forEach((button) => { button.disabled = true; });
    list.setAttribute("aria-busy", "true");
    showNotice("Виконуємо дію…", false, false, 0);

    let focusTarget = reverting ? row?.querySelector("button, a") || document.querySelector("#file-list-heading") : submitter;
    let restoreFocus = false;
    try {
      const response = await fetch(url, {
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
      const revert = data.success && !reverting ? data.revert || null : null;
      showNotice(data.message, !data.success, false, revert || !data.success ? 10000 : 6000, revert);
    } catch (error) {
      showNotice("Не вдалося отримати результат дії. Вона могла виконатися. Оновіть список перед повторною спробою.", true);
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
      list.removeAttribute("aria-busy");
      busy = false;
      noticeFocusTarget = focusTarget;
      restoreFocus ||= document.activeElement === submitter || document.activeElement === document.body;
      if (restoreFocus && focusTarget?.isConnected) focusTarget.focus({ preventScroll: true });
      resumeNotice();
    }
  }
})();
