// tests/test_scan_actions.js

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../pi_scan_panel/static/scan-actions.js"), "utf8");
const base = fs.readFileSync(path.join(__dirname, "../pi_scan_panel/templates/base.html"), "utf8");
const confirmation = base.match(/<script type="module">([\s\S]*?)<\/script>/)[1]
  .replace(/import \{ lockScroll \} from .*?;/, "");

function setup() {
  const listeners = [];
  const requests = [];
  const scrolls = [];
  const focusCalls = [];
  const changes = [];
  const pending = [];
  const elements = {};
  const timers = new Map();
  let now = 0;
  let timerId = 0;
  let rows;
  let nextRows;
  let response = { success: true, message: "Done" };
  let fetchResponse;

  function element() {
    const events = {};
    return {
      isConnected: true, disabled: false, hidden: true, dataset: {}, textContent: "",
      classList: { toggle() {}, remove() {} },
      closest: () => null,
      setAttribute() {}, removeAttribute() {},
      focus(options) { document.activeElement = this; focusCalls.push({ target: this, options }); },
      addEventListener(name, callback) { events[name] = callback; },
      contains(item) { return item === this; },
      emit(name, event = {}) {
        const result = events[name]?.(event);
        if (result?.then) pending.push(result);
      },
    };
  }

  function makeRow(id, top) {
    const row = { dataset: { fileId: id }, getBoundingClientRect: () => ({ top }) };
    const metadata = element();
    const preview = element();
    let image;
    function makeImage() {
      return {
        dataset: {}, removeAttribute() {}, closest: () => preview,
        cloneNode: makeImage,
        replaceWith(value) { image = value; },
      };
    }
    image = makeImage();
    row.forms = ["rotate", "print", "delete"].map((action) => {
      const button = element();
      const form = {
        action: `/${action}/${id}`, dataset: {}, button,
        matches: (selector) => selector === "form[data-confirm]" ? action === "delete" : true,
        closest: () => row,
        querySelector: () => button,
        requestSubmit: (submitter) => submit(form, submitter),
      };
      if (action === "delete") form.dataset = {
        confirm: "Delete?", confirmTitle: "Delete", confirmAction: "Delete",
      };
      return form;
    });
    row.querySelector = (selector) => {
      if (selector === ".scan-meta > span") return metadata;
      if (selector === "img[data-preview-src]") return image;
      return row.forms[0].button;
    };
    return row;
  }

  const list = Object.assign(element(), {
    contains: (item) => rows.some((row) => row.forms.some((form) => form === item || form.button === item)),
    querySelectorAll: (selector) => selector === ".scan-item" ? rows : rows.flatMap((row) => row.forms.map((form) => form.button)),
  });
  Object.defineProperty(list, "innerHTML", {
    set(value) {
      assert.equal(value, "updated-list");
      rows.forEach((row) => row.forms.forEach((form) => { form.button.isConnected = false; }));
      rows = nextRows;
    },
  });
  elements["#file-list"] = list;
  for (const id of ["action-notice", "action-notice-text", "action-login", "action-revert", "action-close", "last-scan-actions", "file-list-heading",
                    "confirm-dialog", "confirm-cancel", "confirm-accept", "confirm-title", "confirm-message"]) {
    elements[`#${id}`] = element();
  }
  elements["#action-notice"].contains = (item) => ["action-notice", "action-notice-text", "action-login", "action-revert", "action-close"]
    .some((id) => elements[`#${id}`] === item);
  const dialog = elements["#confirm-dialog"];
  dialog.open = false;
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; dialog.emit("close"); };
  const document = {
    body: element(), activeElement: null, hidden: false,
    querySelector: (selector) => elements[selector],
    addEventListener: (name, callback, capture = false) => listeners.push({ name, callback, capture }),
    dispatchEvent: (event) => changes.push(event.type),
  };
  document.activeElement = document.body;
  rows = [makeRow("first.png", -150), makeRow("second.png", 100), makeRow("third.png", 350)];

  function submit(form, submitter = form.button) {
    const event = {
      target: form, submitter, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
    };
    for (const listener of listeners.filter((item) => item.name === "submit").sort((a, b) => Number(b.capture) - Number(a.capture))) {
      const result = listener.callback(event);
      if (result?.then) pending.push(result);
    }
    assert.equal(event.defaultPrevented, true, "native navigation must be prevented");
  }

  vm.runInNewContext(source + "\n" + confirmation, {
    document, Event: class { constructor(type) { this.type = type; } },
    FormData: class {
      constructor(form) { this.form = form; this.fields = {}; }
      append(name, value) { this.fields[name] = value; }
    },
    performance: { now: () => now }, queueMicrotask,
    window: { scrollX: 0, scrollY: 750, scrollTo: (value) => scrolls.push(value) },
    history: { state: null, replaceState: (...args) => changes.push(args) },
    lockScroll: () => () => {},
    setTimeout(callback, delay) {
      const id = ++timerId;
      timers.set(id, { callback, deadline: now + delay });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (fetchResponse) return fetchResponse();
      return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => response };
    },
  });
  return {
    requests, scrolls, focusCalls, changes, elements, document, makeRow,
    get rows() { return rows; },
    get timerCount() { return timers.size; },
    submit,
    emitDocument(name) { listeners.filter((item) => item.name === name).forEach((item) => item.callback({})); },
    async flush() { await Promise.all(pending.splice(0)); },
    respond(value) { response = value; },
    fetchWith(callback) { fetchResponse = callback; },
    replaceWith(value) { nextRows = value; },
    advanceTime(milliseconds) {
      const end = now + milliseconds;
      while (timers.size) {
        const [id, timer] = [...timers].sort((a, b) => a[1].deadline - b[1].deadline)[0];
        if (timer.deadline > end) break;
        now = timer.deadline;
        timers.delete(id);
        timer.callback();
      }
      now = end;
    },
  };
}

test("rotation updates only its row, keeps scroll position and supports repeated submissions", async () => {
  const page = setup();
  const row = page.rows[1];
  const form = row.forms[0];
  page.respond({ success: true, message: "Rotated", file: { id: "second.png", metadata: "new size", preview_url: "/previews/second.png?v=2" } });
  for (let count = 1; count <= 2; count += 1) {
    page.document.activeElement = form.button;
    page.submit(form);
    assert.equal(form.button.disabled, true);
    await page.flush();
    assert.equal(page.requests.length, count);
    assert.equal(page.rows[1], row);
    assert.equal(row.querySelector(".scan-meta > span").textContent, "new size");
    assert.equal(row.querySelector("img[data-preview-src]").dataset.previewSrc, "/previews/second.png?v=2");
    assert.equal(page.scrolls.at(-1).top, 750);
    assert.equal(form.button.disabled, false);
    assert.equal(page.focusCalls.at(-1).options.preventScroll, true);
  }
  assert.equal(page.requests[0].options.headers.Accept, "application/json");
  assert.equal(page.requests[0].options.method, "POST");
  assert.ok(page.changes.includes("scan-previews:update"));
});

test("cancel and Escape do not send a request; confirmation sends exactly one", async () => {
  const page = setup();
  const form = page.rows[1].forms[2];
  page.submit(form);
  assert.equal(page.elements["#confirm-dialog"].open, true);
  page.elements["#confirm-cancel"].emit("click");
  await page.flush();
  assert.equal(page.requests.length, 0);
  assert.equal(form.button.disabled, false);
  page.submit(form);
  page.elements["#confirm-dialog"].emit("cancel", { preventDefault() {} });
  await page.flush();
  assert.equal(page.requests.length, 0);
  page.submit(form);
  page.elements["#confirm-accept"].emit("click");
  await page.flush();
  assert.equal(page.requests.length, 1);
  assert.equal(page.elements["#confirm-dialog"].open, false);
  assert.equal(form.button.disabled, false);
});

test("duplicate submissions are ignored while a request is pending", async () => {
  const page = setup();
  let finish;
  page.fetchWith(() => new Promise((resolve) => { finish = resolve; }));
  const form = page.rows[1].forms[1];
  page.submit(form);
  page.submit(form);
  assert.equal(page.requests.length, 1);
  finish({ ok: true, headers: { get: () => "application/json" }, json: async () => ({ success: true, message: "Printed" }) });
  await page.flush();
  assert.ok(page.rows.every((row) => row.forms.every((item) => !item.button.disabled)));
  assert.equal(page.elements["#action-notice-text"].textContent, "Printed");
});

test("list replacement preserves an existing row's viewport offset and moves focus without scrolling", async () => {
  const page = setup();
  const form = page.rows[1].forms[2];
  const first = page.makeRow("first.png", -200);
  const third = page.makeRow("third.png", 50);
  page.replaceWith([first, third]);
  page.respond({ success: true, message: "Deleted", list_html: "updated-list", page: 1, per_page: 10, url: "/?page=1&per_page=10", last_scan_html: "" });
  page.submit(form);
  page.elements["#confirm-accept"].emit("click");
  await page.flush();
  assert.equal(page.scrolls[0].top, 700);
  assert.equal(page.focusCalls.at(-1).target, third.forms[0].button);
  assert.equal(page.focusCalls.at(-1).options.preventScroll, true);
  assert.equal(page.elements["#file-list"].dataset.page, 1);
  assert.ok(page.changes.some((change) => Array.isArray(change) && change[2] === "/?page=1&per_page=10"));
});

test("an empty list focuses its heading and retains the requested scroll position", async () => {
  const page = setup();
  page.replaceWith([]);
  page.respond({ success: true, message: "Empty", list_html: "updated-list", page: 1, per_page: 20, url: "/trash?page=1&per_page=20" });
  page.submit(page.rows[1].forms[2]);
  page.elements["#confirm-accept"].emit("click");
  await page.flush();
  assert.equal(page.scrolls[0].top, 750);
  assert.equal(page.focusCalls.at(-1).target, page.elements["#file-list-heading"]);
});

test("server and network failures unlock buttons without retrying or moving the page", async () => {
  const page = setup();
  const form = page.rows[1].forms[1];
  page.respond({ success: false, message: "Printer busy" });
  page.submit(form);
  await page.flush();
  assert.equal(page.elements["#action-notice-text"].textContent, "Printer busy");
  page.fetchWith(() => { throw new Error("offline"); });
  page.submit(form);
  await page.flush();
  assert.equal(page.requests.length, 2);
  assert.equal(page.scrolls.length, 0);
  assert.equal(form.button.disabled, false);
  assert.match(page.elements["#action-notice-text"].textContent, /Вона могла виконатися/);
});

test("expired sessions show a login link and restore button availability", async () => {
  const page = setup();
  page.fetchWith(() => ({ status: 401 }));
  const form = page.rows[1].forms[1];
  page.submit(form);
  await page.flush();
  assert.equal(page.elements["#action-login"].hidden, false);
  assert.equal(form.button.disabled, false);
  assert.equal(page.scrolls.length, 0);
});

test("success notices hide after six seconds without moving scroll or focus", async () => {
  const page = setup();
  page.submit(page.rows[1].forms[1]);
  await page.flush();
  const notice = page.elements["#action-notice"];
  const scrollCount = page.scrolls.length;
  const focusCount = page.focusCalls.length;
  const active = page.document.activeElement;
  page.advanceTime(5999);
  assert.equal(notice.hidden, false);
  page.advanceTime(1);
  assert.equal(notice.hidden, true);
  assert.equal(page.scrolls.length, scrollCount);
  assert.equal(page.focusCalls.length, focusCount);
  assert.equal(page.document.activeElement, active);
});

test("server, network and session errors remain visible for ten seconds", async () => {
  for (const kind of ["server", "network", "session"]) {
    const page = setup();
    if (kind === "server") page.respond({ success: false, message: "Print failed" });
    if (kind === "network") page.fetchWith(() => { throw new Error("offline"); });
    if (kind === "session") page.fetchWith(() => ({ status: 401 }));
    page.submit(page.rows[1].forms[1]);
    await page.flush();
    page.advanceTime(9999);
    assert.equal(page.elements["#action-notice"].hidden, false, kind);
    page.advanceTime(1);
    assert.equal(page.elements["#action-notice"].hidden, true, kind);
  }
});

test("pending actions cancel old timers and results receive their full display time", async () => {
  const page = setup();
  const form = page.rows[1].forms[1];
  page.submit(form);
  await page.flush();
  page.advanceTime(5000);
  let finish;
  page.fetchWith(() => new Promise((resolve) => { finish = resolve; }));
  page.submit(form);
  page.advanceTime(30000);
  assert.equal(page.elements["#action-notice"].hidden, false);
  assert.equal(page.elements["#action-notice-text"].textContent, "Виконуємо дію…");
  finish({ ok: true, headers: { get: () => "application/json" }, json: async () => ({ success: true, message: "Printed" }) });
  await page.flush();
  page.advanceTime(5999);
  assert.equal(page.elements["#action-notice"].hidden, false);
  page.advanceTime(1);
  assert.equal(page.elements["#action-notice"].hidden, true);
});

test("a newer error notice is not hidden by a previous success timer", async () => {
  const page = setup();
  const form = page.rows[1].forms[1];
  page.submit(form);
  await page.flush();
  page.advanceTime(5000);
  page.respond({ success: false, message: "Printer busy" });
  page.submit(form);
  await page.flush();
  page.advanceTime(1000);
  assert.equal(page.elements["#action-notice"].hidden, false);
  assert.equal(page.elements["#action-notice-text"].textContent, "Printer busy");
  page.advanceTime(8999);
  assert.equal(page.elements["#action-notice"].hidden, false);
  page.advanceTime(1);
  assert.equal(page.elements["#action-notice"].hidden, true);
});

test("only the close button dismisses a notice; clicking its text leaves it available", async () => {
  for (const success of [true, false]) {
    const page = setup();
    page.respond({ success, message: "Result" });
    page.submit(page.rows[1].forms[1]);
    await page.flush();
    const notice = page.elements["#action-notice"];
    const scrollCount = page.scrolls.length;
    const focusCount = page.focusCalls.length;
    const active = page.document.activeElement;
    assert.equal(notice.hidden, false);
    assert.equal(page.timerCount, 1);
    notice.emit("click", { target: success ? notice : page.elements["#action-notice-text"] });
    assert.equal(notice.hidden, false);
    assert.equal(page.timerCount, 1);
    page.elements["#action-close"].emit("click");
    assert.equal(notice.hidden, true);
    assert.equal(page.timerCount, 0);
    page.advanceTime(10000);
    assert.equal(page.scrolls.length, scrollCount);
    assert.equal(page.focusCalls.length, focusCount);
    assert.equal(page.document.activeElement, active);
  }
});

test("clicking the login link leaves the notice and native link behavior intact", async () => {
  const page = setup();
  page.fetchWith(() => ({ status: 401 }));
  page.submit(page.rows[1].forms[1]);
  await page.flush();
  const notice = page.elements["#action-notice"];
  const link = page.elements["#action-login"];
  link.closest = (selector) => selector === "a" ? link : null;
  notice.emit("click", {
    target: link,
    preventDefault() { assert.fail("link navigation must not be prevented"); },
    stopPropagation() { assert.fail("link clicks must propagate normally"); },
  });
  assert.equal(link.hidden, false);
  assert.equal(notice.hidden, false);
  assert.equal(page.timerCount, 1);
});

test("dismissing a pending notice does not cancel the action or hide its result", async () => {
  const page = setup();
  let finish;
  page.fetchWith(() => new Promise((resolve) => { finish = resolve; }));
  const form = page.rows[1].forms[1];
  page.submit(form);
  const notice = page.elements["#action-notice"];
  page.elements["#action-close"].emit("click");
  assert.equal(notice.hidden, true);
  assert.equal(form.button.disabled, true);
  assert.equal(page.requests.length, 1);
  finish({ ok: true, headers: { get: () => "application/json" }, json: async () => ({ success: true, message: "Printed" }) });
  await page.flush();
  assert.equal(notice.hidden, false);
  assert.equal(page.elements["#action-notice-text"].textContent, "Printed");
  assert.equal(form.button.disabled, false);
  page.advanceTime(5999);
  assert.equal(notice.hidden, false);
  page.advanceTime(1);
  assert.equal(notice.hidden, true);
});

test("a new notice receives its full display time after dismissing the previous one", async () => {
  const page = setup();
  const form = page.rows[1].forms[1];
  const notice = page.elements["#action-notice"];
  page.submit(form);
  await page.flush();
  page.advanceTime(5000);
  page.elements["#action-close"].emit("click");
  page.submit(form);
  await page.flush();
  page.advanceTime(1000);
  assert.equal(notice.hidden, false);
  page.advanceTime(4999);
  assert.equal(notice.hidden, false);
  page.advanceTime(1);
  assert.equal(notice.hidden, true);
});

test("rotation Revert lasts ten seconds and sends the matching version exactly once", async () => {
  const page = setup();
  const row = page.rows[1];
  const revert = {
    url: "/rotate/second.png", file_id: "second.png",
    fields: { direction: "counterclockwise", expected_version: "rotated-version" },
  };
  page.respond({ success: true, message: "Rotated", revert });
  page.submit(row.forms[0]);
  await page.flush();
  const button = page.elements["#action-revert"];
  assert.equal(button.hidden, false);
  page.advanceTime(9999);
  assert.equal(page.elements["#action-notice"].hidden, false);
  page.respond({ success: true, message: "Дію скасовано.", file: { id: "second.png", metadata: "original orientation", preview_url: "/previews/second.png?v=3" } });
  page.document.activeElement = button;
  button.emit("click");
  button.emit("click");
  await page.flush();
  assert.equal(page.requests.length, 2);
  assert.equal(page.requests[1].url, revert.url);
  assert.deepEqual(page.requests[1].options.body.fields, revert.fields);
  assert.equal(row.querySelector("img[data-preview-src]").dataset.previewSrc, "/previews/second.png?v=3");
  assert.equal(page.scrolls.at(-1).top, 750);
  assert.equal(page.document.activeElement, row.forms[0].button);
  assert.equal(button.hidden, true);
  assert.equal(button.disabled, false);
  page.advanceTime(6000);
  assert.equal(page.elements["#action-notice"].hidden, true);
});

test("Revert expires and cannot send a request after its notice is closed or replaced", async () => {
  for (const dismissal of ["timeout", "close", "next-action"]) {
    const page = setup();
    page.respond({ success: true, message: "Rotated", revert: { url: "/rotate/second.png", fields: {}, file_id: "second.png" } });
    page.submit(page.rows[1].forms[0]);
    await page.flush();
    if (dismissal === "timeout") page.advanceTime(10000);
    if (dismissal === "close") page.elements["#action-close"].emit("click");
    if (dismissal === "next-action") {
      page.respond({ success: false, message: "Print failed" });
      page.submit(page.rows[1].forms[1]);
      await page.flush();
    }
    const requestCount = page.requests.length;
    assert.equal(page.elements["#action-revert"].hidden, true);
    page.elements["#action-revert"].emit("click");
    await page.flush();
    assert.equal(page.requests.length, requestCount);
  }
});

test("cancelling delete confirmation preserves the previous Revert", async () => {
  const page = setup();
  page.respond({ success: true, message: "Rotated", revert: { url: "/rotate/second.png", fields: {}, file_id: "second.png" } });
  page.submit(page.rows[1].forms[0]);
  await page.flush();
  page.submit(page.rows[1].forms[2]);
  page.elements["#confirm-cancel"].emit("click");
  await page.flush();
  assert.equal(page.requests.length, 1);
  assert.equal(page.elements["#action-revert"].hidden, false);
});

test("delete Revert updates the main list without navigating to trash", async () => {
  const page = setup();
  const first = page.makeRow("first.png", -150);
  const third = page.makeRow("third.png", 100);
  page.replaceWith([first, third]);
  const revert = { url: "/trash/entry/restore?return_to=scans&page=1&per_page=10", fields: {}, file_id: "second.png" };
  page.respond({ success: true, message: "Deleted", revert, list_html: "updated-list", page: 1, per_page: 10, url: "/?page=1&per_page=10" });
  page.submit(page.rows[1].forms[2]);
  page.elements["#confirm-accept"].emit("click");
  await page.flush();
  const second = page.makeRow("second.png", 100);
  const restoredThird = page.makeRow("third.png", 350);
  page.replaceWith([first, second, restoredThird]);
  page.respond({ success: true, message: "Дію скасовано.", list_html: "updated-list", page: 1, per_page: 10, url: "/?page=1&per_page=10" });
  page.document.activeElement = page.elements["#action-revert"];
  page.elements["#action-revert"].emit("click");
  await page.flush();
  assert.equal(page.requests[1].url, revert.url);
  assert.equal(page.rows[1], second);
  assert.equal(page.elements["#action-revert"].hidden, true);
  assert.ok(page.changes.filter(Array.isArray).every((change) => change[2].startsWith("/?")));
});

test("notice timeout pauses on hover, keyboard focus and hidden tabs with its remaining time", async () => {
  for (const pause of ["hover", "focus", "background"]) {
    const page = setup();
    page.respond({ success: true, message: "Rotated", revert: { url: "/rotate/second.png", fields: {}, file_id: "second.png" } });
    page.submit(page.rows[1].forms[0]);
    await page.flush();
    const notice = page.elements["#action-notice"];
    page.advanceTime(3000);
    if (pause === "hover") notice.emit("pointerenter", { pointerType: "mouse" });
    if (pause === "focus") {
      page.document.activeElement = page.elements["#action-revert"];
      notice.emit("focusin");
    }
    if (pause === "background") {
      page.document.hidden = true;
      page.emitDocument("visibilitychange");
    }
    page.advanceTime(30000);
    assert.equal(notice.hidden, false, pause);
    assert.equal(page.timerCount, 0, pause);
    if (pause === "hover") notice.emit("pointerleave");
    if (pause === "focus") {
      page.document.activeElement = page.rows[1].forms[0].button;
      notice.emit("focusout", { relatedTarget: page.document.activeElement });
      await Promise.resolve();
    }
    if (pause === "background") {
      page.document.hidden = false;
      page.emitDocument("visibilitychange");
    }
    page.advanceTime(6999);
    assert.equal(notice.hidden, false, pause);
    page.advanceTime(1);
    assert.equal(notice.hidden, true, pause);
  }
});

test("touch does not leave the notice timer paused after lifting the finger", async () => {
  const page = setup();
  page.respond({ success: true, message: "Rotated", revert: { url: "/rotate/second.png", fields: {}, file_id: "second.png" } });
  page.submit(page.rows[1].forms[0]);
  await page.flush();
  const notice = page.elements["#action-notice"];
  page.advanceTime(3000);
  notice.emit("pointerenter", { pointerType: "touch" });
  notice.emit("pointerdown");
  page.advanceTime(20000);
  notice.emit("pointerup");
  page.advanceTime(7000);
  assert.equal(notice.hidden, true);
});

test("Revert failures and expired sessions unlock controls without offering another Revert", async () => {
  for (const kind of ["server", "network", "session"]) {
    const page = setup();
    page.respond({ success: true, message: "Rotated", revert: { url: "/rotate/second.png", fields: {}, file_id: "second.png" } });
    page.submit(page.rows[1].forms[0]);
    await page.flush();
    if (kind === "server") page.respond({ success: false, message: "File changed" });
    if (kind === "network") page.fetchWith(() => { throw new Error("offline"); });
    if (kind === "session") page.fetchWith(() => ({ status: 401 }));
    page.elements["#action-revert"].emit("click");
    await page.flush();
    assert.equal(page.requests.length, 2, kind);
    assert.equal(page.elements["#action-revert"].hidden, true, kind);
    assert.equal(page.elements["#action-revert"].disabled, false, kind);
    assert.ok(page.rows.every((row) => row.forms.every((form) => !form.button.disabled)), kind);
    assert.equal(page.elements["#action-login"].hidden, kind !== "session", kind);
  }
});
