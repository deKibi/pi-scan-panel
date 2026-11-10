// tests/test_scan_previews.js

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../pi_scan_panel/static/scan-previews.js"), "utf8"
);

function setup(tops) {
  let onLoad;
  let observer;
  let onUpdate;
  const requests = [];
  const images = tops.map((top, index) => {
    const listeners = {};
    const classes = new Set();
    const attributes = {};
    const preview = {
      tagName: index === 0 ? "A" : "DIV",
      classList: { add: (name) => classes.add(name) },
      setAttribute: (name, value) => { attributes[name] = value; },
    };
    return {
      isConnected: true,
      top,
      alt: `scan-${index}`,
      dataset: { previewSrc: `/previews/scan-${index}.${index % 2 ? "png" : "pdf"}` },
      getBoundingClientRect() { return { top: this.top, bottom: this.top + 120 }; },
      closest: () => preview,
      addEventListener: (name, callback) => { listeners[name] = callback; },
      finish: (name) => { const callback = listeners[name]; delete listeners[name]; callback(); },
      classes,
      attributes,
      set src(value) { requests.push(value); },
    };
  });
  vm.runInNewContext(source, {
    window: {
      innerHeight: 800,
      addEventListener: (name, callback) => {
        assert.equal(name, "load");
        onLoad = callback;
      },
    },
    document: {
      querySelectorAll: () => images.filter((image) => image.isConnected),
      addEventListener: (name, callback) => {
        assert.equal(name, "scan-previews:update");
        onUpdate = callback;
      },
    },
    IntersectionObserver: class {
      constructor(callback, options) {
        this.callback = callback;
        this.options = options;
        this.observed = new Set();
        observer = this;
      }
      observe(image) { this.observed.add(image); }
      unobserve(image) { this.observed.delete(image); }
    },
  });
  return {
    images,
    requests,
    load() { onLoad(); },
    update() { onUpdate(); },
    intersect(entries = images.map((target) => ({ target, isIntersecting: true }))) {
      observer.callback(entries);
    },
    get observer() { return observer; },
  };
}

test("PDF and image requests start only after window load and intersection", () => {
  const page = setup([0, 150]);
  assert.equal(page.observer, undefined);
  assert.equal(page.requests.length, 0);
  page.load();
  assert.equal(page.requests.length, 0);
  assert.equal(page.observer.options.rootMargin, "200px 0px");
  page.intersect();
  assert.equal(page.requests.length, 2);
});

test("one shared queue permits at most two requests, then advances on completion", () => {
  const page = setup([0, 150, 300, 450]);
  page.load();
  page.intersect();
  assert.equal(page.requests.length, 2);
  page.images[0].finish("load");
  assert.equal(page.requests.length, 3);
  assert.ok(page.images[0].classes.has("is-loaded"));
  page.images[1].finish("error");
  assert.equal(page.requests.length, 4);
  assert.ok(page.images[1].classes.has("is-error"));
  assert.match(page.images[1].attributes["aria-label"], /Прев’ю недоступне/);
  page.images[2].finish("load");
  page.images[3].finish("load");
  assert.equal(page.requests.length, 4);
});

test("visible previews precede nearby previews; distant previews are not fetched", () => {
  const page = setup([850, 2000, 100, 250]);
  page.load();
  page.intersect();
  assert.deepEqual(page.requests, [
    page.images[2].dataset.previewSrc, page.images[3].dataset.previewSrc,
  ]);
  assert.equal(page.images[2].fetchPriority, "high");
  page.images[2].finish("load");
  assert.equal(page.requests[2], page.images[0].dataset.previewSrc);
  assert.equal(page.images[0].fetchPriority, "low");
  assert.equal(page.requests.length, 3);
});

test("scrolling away removes a queued preview and errors do not trigger retries", () => {
  const page = setup([0, 150, 300]);
  page.load();
  page.intersect();
  page.images[2].top = 2500;
  page.intersect([{ target: page.images[2], isIntersecting: false }]);
  page.images[0].finish("error");
  page.images[1].finish("load");
  assert.equal(page.requests.length, 2);
  assert.match(page.images[0].attributes["aria-label"], /Відкрити оригінал/);
});

test("new previews join the shared queue and detached queued images are discarded", () => {
  const page = setup([0, 150, 300, 450]);
  page.load();
  page.intersect();
  const removed = page.images[2];
  removed.isConnected = false;
  const added = {
    ...removed, isConnected: true,
    dataset: { previewSrc: "/previews/new.png?v=2" },
    set src(value) { page.requests.push(value); },
  };
  page.images.push(added);
  page.update();
  assert.ok(!page.observer.observed.has(removed));
  assert.ok(page.observer.observed.has(added));
  page.intersect([{ target: added, isIntersecting: true }]);
  assert.equal(page.requests.length, 2);
  page.images[0].finish("load");
  assert.equal(page.requests[2], added.dataset.previewSrc);
  assert.ok(!page.requests.includes(removed.dataset.previewSrc));
  page.update();
  assert.ok(!page.observer.observed.has(page.images[0]));
});
