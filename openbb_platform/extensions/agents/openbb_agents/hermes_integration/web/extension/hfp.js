/* OpenBB financial planning extension for Hermes WebUI (#1342).
 *
 * UMD: Node's `require` gets the pure HfpCards logic for tests; in the browser the
 * module registers with `hermesExt` and mounts cards next to `[[hfp:plan:<id>]]` and
 * `[[hfp:run:<id>]]` markers. Every sidecar call goes through the same-origin WebUI
 * proxy path, never to the sidecar port. The extension never starts a chat turn: the
 * starter list only pre-fills the composer, and the user presses Send (W4). Paper
 * actions are approved in the terminal only (W3). Cards render with textContent and
 * show fixed codes, never raw server text.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.HfpCards = api;
    if (root.hermesExt && typeof root.hermesExt.register === "function") {
      try {
        root.hermesExt.register(api.EXTENSION_ID);
      } catch (err) {
        /* registration failure leaves the page untouched */
      }
    }
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
  ];
  var BY_STATUS = { 403: "consent_required", 502: "sidecar_unreachable", 503: "token_unprovisioned" };

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
      approve: function (card) {
        if (!card || !PLAN_ID.test(card.plan_id) || !card.approval_nonce) {
          return Promise.resolve({ ok: false, code: "bad_nonce" });
        }
        var key = card.plan_id;
        if (!inflight[key]) {
          inflight[key] = call("POST", "/plans/" + key + "/approve", {
            plan_sha256: card.plan_sha256,
            approval_nonce: card.approval_nonce,
          });
        }
        return inflight[key];
      },
    };
  }

  // Poll a run card until its outcome is terminal; returns a stop function.
  function pollRun(client, runId, onCard, opts) {
    var o = opts || {};
    var wait = o.setTimeout || setTimeout;
    var interval = o.interval || 1500;
    var stopped = false;
    function tick() {
      if (stopped) { return; }
      client.getRun(runId).then(function (res) {
        if (stopped) { return; }
        onCard(res);
        var done = res.ok && res.data && TERMINAL[res.data.outcome];
        if (!done) { wait(tick, interval); }
      });
    }
    tick();
    return function () { stopped = true; };
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
    box.appendChild(row(doc, "run", card.run_id));
    box.appendChild(row(doc, "plan", card.plan_id));
    box.appendChild(row(doc, "outcome", card.outcome || card.code));
    (card.jobs || []).forEach(function (j) { box.appendChild(row(doc, "job " + j.job_id, j.status)); });
    (card.artifacts || []).forEach(function (a) {
      box.appendChild(row(doc, "artifact " + a.artifact_id, a.kind + " " + String(a.sha256).slice(0, 12)));
    });
    box.appendChild(el(doc, "div", "hfp-note", "paper_approval_terminal_only"));
    target.appendChild(box);
  }

  function mountRun(doc, target, client, runId, opts) {
    return pollRun(client, runId, function (res) {
      if (res.ok) { renderRun(doc, target, res.data); } else { renderError(doc, target, res.code); }
    }, opts);
  }

  function renderPlan(doc, target, client, card, opts) {
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
          status.textContent = res.ok ? res.data.result : res.code;
          status.setAttribute("data-hfp-code", res.ok ? res.data.result : res.code);
          if (res.ok) {
            box.setAttribute("data-hfp-state", res.data.card.state);
          }
        });
      });
      box.appendChild(button);
    } else if (card.run_id) {
      var runBox = el(doc, "div", "hfp-run-slot");
      box.appendChild(runBox);
      mountRun(doc, runBox, client, card.run_id, opts);
    }
    box.appendChild(status);
    box.appendChild(el(doc, "div", "hfp-note", "paper_approval_terminal_only"));
    target.appendChild(box);
  }

  function mountPlan(doc, target, client, planId, opts) {
    return client.getPlan(planId).then(function (res) {
      if (res.ok) { renderPlan(doc, target, client, res.data, opts); } else { renderError(doc, target, res.code); }
      return res;
    });
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

  function scan(win, client) {
    var doc = win.document;
    var nodes = doc.querySelectorAll(".msg-body, .message-content, [data-hfp-scan]");
    Array.prototype.forEach.call(nodes, function (node) {
      if (node.getAttribute("data-hfp-mounted")) { return; }
      var found = findMarkers(node.textContent);
      if (!found.length) { return; }
      node.setAttribute("data-hfp-mounted", "1");
      found.forEach(function (f) {
        var slot = el(doc, "div", "hfp-root");
        node.appendChild(slot);
        if (f.kind === "plan") { mountPlan(doc, slot, client, f.id); } else { mountRun(doc, slot, client, f.id); }
      });
    });
  }

  function autoMount(win) {
    var client = createClient(function (u, i) { return win.fetch(u, i); });
    var run = function () { try { scan(win, client); } catch (e) { /* page untouched */ } };
    if (win.MutationObserver && win.document.body) {
      new win.MutationObserver(run).observe(win.document.body, { childList: true, subtree: true });
    }
    run();
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
    findMarkers: findMarkers,
    mountPlan: mountPlan,
    mountRun: mountRun,
    renderWorkflows: renderWorkflows,
    autoMount: autoMount,
  };
});
