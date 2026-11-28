// HFP card logic (#1342 T02): `node --test`, no dependencies.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const SRC = path.join(
  __dirname, "..", "..", "..", "openbb_agents", "hermes_integration", "web", "extension", "hfp.js",
);
const H = require(SRC);
const PLAN = "plan_" + "a".repeat(32);
const RUN = "b".repeat(32);

function fakeFetch(responses) {
  const calls = [];
  const fn = (url, init) => {
    calls.push({ url, init });
    const next = responses.length > 1 ? responses.shift() : responses[0];
    if (next instanceof Error) { return Promise.reject(next); }
    return Promise.resolve({
      status: next.status,
      json: () => (next.raw ? Promise.reject(new Error("not json")) : Promise.resolve(next.body)),
    });
  };
  fn.calls = calls;
  return fn;
}

test("proxy 403/502/503 map to consent_required, sidecar_unreachable, token_unprovisioned", async () => {
  for (const [status, code] of [[403, "consent_required"], [502, "sidecar_unreachable"], [503, "token_unprovisioned"]]) {
    const client = H.createClient(fakeFetch([{ status, raw: true }]));
    assert.deepEqual(await client.getPlan(PLAN), { ok: false, code, status });
  }
  const down = H.createClient(fakeFetch([new Error("ECONNREFUSED 127.0.0.1")]));
  assert.equal((await down.getRun(RUN)).code, "sidecar_unreachable");
});

test("known sidecar codes pass through; raw server text never does", async () => {
  const known = H.createClient(fakeFetch([{ status: 503, body: { error: "plan_store_unavailable" } }]));
  assert.equal((await known.getPlan(PLAN)).code, "plan_store_unavailable");
  const raw = H.createClient(fakeFetch([{ status: 500, body: { error: "Traceback: secret path C:/x", detail: "boom" } }]));
  const res = await raw.getPlan(PLAN);
  assert.equal(res.code, "request_failed");
  assert.ok(!JSON.stringify(res).includes("Traceback"));
});

test("double click sends one approval request", async () => {
  const fetch = fakeFetch([{ status: 200, body: { result: "approved", card: { state: "approved" } } }]);
  const client = H.createClient(fetch);
  const card = { plan_id: PLAN, plan_sha256: "c".repeat(64), approval_nonce: "d".repeat(64) };
  const [a, b] = await Promise.all([client.approve(card), client.approve(card)]);
  assert.equal(fetch.calls.length, 1);
  assert.equal(a, b);
  assert.equal(fetch.calls[0].url, H.PROXY_PREFIX + "/plans/" + PLAN + "/approve");
  assert.equal(fetch.calls[0].init.method, "POST");
  assert.equal(fetch.calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(fetch.calls[0].init.body), {
    plan_sha256: card.plan_sha256, approval_nonce: card.approval_nonce,
  });
});

test("ids are validated before any request", async () => {
  const fetch = fakeFetch([{ status: 200, body: {} }]);
  const client = H.createClient(fetch);
  assert.equal((await client.getPlan("../v1/session")).code, "plan_not_found");
  assert.equal((await client.getRun("x")).code, "run_unavailable");
  assert.equal((await client.approve({ plan_id: PLAN })).code, "bad_nonce");
  assert.equal(fetch.calls.length, 0);
  assert.throws(() => H.proxyPath("//evil"), /invalid_path/);
});

test("run polling stops at a terminal outcome and never posts", async () => {
  const fetch = fakeFetch([
    { status: 200, body: { outcome: "running" } },
    { status: 200, body: { outcome: "partial" } },
  ]);
  const seen = [];
  let stop;
  await new Promise((resolve) => {
    stop = H.pollRun(H.createClient(fetch), RUN, (res) => {
      seen.push(res.data.outcome);
      if (res.data.outcome === "partial") { setTimeout(resolve, 20); }
    }, { setTimeout: (f) => setTimeout(f, 1) });
  });
  stop();
  assert.deepEqual(seen, ["running", "partial"]);
  assert.equal(fetch.calls.length, 2);
  assert.ok(fetch.calls.every((c) => c.init.method === "GET"));
});

test("markers find plan and run ids only in their exact grammar", () => {
  const text = `see [[hfp:plan:${PLAN}]] and [[hfp:run:${RUN}]] not [[hfp:run:plan_${RUN}]]`;
  assert.deepEqual(H.findMarkers(text), [{ kind: "plan", id: PLAN }, { kind: "run", id: RUN }]);
});

test("extension never starts a chat turn or clicks send", () => {
  const src = fs.readFileSync(SRC, "utf8");
  for (const banned of ["/api/chat", "chat/start", ".click()", "submit()", "innerHTML", "eval("]) {
    assert.ok(!src.includes(banned), banned);
  }
});

test("starter pre-fills the composer and does not send", () => {
  const listeners = {};
  const made = [];
  const doc = {
    defaultView: { Event: function (type) { this.type = type; } },
    createElement: (tag) => {
      const node = {
        tag, children: [], attrs: {}, textContent: "",
        appendChild(c) { this.children.push(c); },
        setAttribute(k, v) { this.attrs[k] = v; },
        addEventListener(t, f) { listeners[t] = f; },
      };
      made.push(node);
      return node;
    },
  };
  const target = doc.createElement("div");
  const events = [];
  const composer = { value: "", dispatchEvent: (e) => events.push(e.type), focus() {} };
  H.renderWorkflows(doc, target, { workflows: [{ workflow_id: "synthetic.basket_xray", prompt: "Preview it" }] }, composer);
  listeners.click();
  assert.equal(composer.value, "Preview it");
  assert.deepEqual(events, ["input"]);
});

async function flush() {
  for (let i = 0; i < 5; i += 1) { await new Promise((r) => setImmediate(r)); }
}

function fakeDoc() {
  return {
    createElement: (tag) => ({
      tag, children: [], attrs: {}, textContent: "",
      appendChild(c) { this.children.push(c); },
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener() {},
    }),
  };
}

function fakeStorage(initial) {
  const data = { ...initial };
  return {
    data,
    get: (k, d) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : d),
    set: (k, v) => { data[k] = v; return true; },
    remove: (k) => { delete data[k]; return true; },
  };
}

test("poll backoff 2 s -> 10 s, resets on change and after reconnect, stops at terminal", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const running = { status: 200, body: { outcome: "running" } };
  const fetch = fakeFetch([
    running, running, running, running, running,
    new Error("ECONNREFUSED 127.0.0.1"), new Error("ECONNREFUSED 127.0.0.1"),
    running,
    { status: 200, body: { outcome: "succeeded" } },
  ]);
  const seen = [];
  H.pollRun(H.createClient(fetch), RUN, (res) => seen.push(res.ok ? res.data.outcome : res.code));
  await flush();
  assert.equal(fetch.calls.length, 1);
  // unchanged: 2, 4, 8, 10, 10 s; unreachable resets to 2, then 4; reconnect resets to 2.
  for (const ms of [2000, 4000, 8000, 10000, 10000, 2000, 4000, 2000]) {
    const before = fetch.calls.length;
    t.mock.timers.tick(ms - 1);
    await flush();
    assert.equal(fetch.calls.length, before, `no request before ${ms} ms`);
    t.mock.timers.tick(1);
    await flush();
    assert.equal(fetch.calls.length, before + 1, `request after ${ms} ms`);
  }
  assert.deepEqual(seen.slice(-4), ["sidecar_unreachable", "sidecar_unreachable", "running", "succeeded"]);
  t.mock.timers.tick(60000);
  await flush();
  assert.equal(fetch.calls.length, 9, "polling stopped at the terminal outcome");
  assert.ok(fetch.calls.every((c) => c.init.method === "GET"));
});

test("run_unavailable stops polling", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const fetch = fakeFetch([{ status: 404, body: { error: "run_unavailable" } }]);
  H.pollRun(H.createClient(fetch), RUN, () => {});
  await flush();
  t.mock.timers.tick(60000);
  await flush();
  assert.equal(fetch.calls.length, 1);
});

test("test_resume_polls_existing_run_never_posts", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const storage = fakeStorage({ last_run_id: RUN });
  const fetch = fakeFetch([
    { status: 200, body: { run_id: RUN, outcome: "waiting_job", state: "unavailable", code: "worker_unavailable" } },
    { status: 200, body: { run_id: RUN, outcome: "succeeded", state: "available" } },
  ]);
  const doc = fakeDoc();
  const target = doc.createElement("div");
  const stop = H.resumeRun(doc, target, H.createClient(fetch), { storage });
  assert.equal(typeof stop, "function");
  await flush();
  assert.equal(target.children[0].attrs["data-hfp-code"], "worker_unavailable");
  t.mock.timers.tick(2000);
  await flush();
  const card = target.children[target.children.length - 1];
  assert.equal(card.attrs["data-hfp-run"], RUN);
  assert.equal(card.attrs["data-hfp-outcome"], "succeeded");
  assert.deepEqual(fetch.calls.map((c) => [c.init.method, c.url]), [
    ["GET", H.PROXY_PREFIX + "/runs/" + RUN], ["GET", H.PROXY_PREFIX + "/runs/" + RUN],
  ]);
  assert.equal(storage.data.last_run_id, undefined, "a terminal run is forgotten");
  const none = fakeFetch([{ status: 200, body: {} }]);
  assert.equal(H.resumeRun(doc, target, H.createClient(none), { storage }), null);
  assert.equal(H.resumeRun(doc, target, H.createClient(none), { storage: fakeStorage({ last_run_id: "../x" }) }), null);
  assert.equal(none.calls.length, 0);
});

test("a mounted run is remembered for resume until it is terminal", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const storage = fakeStorage({});
  const fetch = fakeFetch([{ status: 200, body: { run_id: RUN, outcome: "running" } }]);
  const doc = fakeDoc();
  const stop = H.mountRun(doc, doc.createElement("div"), H.createClient(fetch), RUN, { storage });
  await flush();
  stop();
  assert.equal(H.lastRun(storage), RUN);
});
