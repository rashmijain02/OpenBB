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
    }, { interval: 1, setTimeout: (f) => setTimeout(f, 1) });
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
