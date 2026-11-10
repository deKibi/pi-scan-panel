// tests/test_scan_actions.js

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/scan-actions.js"), "utf8");
const base = fs.readFileSync(path.join(__dirname, "../templates/base.html"), "utf8");
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
  let rows;
  let nextRows;
  let response = { success: true, message: "Done" };
  let fetchResponse;

  function element() {
    const events = {};
    return {
      isConnected: true, disabled: false, hidden: true, dataset: {}, textContent: "",
      classList: { toggle() {}, remove() {} },
      setAttribute() {}, removeAttribute() {},
      focus(options) { document.activeElement = this; focusCalls.push({ target: this, options }); },
      addEventListener(name, callback) { events[name] = callback; },
      emit(name, event = {}) { events[name]?.(event); },
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
  for (const id of ["action-notice", "action-notice-text", "action-login", "last-scan-actions", "file-list-heading",
                    "confirm-dialog", "confirm-cancel", "confirm-accept", "confirm-title", "confirm-message"]) {
    elements[`#${id}`] = element();
  }
  const dialog = elements["#confirm-dialog"];
  dialog.open = false;
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; dialog.emit("close"); };
  const document = {
    body: element(), activeElement: null,
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
    FormData: class { constructor(form) { this.form = form; } },
    window: { scrollX: 0, scrollY: 750, scrollTo: (value) => scrolls.push(value) },
    history: { state: null, replaceState: (...args) => changes.push(args) },
    lockScroll: () => () => {}, setTimeout,
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (fetchResponse) return fetchResponse();
      return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => response };
    },
  });
  return {
    requests, scrolls, focusCalls, changes, elements, document, makeRow,
    get rows() { return rows; },
    submit,
    async flush() { await Promise.all(pending.splice(0)); },
    respond(value) { response = value; },
    fetchWith(callback) { fetchResponse = callback; },
    replaceWith(value) { nextRows = value; },
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
