/* OpenBB financial planning extension for Hermes WebUI (#1342).
 *
 * UMD: Node's `require` gets the pure HfpCards logic for tests; in the browser the
 * module registers with `hermesExt` and mounts cards next to `[[hfp:plan:<id>]]` and
 * `[[hfp:run:<id>]]` markers. Every sidecar call goes through the same-origin WebUI
 * proxy path, never to the sidecar port. The extension never starts a chat turn: the
 * starter list only pre-fills the composer, and the user presses Send (W4). Paper
 * actions are approved in the terminal only (W3). Cards render with textContent and
 * show fixed codes, never raw server text.
 *
 * Reconnect (T03): a run card polls `GET /runs/<id>` with 2 s -> 10 s backoff, resets
 * to 2 s when the card changes (including recovery after `sidecar_unreachable`) and
 * stops at a terminal outcome or `run_unavailable`. The last open run id is kept in
 * the extension-owned storage, so a reloaded page observes the same run again; it
 * never re-sends a chat turn or starts anything.
 *
 * One card per id per page: a second marker of a plan or run already shown renders a
 * pointer and sends nothing. An approved plan card polls `GET /plans/<id>` with the
 * same backoff until the agent's start gives it a `run_id`, then mounts the run card.
 * A `bad_nonce` approval (another tab read the plan later) re-reads the plan for a
 * fresh nonce and enables Approve again.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.HfpCards = api;
    if (root.document) {
      api.autoMount(root);
    }
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var EXTENSION_ID = "openbb-hfp";
  var PROXY_PREFIX = "/api/extensions/" + EXTENSION_ID + "/sidecar";
  var PLAN_ID = /^plan_[0-9a-f]{32}$/;
  var RUN_ID = /^[0-9a-f]{32}$/;
  var MARKER = /\[\[hfp:(plan|run):([0-9a-z_]{32,37})\]\]/g;
  var TERMINAL = { succeeded: 1, failed: 1, cancelled: 1, partial: 1, blocked: 1 };
  // Codes a card may show; anything else maps from the HTTP status.
  var KNOWN = [
    "approved", "already_approved", "plan_not_found", "plan_expired", "plan_superseded",
    "bad_nonce", "plan_store_unavailable", "run_unavailable", "outcome_unavailable",
    "paper_approval_terminal_only", "consent_required", "sidecar_unreachable",
    "token_unprovisioned", "token_mismatch", "origin_mismatch", "request_failed",
    "worker_unavailable", "sidecar_timeout",
  ];
  var BY_STATUS = { 403: "consent_required", 502: "sidecar_unreachable", 503: "token_unprovisioned" };
  var POLL_MIN_MS = 2000;
  var POLL_MAX_MS = 10000;
  // Codes after which polling stops: the run does not exist for this session.
  var FINAL = { run_unavailable: 1 };
  var LAST_RUN = "last_run_id";

  function proxyPath(path) {
    if (typeof path !== "string" || path.charAt(0) !== "/" || path.indexOf("//") !== -1) {
      throw new Error("invalid_path");
    }
    return PROXY_PREFIX + path;
  }

  function codeFor(status, body) {
    var code = body && typeof body === "object" ? body.error : null;
    if (typeof code === "string" && KNOWN.indexOf(code) !== -1) {
      return code;
    }
    return BY_STATUS[status] || "request_failed";
  }

  function createClient(fetchImpl) {
    var inflight = {};
    function call(method, path, body) {
      var init = { method: method, credentials: "same-origin", headers: {} };
      if (body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
      return Promise.resolve()
        .then(function () { return fetchImpl(proxyPath(path), init); })
        .then(function (r) {
          return r.json().catch(function () { return null; }).then(function (data) {
            if (r.status >= 200 && r.status < 300 && data) {
              return { ok: true, data: data };
            }
            return { ok: false, code: codeFor(r.status, data), status: r.status };
          });
        }, function () { return { ok: false, code: "sidecar_unreachable", status: 0 }; });
    }
    return {
      getPlan: function (planId) {
        if (!PLAN_ID.test(planId)) { return Promise.resolve({ ok: false, code: "plan_not_found" }); }
        return call("GET", "/plans/" + planId);
      },
      getRun: function (runId) {
        if (!RUN_ID.test(runId)) { return Promise.resolve({ ok: false, code: "run_unavailable" }); }
        return call("GET", "/runs/" + runId);
      },
      getWorkflows: function () { return call("GET", "/workflows"); },
      // One request per plan while it is in flight: a double click sends once.
      // A settled request is forgotten, so a later Approve sends again.
      approve: function (card) {
        if (!card || !PLAN_ID.test(card.plan_id) || !card.approval_nonce) {
          return Promise.resolve({ ok: false, code: "bad_nonce" });
        }
        var key = card.plan_id;
        if (!inflight[key]) {
          inflight[key] = call("POST", "/plans/" + key + "/approve", {
            plan_sha256: card.plan_sha256,
            approval_nonce: card.approval_nonce,
          }).then(function (res) {
            delete inflight[key];
            return res;
          });
        }
        return inflight[key];
      },
    };
  }

  // Poll `read()` until `isDone(res)`; returns a stop function. Waits 2 s, then
  // doubles while `signature(res)` is unchanged, up to 10 s; any change (an outcome
  // step, a reconnect after `sidecar_unreachable`) resets it to 2 s.
  function poll(read, onRes, isDone, signature, opts) {
    var o = opts || {};
    var wait = o.setTimeout || setTimeout;
    var delay = 0;
    var last = null;
    var stopped = false;
    function tick() {
      if (stopped) { return; }
      read().then(function (res) {
        if (stopped) { return; }
        onRes(res);
        if (isDone(res)) {
          if (o.onTerminal) { o.onTerminal(res); }
          return;
        }
        var sig = signature(res);
        delay = sig === last ? Math.min(POLL_MAX_MS, delay * 2) : POLL_MIN_MS;
        last = sig;
        wait(tick, delay);
      });
    }
    tick();
    return function () { stopped = true; };
  }

  // Poll a run card until its outcome is terminal or the run is unavailable.
  function pollRun(client, runId, onCard, opts) {
    return poll(
      function () { return client.getRun(runId); },
      onCard,
      function (res) { return res.ok ? !!(res.data && TERMINAL[res.data.outcome]) : !!FINAL[res.code]; },
      function (res) { return res.ok ? "ok:" + res.data.outcome + ":" + (res.data.code || "") : "err:" + res.code; },
      opts
    );
  }

  // Poll an approved plan until it names its run or stops being approved (started,
  // expired, gone). A pending plan is never polled: each of its reads mints a new
  // nonce. Transport errors keep polling.
  var PLAN_FINAL = { plan_not_found: 1, plan_expired: 1, plan_superseded: 1 };
  function pollPlan(client, planId, onCard, opts) {
    return poll(
      function () { return client.getPlan(planId); },
      onCard,
      function (res) {
        return res.ok ? !!res.data.run_id || res.data.state !== "approved" : !!PLAN_FINAL[res.code];
      },
      function (res) { return res.ok ? "ok:" + res.data.state : "err:" + res.code; },
      opts
    );
  }

  // Extension-owned storage (hermesExt handle); every access is best effort.
  function lastRun(storage) {
    try {
      var id = storage ? storage.get(LAST_RUN, null) : null;
      return typeof id === "string" && RUN_ID.test(id) ? id : null;
    } catch (err) { return null; }
  }

  function rememberRun(storage, runId) {
    try { if (storage && RUN_ID.test(runId)) { storage.set(LAST_RUN, runId); } } catch (err) { /* no storage */ }
  }

  function forgetRun(storage, runId) {
    try {
      if (storage && storage.get(LAST_RUN, null) === runId) { storage.remove(LAST_RUN); }
    } catch (err) { /* no storage */ }
  }

  function el(doc, tag, cls, text) {
    var node = doc.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function row(doc, label, value) {
    var r = el(doc, "div", "hfp-row");
    r.appendChild(el(doc, "span", "hfp-label", label));
    r.appendChild(el(doc, "code", "hfp-value", value === null || value === undefined ? "-" : value));
    return r;
  }

  function renderError(doc, target, code) {
    target.textContent = "";
    var box = el(doc, "div", "hfp-card hfp-unavailable");
    box.setAttribute("data-hfp-code", code);
    box.appendChild(el(doc, "div", "hfp-code", code));
    target.appendChild(box);
  }

  function renderRun(doc, target, card) {
    target.textContent = "";
    var box = el(doc, "div", "hfp-card hfp-run");
    box.setAttribute("data-hfp-run", card.run_id);
    box.setAttribute("data-hfp-outcome", card.outcome || card.code || "");
    if (card.code) { box.setAttribute("data-hfp-code", card.code); }
    box.appendChild(row(doc, "run", card.run_id));
    box.appendChild(row(doc, "plan", card.plan_id));
    box.appendChild(row(doc, "outcome", card.outcome || card.code));
    if (card.code && card.outcome) { box.appendChild(row(doc, "state", card.code)); }
    (card.jobs || []).forEach(function (j) { box.appendChild(row(doc, "job " + j.job_id, j.status)); });
    (card.artifacts || []).forEach(function (a) {
      box.appendChild(row(doc, "artifact " + a.artifact_id, a.kind + " " + String(a.sha256).slice(0, 12)));
    });
    box.appendChild(el(doc, "div", "hfp-note", "paper_approval_terminal_only"));
    target.appendChild(box);
  }

  // A second marker of a card already on the page: a pointer, no request.
  function renderPointer(doc, target, id) {
    var box = el(doc, "div", "hfp-card hfp-pointer", "card_shown_above");
    box.setAttribute("data-hfp-ref", id);
    target.appendChild(box);
  }

  // Mount a polling run card; the run id is remembered until it is terminal.
  // A run already polled on this page (`opts.mounted`) gets a pointer and null.
  function mountRun(doc, target, client, runId, opts) {
    var o = opts || {};
    if (o.mounted) {
      if (o.mounted[runId]) {
        renderPointer(doc, target, runId);
        return null;
      }
      o.mounted[runId] = 1;
    }
    rememberRun(o.storage, runId);
    var poll = {};
    Object.keys(o).forEach(function (k) { poll[k] = o[k]; });
    poll.onTerminal = function (res) {
      forgetRun(o.storage, runId);
      if (o.onTerminal) { o.onTerminal(res); }
    };
    return pollRun(client, runId, function (res) {
      if (res.ok) { renderRun(doc, target, res.data); } else { renderError(doc, target, res.code); }
    }, poll);
  }

  // After a reload: observe the remembered run again (GET only); null if none.
  function resumeRun(doc, target, client, opts) {
    var runId = lastRun((opts || {}).storage);
    return runId ? mountRun(doc, target, client, runId, opts) : null;
  }

  function mountRunSlot(doc, box, client, runId, opts) {
    var runBox = el(doc, "div", "hfp-run-slot");
    box.appendChild(runBox);
    return mountRun(doc, runBox, client, runId, opts);
  }

  // After approval: wait (GET /plans/<id>) for the agent's start, then show the run.
  function watchPlan(doc, box, client, planId, opts) {
    var o = opts || {};
    return pollPlan(client, planId, function (res) {
      if (res.ok) {
        box.setAttribute("data-hfp-state", res.data.state);
        if (res.data.run_id) { mountRunSlot(doc, box, client, res.data.run_id, o); }
      }
    }, { setTimeout: o.setTimeout });
  }

  function renderPlan(doc, target, client, card, opts, notice) {
    target.textContent = "";
    var box = el(doc, "div", "hfp-card hfp-plan");
    box.setAttribute("data-hfp-plan", card.plan_id);
    box.setAttribute("data-hfp-state", card.state);
    box.appendChild(row(doc, "plan", card.plan_id));
    box.appendChild(row(doc, "workflow", card.workflow_id + " " + card.version));
    box.appendChild(row(doc, "sha256", String(card.plan_sha256).slice(0, 16)));
    box.appendChild(row(doc, "inputs", card.inputs));
    box.appendChild(row(doc, "stages", (card.stages || []).join(", ")));
    box.appendChild(row(doc, "state", card.state));
    var status = el(doc, "div", "hfp-status");
    if (card.can_approve) {
      var button = el(doc, "button", "hfp-approve", "Approve plan");
      button.type = "button";
      button.addEventListener("click", function () {
        button.disabled = true;
        client.approve(card).then(function (res) {
          if (!res.ok && res.code === "bad_nonce") {
            // A later read replaced the nonce: re-read for a fresh one.
            loadPlan(doc, target, client, card.plan_id, opts, "bad_nonce");
            return;
          }
          status.textContent = res.ok ? res.data.result : res.code;
          status.setAttribute("data-hfp-code", res.ok ? res.data.result : res.code);
          if (res.ok) {
            box.setAttribute("data-hfp-state", res.data.card.state);
            watchPlan(doc, box, client, card.plan_id, opts);
          }
        });
      });
      box.appendChild(button);
    } else if (card.run_id) {
      mountRunSlot(doc, box, client, card.run_id, opts);
    } else if (card.state === "approved") {
      watchPlan(doc, box, client, card.plan_id, opts);
    }
    if (notice) {
      status.textContent = notice;
      status.setAttribute("data-hfp-code", notice);
    }
    box.appendChild(status);
    box.appendChild(el(doc, "div", "hfp-note", "paper_approval_terminal_only"));
    target.appendChild(box);
  }

  function loadPlan(doc, target, client, planId, opts, notice) {
    return client.getPlan(planId).then(function (res) {
      if (res.ok) {
        renderPlan(doc, target, client, res.data, opts, notice);
      } else {
        renderError(doc, target, res.code);
      }
      return res;
    });
  }

  // One plan card per plan id per page (`opts.mounted`); a repeat marker gets a
  // pointer and sends nothing (every read of a pending plan mints a new nonce).
  function mountPlan(doc, target, client, planId, opts) {
    var o = opts || {};
    if (o.mounted) {
      if (o.mounted[planId]) {
        renderPointer(doc, target, planId);
        return Promise.resolve(null);
      }
      o.mounted[planId] = 1;
    }
    return loadPlan(doc, target, client, planId, o);
  }

  // Starter list: a click pre-fills the composer; nothing is ever sent (W4).
  function renderWorkflows(doc, target, card, composer) {
    target.textContent = "";
    var box = el(doc, "div", "hfp-card hfp-workflows");
    (card.workflows || []).forEach(function (w) {
      var b = el(doc, "button", "hfp-starter", w.workflow_id);
      b.type = "button";
      b.setAttribute("data-hfp-workflow", w.workflow_id);
      b.addEventListener("click", function () {
        if (!composer) { return; }
        composer.value = w.prompt;
        composer.dispatchEvent(new doc.defaultView.Event("input", { bubbles: true }));
        composer.focus();
      });
      box.appendChild(b);
    });
    target.appendChild(box);
  }

  function findMarkers(text) {
    var out = [];
    var m;
    MARKER.lastIndex = 0;
    while ((m = MARKER.exec(text || "")) !== null) {
      var ok = m[1] === "plan" ? PLAN_ID.test(m[2]) : RUN_ID.test(m[2]);
      if (ok) { out.push({ kind: m[1], id: m[2] }); }
    }
    return out;
  }

  function scan(win, client, opts) {
    var doc = win.document;
    var o = opts || {};
    if (!o.mounted) { o.mounted = {}; }
    var nodes = doc.querySelectorAll(".msg-body, .message-content, [data-hfp-scan]");
    Array.prototype.forEach.call(nodes, function (node) {
      if (node.getAttribute("data-hfp-mounted")) { return; }
      var found = findMarkers(node.textContent);
      if (!found.length) { return; }
      node.setAttribute("data-hfp-mounted", "1");
      found.forEach(function (f) {
        var slot = el(doc, "div", "hfp-root");
        node.appendChild(slot);
        if (f.kind === "plan") {
          mountPlan(doc, slot, client, f.id, o);
        } else {
          mountRun(doc, slot, client, f.id, o);
        }
      });
    });
  }

  function extStorage(win) {
    try {
      var ext = win.hermesExt && typeof win.hermesExt.register === "function"
        ? win.hermesExt.register(EXTENSION_ID) : null;
      return ext && ext.storage ? ext.storage : null;
    } catch (err) { return null; }
  }

  function autoMount(win) {
    var client = createClient(function (u, i) { return win.fetch(u, i); });
    var opts = { storage: extStorage(win), mounted: {} };
    var run = function () { try { scan(win, client, opts); } catch (e) { /* page untouched */ } };
    if (win.MutationObserver && win.document.body) {
      new win.MutationObserver(run).observe(win.document.body, { childList: true, subtree: true });
    }
    run();
    // After a reload, observe the remembered run unless a marker already shows it.
    var resume = function () {
      var resumed = lastRun(opts.storage);
      if (!resumed || opts.mounted[resumed] || !win.document.body) { return; }
      var slot = el(win.document, "div", "hfp-root hfp-resume");
      win.document.body.appendChild(slot);
      resumeRun(win.document, slot, client, opts);
    };
    if (win.document.body) { resume(); } else { win.document.addEventListener("DOMContentLoaded", resume); }
    return client;
  }

  return {
    EXTENSION_ID: EXTENSION_ID,
    PROXY_PREFIX: PROXY_PREFIX,
    KNOWN_CODES: KNOWN,
    proxyPath: proxyPath,
    codeFor: codeFor,
    createClient: createClient,
    pollRun: pollRun,
    pollPlan: pollPlan,
    POLL_MIN_MS: POLL_MIN_MS,
    POLL_MAX_MS: POLL_MAX_MS,
    lastRun: lastRun,
    resumeRun: resumeRun,
    findMarkers: findMarkers,
    mountPlan: mountPlan,
    mountRun: mountRun,
    renderWorkflows: renderWorkflows,
    autoMount: autoMount,
  };
});
