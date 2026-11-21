// Behavior tests for the Local Workspace Viewer's pure rendering helpers
// (#1805). These exercise the REAL functions embedded in index.html by
// extracting each named function's source (balanced-brace) and evaluating it
// in a clean sandbox — no DOM, no fetch, no bootstrap side effects. This
// keeps the viewer a single self-contained HTML file while still giving the
// chart/markdown/metric shaping logic genuine behavioral coverage.
//
// Run: node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/
//
// Fixtures below mirror the ACTUAL 6120 backend response shapes
// (widgets_endpoints.py): pie rows {sector,weight}, raw multi-series rows
// {date,vol_20d,vol_60d}, markdown strings, and metric dicts
// {value,label,note} / {vol_annualized,var_95_1d,beta_spy,note}, and (#1268)
// Workspace metric cards [{label,value}] with server-side labels.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const HTML = readFileSync(join(__dirname, "..", "index.html"), "utf-8");
const WIDGETS = JSON.parse(
  readFileSync(join(__dirname, "..", "..", "..", "..", "..", "extensions", "portfolio_intel", "openbb_portfolio_intel", "widget_backend", "widgets.json"), "utf-8")
);

// Extract the inline <script> body.
function scriptBody(html) {
  const m = /<script>([\s\S]*?)<\/script>/.exec(html);
  if (!m) throw new Error("no <script> block found in index.html");
  return m[1];
}

// Extract a single `function name(...) { ... }` declaration by brace-matching.
function extractFn(src, name) {
  const start = src.indexOf("function " + name + "(");
  if (start < 0) throw new Error(`function ${name} not found in index.html`);
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === "{") depth++;
    else if (c === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced braces extracting ${name}`);
}

// Build a sandbox with the pure helpers under test.
function loadHelpers() {
  const src = scriptBody(HTML);
  const names = ["escapeHtml", "mdToHtml", "inferChartModel", "svgForChart", "xAxisTicksSvg",
    "isDateLabel", "isTimeSeriesModel", "toLwcSeries", "fmtCell", "cellClass", "renderTable",
    "metricModel", "renderMetric", "metricGlossaryData", "metricGlossaryEntry", "metricGlossaryForLabel",
    "metricLabelGlossaryData", "metricLabelGlossaryKey", "metricGlossaryKeyForSummary", "glossaryKeyForLabel", "metricHelpButtonHtml", "metricLabelHtml", "metricHelpPageHtml", "metricHelpLayerPosition", "hideMetricHelpLayer", "hideMetricHelpLayerWithin", "inlineOptionsHtml",
    "sidebarAppsHtml", "pxToGridRect", "clampGridItem", "gridItemStyle", "mergeLayout", "widgetRefString",
    "helpText", "helpButtonHtml", "dataSourceBadge", "resolveParams", "appContextParams", "contextParamLabel", "chartLegendLabelHtml", "renderTab",
    "syncMetricHelpLayer", "bindMetricHelpLayerEvents", "bindMetricHelpButtons",
    "isPlotlyFigure", "plotlyFigureModel", "renderPlotlyFigure"];
  const code = "let METRIC_HELP_ID_SEQ = 0; let ACTIVE_METRIC_HELP_BTN = null; let METRIC_HELP_LAYER_BOUND = false;\n\n"
    + names.map((n) => extractFn(src, n)).join("\n\n") +
    "\n;globalThis.__H = { " + names.join(", ")
    + ", __setDocument: (doc) => { globalThis.document = doc; }, __setWindow: (win) => { globalThis.window = win; }, __setGlobals: (globals) => { Object.assign(globalThis, globals); }, __setActiveMetricHelpBtn: (btn) => { ACTIVE_METRIC_HELP_BTN = btn; }, __getActiveMetricHelpBtn: () => ACTIVE_METRIC_HELP_BTN };";
  const ctx = {
    document: { getElementById: () => null, addEventListener() {} },
    window: { innerWidth: 1024, innerHeight: 768, addEventListener() {} },
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.__H;
}

const H = loadHelpers();

// --------------------------------------------------------------------------
// escapeHtml (regression guard — must survive the #1805 edits)
// --------------------------------------------------------------------------
test("escapeHtml neutralizes angle brackets and quotes", () => {
  assert.equal(H.escapeHtml(`<script>"x"&'y'`), "&lt;script&gt;&quot;x&quot;&amp;&#39;y&#39;");
});

// --------------------------------------------------------------------------
// mdToHtml — safe markdown subset built on escapeHtml
// --------------------------------------------------------------------------
test("mdToHtml renders headings, bold, italic, inline code", () => {
  const h = H.mdToHtml("# Title\n\n**bold** and *italic* and `code`");
  assert.match(h, /<h1>Title<\/h1>/);
  assert.match(h, /<strong>bold<\/strong>/);
  assert.match(h, /<em>italic<\/em>/);
  assert.match(h, /<code>code<\/code>/);
});

test("mdToHtml renders unordered lists", () => {
  const h = H.mdToHtml("- one\n- two");
  assert.match(h, /<ul>/);
  assert.match(h, /<li>one<\/li>/);
  assert.match(h, /<li>two<\/li>/);
});

test("mdToHtml renders blockquotes", () => {
  const h = H.mdToHtml("> quoted line");
  assert.match(h, /<blockquote>[\s\S]*quoted line[\s\S]*<\/blockquote>/);
});

test("mdToHtml renders safe http links", () => {
  const h = H.mdToHtml("[OpenBB](https://openbb.co)");
  assert.match(h, /<a href="https:\/\/openbb\.co"[^>]*>OpenBB<\/a>/);
});

test("mdToHtml is XSS-safe: raw HTML is escaped, not passed through", () => {
  const h = H.mdToHtml('<img src=x onerror="alert(1)">');
  assert.doesNotMatch(h, /<img/i, "raw <img> tag must not survive");
  assert.match(h, /&lt;img/i, "angle brackets must be escaped to entities");
  // The chars 'onerror=' may remain as INERT escaped text; what must never
  // survive is a live tag carrying the handler.
  assert.doesNotMatch(h, /<[a-z][^>]*onerror/i, "no live tag may carry an event handler");
});

test("mdToHtml is XSS-safe: javascript: link hrefs are rejected", () => {
  const h = H.mdToHtml("[x](javascript:alert(1))");
  assert.doesNotMatch(h, /href="javascript:/i);
});

test("mdToHtml preserves link URLs containing _ and * (no emphasis corruption)", () => {
  // Emphasis passes must not rewrite chars inside a generated anchor's href.
  const h = H.mdToHtml("See [report](https://example.com/my_report_v2) now");
  assert.match(
    h,
    /href="https:\/\/example\.com\/my_report_v2"/,
    "underscores in the href must survive the *//_ emphasis passes"
  );
  assert.doesNotMatch(h, /href="[^"]*<em>/i, "no <em> injected into href");
  assert.doesNotMatch(h, /target="<em>/i, "no <em> injected into target attr");
});

test("mdToHtml loud-empty: empty input yields empty-ish output (no throw)", () => {
  assert.equal(typeof H.mdToHtml(""), "string");
});

// --------------------------------------------------------------------------
// inferChartModel — pie config vs. raw-row multi-series inference
// --------------------------------------------------------------------------
test("inferChartModel builds a pie model from labelColumn/valueColumn", () => {
  const rows = [
    { sector: "Technology", weight: 0.5 },
    { sector: "Financials", weight: 0.3 },
    { sector: "Energy", weight: 0.2 },
  ];
  const m = H.inferChartModel(rows, { type: "pie", labelColumn: "sector", valueColumn: "weight" });
  assert.equal(m.kind, "pie");
  assert.equal(m.slices.length, 3);
  assert.equal(m.slices[0].label, "Technology");
  assert.ok(Math.abs(m.total - 1.0) < 1e-9);
});

test("inferChartModel infers a multi-series line from raw rows", () => {
  const rows = [
    { date: "2026-06-01", vol_20d: 0.16, vol_60d: 0.18 },
    { date: "2026-06-02", vol_20d: 0.17, vol_60d: 0.19 },
    { date: "2026-06-03", vol_20d: 0.15, vol_60d: 0.17 },
  ];
  const m = H.inferChartModel(rows, undefined);
  assert.equal(m.kind, "line");
  assert.equal(m.xKey, "date");
  const keys = m.series.map((s) => s.key).sort();
  // Compare by value (join) — cross-realm arrays from the vm sandbox have a
  // different Array.prototype, which trips deepStrictEqual's prototype check.
  assert.equal(keys.join(","), "vol_20d,vol_60d");
  assert.equal(m.series[0].points.length, 3);
});

test("inferChartModel loud-empty: no rows -> empty (table fallback)", () => {
  assert.equal(H.inferChartModel([], undefined).kind, "empty");
});

test("inferChartModel loud-empty: no numeric columns -> empty (table fallback)", () => {
  const m = H.inferChartModel([{ a: "x", b: "y" }], undefined);
  assert.equal(m.kind, "empty");
});

// --------------------------------------------------------------------------
// svgForChart — inline SVG, no CDN
// --------------------------------------------------------------------------
test("svgForChart draws one slice per pie datum", () => {
  const model = H.inferChartModel(
    [{ s: "A", w: 0.6 }, { s: "B", w: 0.4 }],
    { type: "pie", labelColumn: "s", valueColumn: "w" },
  );
  const svg = H.svgForChart(model);
  assert.match(svg, /<svg/);
  assert.match(svg, /class="chart pie-chart"/);
  assert.match(svg, /class="pie-plot"/);
  assert.match(svg, /class="legend pie-legend"/);
  assert.equal((svg.match(/<path/g) || []).length, 2);
});

test("pie charts use a container-responsive plot and legend layout", () => {
  assert.match(
    HTML,
    /\.widget\s*\{[^}]*container-type:\s*inline-size;/s,
    "widget width must establish the pie layout container",
  );
  assert.match(
    HTML,
    /\.chart\.pie-chart\s*\{[^}]*grid-template-columns:\s*minmax\(180px,\s*42%\)\s+minmax\(0,\s*1fr\);/s,
    "wide pie widgets must allocate separate plot and legend columns",
  );
  assert.match(
    HTML,
    /@container\s*\(max-width:\s*520px\)\s*\{[\s\S]*?\.chart\.pie-chart\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/,
    "narrow pie widgets must collapse to one column",
  );
});

test("svgForChart draws one polyline per line series", () => {
  const model = H.inferChartModel(
    [
      { date: "d1", a: 1, b: 2 },
      { date: "d2", a: 3, b: 4 },
    ],
    undefined,
  );
  const svg = H.svgForChart(model);
  assert.match(svg, /<svg/);
  assert.equal((svg.match(/<polyline/g) || []).length, 2);
});

test("inferChartModel applies explicit chart-series labels", () => {
  const model = H.inferChartModel(
    [{ date: "2026-01-01", vol_20d: 20.0, vol_60d: 30.0 }],
    { labels: { vol_20d: "20-Day Volatility (%)", vol_60d: "60-Day Volatility (%)" } },
  );
  assert.equal(
    model.series.map((series) => series.key).join("|"),
    "20-Day Volatility (%)|60-Day Volatility (%)",
  );
});

// --------------------------------------------------------------------------
// #1978 — dual-axis combo: bars on a LEFT axis + line(s) on a RIGHT axis so a
// %-scale margin line isn't crushed flat by a $B-scale revenue series.
// --------------------------------------------------------------------------
const _COMBO_CFG = {
  type: "combo",
  x: "year",
  bars: [
    { column: "revenue_b", name: "Revenue ($B)" },
    { column: "net_income_b", name: "Net Income ($B)" },
  ],
  lines: [{ column: "net_margin_pct", name: "Net Margin (%)" }],
  leftLabel: "$B",
  rightLabel: "%",
};
const _COMBO_ROWS = [
  { year: 2023, revenue_b: 383.3, net_income_b: 97.0, net_margin_pct: 25.31 },
  { year: 2024, revenue_b: 391.0, net_income_b: 93.0, net_margin_pct: 23.79 },
  { year: 2025, revenue_b: 400.5, net_income_b: 102.3, net_margin_pct: 25.54 },
];

test("inferChartModel builds a combo model (bars + lines, own axes)", () => {
  const m = H.inferChartModel(_COMBO_ROWS, _COMBO_CFG);
  assert.equal(m.kind, "combo");
  assert.equal(m.xKey, "year");
  assert.deepEqual(m.xLabels, ["2023", "2024", "2025"]);
  assert.equal(m.bars.length, 2);
  assert.equal(m.lines.length, 1);
  assert.equal(m.bars[0].key, "Revenue ($B)");
  assert.equal(m.lines[0].key, "Net Margin (%)");
  // the margin series values are kept intact (not rescaled into $B)
  assert.equal(m.lines[0].points[0].y, 25.31);
});

test("svgForChart combo: grouped bars + line, dual axis, margin not crushed", () => {
  const svg = H.svgForChart(H.inferChartModel(_COMBO_ROWS, _COMBO_CFG));
  assert.match(svg, /<svg/);
  // 2 bar series x 3 years = 6 bar rects
  assert.equal((svg.match(/<rect/g) || []).length, 6, "expected grouped bar rects");
  // exactly one margin polyline
  assert.equal((svg.match(/<polyline/g) || []).length, 1, "expected one line series");
  // RIGHT axis carries a percentage label (the margin scale), proving a second
  // independent axis exists rather than one shared $B axis.
  const labels = [...svg.matchAll(/font-size="10">([^<]+)<\/text>/g)].map((x) => x[1]);
  assert.ok(labels.some((t) => /%$/.test(t)), `expected a %-axis label, got ${JSON.stringify(labels)}`);
  // LEFT axis stays $B-scale (a label reflecting the ~400 magnitude).
  assert.ok(labels.some((t) => !/%$/.test(t) && parseFloat(t) >= 100),
    `expected a $B-scale left-axis label, got ${JSON.stringify(labels)}`);
});

test("inferChartModel combo loud-empty: all-null columns -> empty", () => {
  const m = H.inferChartModel([{ year: 2024, revenue_b: null, net_margin_pct: null }], {
    type: "combo", x: "year",
    bars: [{ column: "revenue_b" }], lines: [{ column: "net_margin_pct" }],
  });
  assert.equal(m.kind, "empty");
});

// --------------------------------------------------------------------------
// metricModel — single big card vs. multi-key grid, sign coloring
// --------------------------------------------------------------------------
test("metricModel: {value,label,note} -> one card", () => {
  const m = H.metricModel({ value: 0.62, label: "Sentiment (-1..+1)", note: "demo" });
  assert.equal(m.cards.length, 1);
  assert.equal(m.cards[0].label, "Sentiment (-1..+1)");
  assert.equal(m.cards[0].value, 0.62);
  assert.equal(m.note, "demo");
});

test("metricModel: multi numeric keys -> grid, negatives flagged", () => {
  const m = H.metricModel({ vol_annualized: 0.184, var_95_1d: -0.021, beta_spy: 1.08, note: "demo book" });
  assert.equal(m.cards.length, 3);
  assert.equal(m.note, "demo book");
  const varCard = m.cards.find((c) => /var/i.test(c.label));
  assert.equal(varCard.cls, "neg");
});

test("metricModel keeps raw snake_case keys when labels are absent", () => {
  const m = H.metricModel({ net_margin_pct: 0.215, beta_spy: 1.08 });
  assert.equal(m.cards.length, 2);
  assert.equal(m.cards[0].label, "net_margin_pct");
  assert.equal(m.cards[0].rawKey, "net_margin_pct");
  assert.equal(m.cards[1].label, "beta_spy");
  assert.equal(m.cards[1].rawKey, "beta_spy");
  assert.doesNotMatch(m.cards[0].label, /[A-Z ]/);
  assert.doesNotMatch(m.cards[1].label, /[A-Z ]/);
  const container = { innerHTML: "" };
  H.renderMetric(container, { net_margin_pct: 0.215, beta_spy: 1.08 }, { data: { metric: {} } });
  assert.match(container.innerHTML, /net_margin_pct/);
  assert.match(container.innerHTML, /beta_spy/);
  assert.doesNotMatch(container.innerHTML, /Net Margin Pct/);
  assert.doesNotMatch(container.innerHTML, /Beta Spy/);
});

test("metricModel maps Workspace metric cards and keys help on the label (#1268)", () => {
  const m = H.metricModel([
    { label: "Market Cap", value: 3_200_000_000_000 },
    { label: "1-Day 95% VaR (%)", value: -2.1, delta: "-0.3" },
    { label: "Plain Metric", value: 7 },
    { value: 1 },
  ]);
  assert.equal(m.cards.length, 3, "cards without a label are dropped");
  assert.equal(m.cards[0].glossaryKey, "market_cap");
  assert.equal(m.cards[1].glossaryKey, "one_day_var_95");
  assert.equal(m.cards[1].cls, "neg");
  assert.equal(m.cards[1].delta, "-0.3");
  assert.equal(m.cards[2].glossaryKey, null);
  assert.equal(m.note, "");
});

test("metricModel loud-empty: {} -> no cards", () => {
  assert.equal(H.metricModel({}).cards.length, 0);
});

// --------------------------------------------------------------------------
// metricGlossaryEntry — curated F2 labels and safe unknowns
// --------------------------------------------------------------------------
test("metricGlossaryEntry returns a curated F2 record", () => {
  const metric = H.metricGlossaryEntry("pe_ttm");
  assert.equal(metric.label, "P/E (TTM)");
  assert.match(metric.summary, /price.*earnings/i);
});

test("metricGlossaryEntry ignores an unknown key", () => {
  assert.equal(H.metricGlossaryEntry("unreviewed_metric"), null);
});

test("metricGlossaryEntry ignores inherited object keys", () => {
  assert.equal(H.metricGlossaryEntry("toString"), null);
  assert.equal(H.metricGlossaryEntry("__proto__"), null);
});

test("metricHelpButtonHtml labels a known metric accessibly", () => {
  const html = H.metricHelpButtonHtml("market_cap");
  assert.match(html, /aria-label="Learn about Market Cap"/);
  assert.match(html, /data-metric-help="market_cap"/);
  assert.match(html, /data-metric-help-summary="The company/);
  const id = html.match(/aria-describedby="([^"]+)"/)?.[1];
  assert.ok(id, "expected aria-describedby id");
  assert.match(id, /^metric-help-summary-market_cap-\d+$/);
  assert.match(html, new RegExp(`id="${id}">The company[^<]*current share price\\.<\\/span>`));
});

test("metricHelpButtonHtml gives repeated metrics unique described-by ids", () => {
  const first = H.metricHelpButtonHtml("market_cap");
  const second = H.metricHelpButtonHtml("market_cap");
  const firstId = first.match(/aria-describedby="([^"]+)"/)?.[1];
  const secondId = second.match(/aria-describedby="([^"]+)"/)?.[1];
  assert.ok(firstId && secondId, "expected ids on both help buttons");
  assert.notEqual(firstId, secondId);
});

test("metricHelpButtonHtml omits unknown metrics", () => {
  assert.equal(H.metricHelpButtonHtml("unreviewed_metric"), "");
});

test("metricHelpPageHtml renders a curated external resource safely", () => {
  const html = H.metricHelpPageHtml("net_margin");
  assert.match(html, /Net Margin/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
});

test("metricHelpPageHtml reports an unknown metric without interpolating it", () => {
  assert.match(H.metricHelpPageHtml("<script>"), /Metric documentation is unavailable/);
  assert.doesNotMatch(H.metricHelpPageHtml("<script>"), /<script>/);
});

test("metricHelpPageHtml stays self-contained and omits the Bug Context loader", () => {
  const html = H.metricHelpPageHtml("net_margin");
  assert.doesNotMatch(html, /bugcontext\.com\/loader\.js/i);
  assert.doesNotMatch(html, /<script/i);
});

test("viewer shell omits remote Bug Context code", () => {
  assert.doesNotMatch(HTML, /bugcontext\.com\/loader\.js/i);
  assert.doesNotMatch(HTML, /Bug Context feedback widget/);
});

test("metricHelpLayerPosition centers below and clamps within the viewport", () => {
  const pos = H.metricHelpLayerPosition(
    { left: 20, right: 36, top: 20, bottom: 38, width: 16, height: 18 },
    { width: 220, height: 56 },
    { left: 0, top: 0, right: 240, bottom: 180 },
  );
  assert.equal(pos.placement, "bottom");
  assert.equal(pos.left, 8, "tooltip should clamp inward from the left edge");
  assert.equal(pos.top, 48);
  assert.ok(pos.arrowLeft >= 12 && pos.arrowLeft <= 208, `arrow inset must stay inside bubble, got ${pos.arrowLeft}`);
});

test("metricHelpLayerPosition flips above when there is no room below", () => {
  const pos = H.metricHelpLayerPosition(
    { left: 120, right: 136, top: 148, bottom: 166, width: 16, height: 18 },
    { width: 180, height: 40 },
    { left: 0, top: 0, right: 280, bottom: 180 },
  );
  assert.equal(pos.placement, "top");
  assert.equal(pos.top, 98);
});

test("F2 key-stat help is keyed on rendered labels; financial chart keys ride on traces", () => {
  // #1268: Workspace manifests carry no viewer-only glossary maps.
  assert.equal(WIDGETS.pi_equity_key_stats.data.metricGlossary, undefined);
  assert.equal(H.metricLabelGlossaryKey("P/E (TTM)"), "pe_ttm");
  assert.equal(H.metricLabelGlossaryKey("Market Cap"), "market_cap");
  assert.equal(WIDGETS.pi_equity_financial_charts.data, undefined);
  const glossary = H.plotlyFigureModel(FINANCIALS_FIGURE).glossary;
  assert.equal(glossary["Revenue ($B)"], "revenue_b");
  assert.equal(glossary["Net Margin (%)"], "net_margin_pct");
});

test("look-through effective-weight formatter converts fractions to displayed percentages", () => {
  const col = WIDGETS.pi_lookthrough_top25.data.table.columnsDefs
    .find((item) => item.field === "effective_weight");
  assert.equal(col.formatterFn, "normalizedPercent");
  assert.equal(H.fmtCell(0.078, col), "7.80%");
});

test("risk dashboard cards show percentage points as served; beta stays a ratio (#1268)", () => {
  assert.equal(WIDGETS.pi_risk_dashboard.data, undefined, "no data.metric in the manifest");
  const container = { innerHTML: "" };
  H.renderMetric(container, [
    { label: "Annualized Volatility (%)", value: 18.4 },
    { label: "1-Day 95% VaR (%)", value: -2.1 },
    { label: "Beta vs SPY", value: 1.08 },
    { label: "Data State", value: "Demo: synthetic sample book" },
  ], WIDGETS.pi_risk_dashboard);
  assert.match(container.innerHTML, />18\.4</);
  assert.match(container.innerHTML, />-2\.1</);
  assert.match(container.innerHTML, />1\.08</);
  assert.match(container.innerHTML, /Annualized Volatility \(%\)[\s\S]*data-metric-help="annualized_volatility"/);
  assert.match(container.innerHTML, /Beta vs SPY[\s\S]*data-metric-help="beta_vs_spy"/);
  assert.match(container.innerHTML, />Demo: synthetic sample book</);
});

// Brinson and X-Ray sector are native Workspace Plotly figures (#1267). The
// viewer maps the figure onto its own chart models; this fixture mirrors the
// backend's brinson_attribution_figure / xray_sector_figure output shapes.
const BRINSON_FIGURE = {
  data: [
    { type: "bar", name: "Allocation Effect (%)", x: ["Technology", "Energy"], y: [3.0, -0.4], meta: { glossaryKey: "allocation_effect" } },
    { type: "bar", name: "Selection Effect (%)", x: ["Technology", "Energy"], y: [-0.5, 0.2], meta: { glossaryKey: "selection_effect" } },
    { type: "bar", name: "Interaction Effect (%)", x: ["Technology", "Energy"], y: [0.1, 0.0], meta: { glossaryKey: "interaction_effect" } },
    { type: "scatter", mode: "markers", name: "Total Active Return (%)", x: ["Technology", "Energy"], y: [2.6, -0.2], meta: { glossaryKey: "total_active_return" } },
  ],
  layout: {
    meta: { state: "demo" },
    annotations: [{ text: "Synthetic demo book, 1Y vs SPY; not your portfolio." }],
  },
};

// #1268 Terminal chart figures (shapes mirror terminal_charts.py output).
const FINANCIALS_FIGURE = {
  data: [
    { type: "bar", name: "Revenue ($B)", x: [2023, 2024, 2025], y: [383.3, 391.0, 400.5], meta: { glossaryKey: "revenue_b" } },
    { type: "bar", name: "Net Income ($B)", x: [2023, 2024, 2025], y: [97.0, 93.0, 102.3], meta: { glossaryKey: "net_income_b" } },
    { type: "scatter", mode: "lines+markers", name: "Net Margin (%)", x: [2023, 2024, 2025], y: [25.31, 23.79, 25.54], yaxis: "y2", meta: { glossaryKey: "net_margin_pct" } },
  ],
  layout: {
    meta: { state: "live", source: "fmp_cached" },
    barmode: "group",
    yaxis: { title: { text: "Billions ($B)" } },
    yaxis2: { title: { text: "Net margin (%)" }, overlaying: "y", side: "right" },
  },
};
const CANDLE_FIGURE = {
  data: [
    { type: "candlestick", name: "OHLC", x: ["2026-07-01", "2026-07-02", "2026-07-03"], open: [10, 11, 12], high: [12, 13, 14], low: [9, 10, 11], close: [11, 12, 11.5] },
    { type: "bar", name: "Volume", x: ["2026-07-01", "2026-07-02", "2026-07-03"], y: [1000, 2500, 1800], yaxis: "y2", meta: { glossaryKey: "volume" } },
  ],
  layout: { meta: { state: "demo", source: "stub" }, annotations: [{ text: "Demo data: sample values, not live AAPL data." }] },
};
const CHARTING_FIGURE = {
  data: [
    { type: "candlestick", name: "OHLC", x: ["2026-04-01", "2026-04-15"], open: [170.1, 172.0], high: [172.5, 174.3], low: [169.2, 171.2], close: [171.35, 173.1] },
    { type: "scatter", name: "SMA 20", x: ["2026-04-01", "2026-04-15"], y: [168.4, 170.1] },
    { type: "scatter", name: "RSI 14", x: ["2026-04-01", "2026-04-15"], y: [58.2, 62.4], yaxis: "y2" },
  ],
  layout: { meta: { state: "demo", source: "stub" } },
};
const VOL_FIGURE = {
  data: [
    { type: "scatter", mode: "lines", name: "20-Day Volatility (%)", x: ["2026-06-01", "2026-06-02"], y: [16.0, 16.67], meta: { glossaryKey: "twenty_day_volatility" } },
    { type: "scatter", mode: "lines", name: "60-Day Volatility (%)", x: ["2026-06-01", "2026-06-02"], y: [18.0, 18.33], meta: { glossaryKey: "sixty_day_volatility" } },
  ],
  layout: { meta: { state: "demo", source: "stub" }, annotations: [{ text: "Demo portfolio (synthetic); not your account." }] },
};

test("Brinson Plotly figure maps to percentage-point series that retain help keys", () => {
  assert.equal(H.isPlotlyFigure(BRINSON_FIGURE), true);
  assert.equal(H.isPlotlyFigure([{ sector: "S0" }]), false);
  const parsed = H.plotlyFigureModel(BRINSON_FIGURE);
  assert.equal(parsed.model.kind, "line");
  assert.deepEqual([...parsed.model.xLabels], ["Technology", "Energy"]);
  assert.equal(
    parsed.model.series.map((series) => series.key).join("|"),
    "Allocation Effect (%)|Selection Effect (%)|Interaction Effect (%)|Total Active Return (%)",
  );
  assert.deepEqual(parsed.model.series[3].points.map((p) => p.y), [2.6, -0.2]);
  assert.equal(parsed.glossary["Allocation Effect (%)"], "allocation_effect");
  assert.equal(parsed.glossary["Total Active Return (%)"], "total_active_return");
  const container = { innerHTML: "", querySelectorAll: () => [] };
  H.renderPlotlyFigure(container, BRINSON_FIGURE, { type: "chart" });
  assert.match(container.innerHTML, /demo book, 1Y vs SPY/);
  assert.match(container.innerHTML, /data-metric-help="allocation_effect"/);
});

test("X-Ray sector Plotly pie maps to a pie model", () => {
  const parsed = H.plotlyFigureModel({
    data: [{ type: "pie", labels: ["Information Technology", "Energy"], values: [0.38, 0.08] }],
    layout: { annotations: [{ text: "Demo portfolio (synthetic); not your account." }] },
  });
  assert.equal(parsed.model.kind, "pie");
  assert.deepEqual(parsed.model.slices.map((s) => s.label), ["Information Technology", "Energy"]);
  assert.ok(Math.abs(parsed.model.total - 0.46) < 1e-12);
});

test("trace-free Plotly figure renders its state message, not a blank chart", () => {
  const container = { innerHTML: "", querySelectorAll: () => [] };
  H.renderPlotlyFigure(container, {
    data: [],
    layout: {
      meta: { state: "unavailable" },
      annotations: [{ text: "Unavailable: no sector data, account resolver not wired for this account." }],
    },
  }, { type: "chart" });
  assert.match(container.innerHTML, /class="state"/);
  assert.match(container.innerHTML, /Unavailable/);
  assert.match(container.innerHTML, /account resolver not wired/);
  assert.doesNotMatch(container.innerHTML, /<svg/);
});

test("single-value metric cards carry the served label and glossary help (#1268)", () => {
  const model = H.metricModel([
    { label: "Concentration (HHI)", value: 0.2374 },
    { label: "Data State", value: "Demo: synthetic sample book" },
  ]);
  assert.equal(model.cards[0].label, "Concentration (HHI)");
  assert.equal(model.cards[0].glossaryKey, "herfindahl_hirschman_index");
  assert.equal(model.cards[1].glossaryKey, null);
});

test("hidden provenance columns stay hidden; data state is shown (#1269)", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [{
    metric: "Resistance 3", value: 234.6, note: "",
    data_state: "demo", data_source: "SOURCE-SENTINEL", data_as_of: "ASOF-SENTINEL",
  }], WIDGETS.pi_equity_technicals);
  assert.match(container.innerHTML, /Data State/);
  assert.match(container.innerHTML, />demo</);
  assert.doesNotMatch(container.innerHTML, /SOURCE-SENTINEL|ASOF-SENTINEL|Data Source|Data As Of/);
});

test("server-labelled technical rows get glossary help (#1268)", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [{ metric: "Resistance 3", value: 234.6, note: "" }],
    WIDGETS.pi_equity_technicals);
  assert.match(container.innerHTML, /Resistance 3[\s\S]*data-metric-help="resistance"/);
});

test("server-labelled analyst-forecast rows map to focused glossary help (#1268)", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { metric: "Rating Distribution: Strong Buy / Buy", value: "12 / 8", note: "as of today" },
    { metric: "Rating Distribution: Hold / Sell / Strong Sell", value: "3 / 2 / 1", note: "" },
    { metric: "Q3 2025 EPS Surprise", value: "+3.2%", note: "reported" },
    { metric: "Q2 2025 EPS Surprise", value: "+1.9%", note: "reported" },
    { metric: "Historical Revenue Estimate", value: "n/a", note: "unavailable" },
  ], WIDGETS.pi_equity_analyst_forecasts);
  for (const key of ["rating_distribution", "eps_surprise", "revenue_estimate"]) {
    assert.match(container.innerHTML, new RegExp(`data-metric-help="${key}"`));
  }
  assert.equal(H.metricLabelGlossaryKey("Rating Distribution: "), null);
  assert.equal(H.metricLabelGlossaryKey("Q5 2025 EPS Surprise"), null);
  assert.equal(H.metricLabelGlossaryKey("Rating: Buy"), null, "raw identifiers carry no help");
});

test("server-labelled enum values render verbatim and escaped (#1268)", () => {
  const smartMoney = { innerHTML: "" };
  H.renderTable(smartMoney, [
    { symbol: "NVDA", kind: "Insider Buy", actor: "CFO", value_usd: 1, date: "2026-08-15" },
    { symbol: "AAPL", kind: "13F Increase", actor: "<b>Fund</b>", value_usd: 1, date: "2026-08-15" },
  ], WIDGETS.pi_smart_money_ribbon);
  for (const label of ["Insider Buy", "13F Increase"]) {
    assert.match(smartMoney.innerHTML, new RegExp(`>${label}</td>`));
  }
  assert.match(smartMoney.innerHTML, /&lt;b&gt;Fund&lt;\/b&gt;/);
  assert.doesNotMatch(smartMoney.innerHTML, /<b>Fund/);

  const consensus = { innerHTML: "" };
  H.renderTable(consensus, [
    { symbol: "MSFT", avg_target: 465, buy: 28, hold: 4, sell: 0, consensus: "Strong Buy" },
  ], WIDGETS.pi_basket_analyst_consensus);
  assert.match(consensus.innerHTML, />Strong Buy<\/td>/);
  assert.match(consensus.innerHTML, /Consensus Rating[\s\S]*data-metric-help="consensus_rating"/);
});

test("column headerTooltip is escaped and only a curated summary adds help (#1268)", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [{ a: 1, b: 2 }], {
    data: {
      table: {
        columnsDefs: [
          { field: "a", headerName: "A", headerTooltip: '"><script>alert(1)</script>' },
          { field: "b", headerName: "B", headerTooltip: H.metricGlossaryEntry("pe_ttm").summary },
        ],
      },
    },
  });
  assert.doesNotMatch(container.innerHTML, /<script>/);
  assert.match(container.innerHTML, /title="&quot;&gt;&lt;script&gt;alert\(1\)&lt;\/script&gt;"/);
  assert.doesNotMatch(container.innerHTML, /<th[^>]*>A[\s\S]*?data-metric-help=[\s\S]*?<\/th><th/);
  assert.match(container.innerHTML, /<th title="[^"]+"><span class="metric-label">B[\s\S]*data-metric-help="pe_ttm"/);
  assert.equal(H.metricGlossaryKeyForSummary(""), null);
  assert.equal(H.metricGlossaryKeyForSummary(undefined), null);
  assert.equal(H.metricGlossaryKeyForSummary("not a summary"), null);
});

test("every manifest headerTooltip resolves to a curated glossary record (#1268)", () => {
  let seen = 0;
  for (const [id, widget] of Object.entries(WIDGETS)) {
    const columns = (widget.data && widget.data.table && widget.data.table.columnsDefs) || [];
    for (const column of columns) {
      if (!("headerTooltip" in column)) continue;
      seen += 1;
      assert.ok(H.metricGlossaryKeyForSummary(column.headerTooltip), `${id}.${column.field}`);
    }
  }
  assert.equal(seen, 19 + 2 * 18); // #1269: data_source/data_as_of on 18 tables
});

test("every rendered-label glossary key is a curated record", () => {
  const labels = H.metricLabelGlossaryData();
  assert.ok(Object.keys(labels).length >= 70);
  for (const [label, key] of Object.entries(labels)) {
    assert.ok(H.metricGlossaryEntry(key), `${label} -> ${key}`);
  }
});

test("TradingView legend keeps chart gestures transparent but binds help controls", () => {
  assert.match(HTML, /\.tvlegend\s*\{[^}]*pointer-events:\s*none;/s);
  assert.match(HTML, /\.tvlegend \.mhelp-wrap, \.tvlegend \.mhelp \{\s*pointer-events:\s*auto;\s*\}/);
  const btn = {
    dataset: {},
    listeners: {},
    addEventListener(type, listener) { this.listeners[type] = listener; },
  };
  H.bindMetricHelpButtons({ querySelectorAll: (selector) => selector === ".mhelp" ? [btn] : [] });
  for (const event of ["pointerdown", "pointerenter", "pointerleave", "focus", "blur", "click"]) {
    assert.equal(typeof btn.listeners[event], "function", `${event} must be bound on legend help`);
  }
  assert.equal(btn.dataset.metricHelpBound, "1");
});

test("What-If server-labelled rows resolve glossary help (#1268)", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { metric: "Symbol Weight (%)", before: 4.8, after: 5.0, delta: 0.2 },
    { metric: "Sector Weight (%)", before: 37.2, after: 37.4, delta: 0.2 },
    { metric: "Cash Weight (%)", before: 5, after: 4.8, delta: -0.2 },
    { metric: "Beta vs SPY", before: 1.08, after: 1.1, delta: 0.02 },
  ], WIDGETS.pi_whatif_card);
  for (const [label, key] of [
    ["Symbol Weight (%)", "symbol_weight"],
    ["Sector Weight (%)", "sector_weight"],
    ["Cash Weight (%)", "cash_weight"],
    ["Beta vs SPY", "beta_vs_spy"],
  ]) {
    assert.ok(container.innerHTML.includes(label));
    assert.match(container.innerHTML, new RegExp(`data-metric-help="${key}"`));
  }
});

test("earnings Surprise header tooltip is the earnings-surprise glossary summary (#1268)", () => {
  const column = WIDGETS.pi_earnings_history.data.table.columnsDefs
    .find((item) => item.field === "surprise_pct");
  assert.equal(column.glossaryKey, undefined);
  assert.equal(H.metricGlossaryKeyForSummary(column.headerTooltip), "earnings_surprise");
  const container = { innerHTML: "" };
  H.renderTable(container, [{ quarter: "Q3 2025", eps_actual: 1.55, eps_estimate: 1.5, surprise_pct: 3.3 }],
    WIDGETS.pi_earnings_history);
  assert.match(container.innerHTML, /Surprise \(%\)[\s\S]*data-metric-help="earnings_surprise"/);
});

test("time-series legend labels expose help from the figure's trace glossary keys", () => {
  const figures = [
    [{ data: [{ type: "scatter", name: "Closing Price", x: ["2026-01-01"], y: [1], meta: { glossaryKey: "closing_price" } }], layout: {} }, "Closing Price", "closing_price"],
    [VOL_FIGURE, "20-Day Volatility (%)", "twenty_day_volatility"],
    [{ data: [{ type: "scatter", name: "Portfolio Equity", x: ["2026-01-01"], y: [1], meta: { glossaryKey: "portfolio_equity" } }], layout: {} }, "Portfolio Equity", "portfolio_equity"],
  ];
  for (const [figure, label, key] of figures) {
    const def = { data: { metricGlossary: H.plotlyFigureModel(figure).glossary } };
    const html = H.chartLegendLabelHtml(label, def);
    assert.match(html, new RegExp(`data-metric-help="${key}"`));
  }
});

test("Plotly candlestick figure maps to a candle model with its volume pane (#1268)", () => {
  const parsed = H.plotlyFigureModel(CANDLE_FIGURE);
  assert.equal(parsed.model.kind, "candle");
  assert.deepEqual([...parsed.model.xLabels], ["2026-07-01", "2026-07-02", "2026-07-03"]);
  assert.deepEqual(parsed.model.candles.map((c) => [c.o, c.h, c.l, c.c]), [[10, 12, 9, 11], [11, 13, 10, 12], [12, 14, 11, 11.5]]);
  assert.deepEqual(parsed.model.volume.map((p) => p.y), [1000, 2500, 1800]);
  assert.equal(H.isTimeSeriesModel(parsed.model), true);
  assert.equal(H.toLwcSeries(parsed.model).kind, "candle");
  const container = { innerHTML: "", querySelectorAll: () => [] };
  H.renderPlotlyFigure(container, CANDLE_FIGURE, { type: "chart" });
  assert.match(container.innerHTML, /Demo data/);
  assert.match(container.innerHTML, /aria-label="candlestick chart"/);
});

test("Plotly charting figure keeps candles; the RSI pane is not read as volume (#1268)", () => {
  const parsed = H.plotlyFigureModel(CHARTING_FIGURE);
  assert.equal(parsed.model.kind, "candle");
  assert.equal(parsed.model.volume, null);
  assert.deepEqual(parsed.model.candles.map((c) => c.c), [171.35, 173.1]);
});

test("Plotly dual-axis figure maps to the combo model with help keys (#1268)", () => {
  const parsed = H.plotlyFigureModel(FINANCIALS_FIGURE);
  assert.equal(parsed.model.kind, "combo");
  assert.deepEqual([...parsed.model.xLabels], ["2023", "2024", "2025"]);
  assert.deepEqual(parsed.model.bars.map((s) => s.key), ["Revenue ($B)", "Net Income ($B)"]);
  assert.deepEqual(parsed.model.lines.map((s) => s.key), ["Net Margin (%)"]);
  // the margin series keeps its own (percent) values, never rescaled into $B
  assert.deepEqual(parsed.model.lines[0].points.map((p) => p.y), [25.31, 23.79, 25.54]);
  const container = { innerHTML: "", querySelectorAll: () => [] };
  H.renderPlotlyFigure(container, FINANCIALS_FIGURE, { type: "chart" });
  assert.match(container.innerHTML, /aria-label="combo bar and line chart"/);
  assert.match(container.innerHTML, /data-metric-help="revenue_b"/);
  assert.match(container.innerHTML, /data-metric-help="net_margin_pct"/);
});

test("dated Plotly line figure is a time-series model for the TradingView path (#1268)", () => {
  const parsed = H.plotlyFigureModel(VOL_FIGURE);
  assert.equal(parsed.model.kind, "line");
  assert.equal(H.isTimeSeriesModel(parsed.model), true);
  assert.deepEqual(parsed.model.series[1].points.map((p) => p.y), [18.0, 18.33]);
});

test("renderTable adds help only for mapped first-column metrics", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { metric: "Market Cap", value: 3_200_000_000_000 },
    { metric: "Unmapped Metric", value: 42 },
  ], WIDGETS.pi_equity_key_stats);
  assert.match(container.innerHTML, /Market Cap[\s\S]*data-metric-help="market_cap"/);
  assert.match(container.innerHTML, /Market Cap[\s\S]*metric-help-summary-market_cap-\d+[\s\S]*The company/);
  assert.match(container.innerHTML, />Unmapped Metric<\/td>/);
  assert.doesNotMatch(container.innerHTML, /Unmapped Metric[\s\S]*data-metric-help=/);
});

test("renderTable adds help buttons to glossary-backed header tooltips only", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { market_cap: 3_200_000_000_000, opaque_field: 42, status: "active" },
  ], {
    data: {
      table: {
        columnsDefs: [
          { field: "market_cap", headerName: "Market Cap", headerTooltip: H.metricGlossaryEntry("market_cap").summary },
          { field: "opaque_field", headerName: "Opaque Field", headerTooltip: "An unreviewed note." },
          { field: "status", headerName: "Status" },
        ],
      },
    },
  });
  assert.match(container.innerHTML, /<th title="[^"]*"><span class="metric-label">Market Cap[\s\S]*data-metric-help="market_cap"/);
  assert.match(container.innerHTML, /<th title="An unreviewed note\.">Opaque Field<\/th>/);
  assert.match(container.innerHTML, /<th>Status<\/th>/);
});

test("renderMetric adds help buttons to glossary-backed card labels only", () => {
  const container = { innerHTML: "" };
  H.renderMetric(container, [
    { label: "Market Cap", value: 3_200_000_000_000 },
    { label: "Opaque Field", value: 42 },
    { label: "Plain Metric", value: 7 },
  ], { type: "metric" });
  assert.match(container.innerHTML, /<div class="mlabel"[^>]*><span class="metric-label">Market Cap[\s\S]*data-metric-help="market_cap"/);
  assert.match(container.innerHTML, /<div class="mlabel"[^>]*>Opaque Field<\/div>/);
  assert.doesNotMatch(container.innerHTML, /Opaque Field[\s\S]*data-metric-help=/);
  assert.match(container.innerHTML, /<div class="mlabel"[^>]*>Plain Metric<\/div>/);
});

test("2010 key stats renders explicit financial table headers", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [{ metric: "Market Cap", value: 3_200_000_000_000 }],
    WIDGETS.pi_equity_key_stats);
  assert.match(container.innerHTML, /<th>Financial Metric<\/th>/);
  assert.match(container.innerHTML, /<th>Value<\/th>/);
  assert.match(container.innerHTML, /Market Cap[\s\S]*data-metric-help="market_cap"/);
});

test("2011 technicals render explicit indicator table headers", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [{ metric: "Resistance 3", value: 234.6, note: "Classic pivot" }],
    WIDGETS.pi_equity_technicals);
  assert.match(container.innerHTML, /<th>Technical Indicator<\/th>/);
  assert.match(container.innerHTML, /<th>Value<\/th>/);
  assert.match(container.innerHTML, /<th>Interpretation<\/th>/);
  assert.match(container.innerHTML, /Resistance 3[\s\S]*data-metric-help="resistance"/);
});

test("2012 event calendar renders served event labels and header help", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { symbol: "AAPL", type: "Ex-Dividend", date: "2026-08-08", detail: "$0.24/sh" },
    { symbol: "NVDA", type: "Form 8-K", date: "2026-07-22", detail: "Item 7.01" },
  ], WIDGETS.pi_event_calendar);
  assert.match(container.innerHTML, /<th[^>]*><span class="metric-label">Event Type[\s\S]*data-metric-help="event_type"/);
  assert.match(container.innerHTML, />Ex-Dividend<\/td>/);
  assert.match(container.innerHTML, />Form 8-K<\/td>/);
});

test("2013 forecasts render explicit forecast table headers", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { metric: "12-Month Price Target", value: "$240", note: "12 months" },
  ], WIDGETS.pi_equity_analyst_forecasts);
  assert.match(container.innerHTML, /<th>Forecast Measure<\/th>/);
  assert.match(container.innerHTML, /<th>Value<\/th>/);
  assert.match(container.innerHTML, /<th>Context<\/th>/);
  assert.match(container.innerHTML, /12-Month Price Target[\s\S]*data-metric-help="twelve_month_price_target"/);
});

test("2014 what-if card renders explicit before-and-after headers", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { metric: "Symbol Weight (%)", before: 4.8, after: 5.0, delta: 0.2 },
  ], WIDGETS.pi_whatif_card);
  assert.match(container.innerHTML, /<th>Portfolio Metric<\/th>/);
  assert.match(container.innerHTML, /<th>Before Trade<\/th>/);
  assert.match(container.innerHTML, /<th>After Trade<\/th>/);
  assert.match(container.innerHTML, /<th>Change<\/th>/);
  assert.match(container.innerHTML, /Symbol Weight \(%\)[\s\S]*data-metric-help="symbol_weight"/);
});

test("2015 alerts render served alert categories and header help", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { severity: "warning", kind: "Held-Security Form 8-K", symbol: "NVDA", detail: "Item 7.01" },
    { severity: "info", kind: "Upcoming Earnings", symbol: "AAPL", detail: "Earnings" },
    { severity: "critical", kind: "Material News", symbol: "TSLA", detail: "Recall" },
  ], WIDGETS.pi_alerts_panel);
  assert.match(container.innerHTML, /<th[^>]*><span class="metric-label">Alert Type[\s\S]*data-metric-help="alert_type"/);
  for (const label of ["Held-Security Form 8-K", "Upcoming Earnings", "Material News"]) {
    assert.match(container.innerHTML, new RegExp(`>${label}</td>`));
  }
});

test("2016 news ribbon renders operational headers without glossary controls", () => {
  const container = { innerHTML: "" };
  H.renderTable(container, [
    { symbol: "AAPL", when: "2026-07-19", title: "Apple beats estimates", severity: "material" },
  ], WIDGETS.pi_news_ribbon);
  for (const header of ["Symbol", "Published", "Headline", "Severity"]) {
    assert.match(container.innerHTML, new RegExp(`<th>${header}</th>`));
  }
  assert.doesNotMatch(container.innerHTML, /data-metric-help=/);
});

test("2017 sentiment gauge renders its served label, glossary help and data state", () => {
  const container = { innerHTML: "" };
  H.renderMetric(container, [
    { label: "News Sentiment Score (-1 to +1)", value: 0.62 },
    { label: "Data State", value: "Demo: synthetic sample, 7-day window" },
  ], WIDGETS.pi_sentiment_gauge);
  assert.match(container.innerHTML, /News Sentiment Score \(-1 to \+1\)[\s\S]*data-metric-help="news_sentiment_score"/);
  assert.match(container.innerHTML, />Demo: synthetic sample, 7-day window</);
});

test("renderTable hides an active floating metric tooltip before replacing widget body", () => {
  const layer = {
    hidden: false,
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
  };
  const activeBtn = {};
  H.__setDocument({ getElementById: () => layer });
  H.__setActiveMetricHelpBtn(activeBtn);
  let html = "";
  const container = {
    contains(node) { return node === activeBtn; },
    set innerHTML(value) {
      assert.equal(layer.hidden, true, "tooltip layer should hide before body replacement");
      html = value;
    },
    get innerHTML() { return html; },
  };
  H.renderTable(container, [{ metric: "Market Cap", value: 1 }], WIDGETS.pi_equity_key_stats);
  assert.equal(H.__getActiveMetricHelpBtn(), null);
  assert.equal(layer.attrs["aria-hidden"], "true");
  assert.match(html, /data-metric-help="market_cap"/);
});

test("renderTab hides an active floating metric tooltip before clearing the widget grid", () => {
  const layer = {
    hidden: false,
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
  };
  const activeBtn = {};
  const calls = [];
  H.__setDocument({
    getElementById: (id) => (id === "metric-help-layer" ? layer : null),
    querySelectorAll: () => [],
  });
  H.__setActiveMetricHelpBtn(activeBtn);
  const grid = {
    set innerHTML(value) {
      calls.push(value);
      assert.equal(layer.hidden, true, "tooltip layer should hide before grid replacement");
    },
    get innerHTML() { return ""; },
  };
  H.__setGlobals({
    $: (id) => {
      if (id === "grid") return grid;
      if (id === "tabs") return { querySelectorAll: () => [] };
      return null;
    },
    disposeTradingViewCharts: () => {},
    APP: { tabs: { overview: { name: "Overview", layout: [] } } },
    ACTIVE_TAB: "overview",
    LAYOUT: [],
    loadOverrides: () => [],
    mergeLayout: () => [],
    renderWidget: () => {},
    gridGeom: () => ({}),
    fitCanvas: () => {},
  });
  H.renderTab("overview");
  assert.equal(H.__getActiveMetricHelpBtn(), null);
  assert.equal(layer.attrs["aria-hidden"], "true");
  assert.deepEqual(calls, ["", '<div class="state">This tab has no widgets.</div>']);
});

test("svgForChart combo legend adds help buttons for mapped series", () => {
  const svg = H.svgForChart(
    H.inferChartModel(_COMBO_ROWS, _COMBO_CFG),
    { data: { metricGlossary: H.plotlyFigureModel(FINANCIALS_FIGURE).glossary } },
  );
  assert.match(svg, /Revenue \(\$B\)[\s\S]*data-metric-help="revenue_b"/);
  assert.match(svg, /Net Income \(\$B\)[\s\S]*data-metric-help="net_income_b"/);
  assert.match(svg, /Net Margin \(%\)[\s\S]*data-metric-help="net_margin_pct"/);
  assert.match(svg, /Revenue \(\$B\)[\s\S]*data-metric-help-summary="Annual sales expressed in billions of dollars\."/);
  assert.match(svg, /Revenue \(\$B\)[\s\S]*id="metric-help-summary-revenue_b-\d+">Annual sales expressed in billions of dollars\.<\/span>/);
});

// --------------------------------------------------------------------------
// #1885 — candle mode must NOT crush OHLC onto a shared axis with volume
// --------------------------------------------------------------------------
test("inferChartModel detects OHLC candle shape (not a 5-line collapse)", () => {
  const rows = [
    { date: "2026-06-01", open: 188, high: 191, low: 187, close: 190, volume: 1_000_000 },
    { date: "2026-06-02", open: 190, high: 194, low: 189, close: 193, volume: 1_200_000 },
    { date: "2026-06-03", open: 193, high: 195, low: 190, close: 191, volume: 900_000 },
  ];
  const m = H.inferChartModel(rows, undefined);
  assert.equal(m.kind, "candle", "OHLCV rows must infer a candle model, not a line");
  assert.equal(m.candles.length, 3);
  assert.equal(m.candles[0].o, 188);
  assert.equal(m.candles[0].c, 190);
  // volume is carried separately so it never shares the price y-axis
  assert.ok(m.volume, "volume series must be separated from the price axis");
  assert.equal(m.volume.length, 3);
});

test("svgForChart candle: OHLC uses a PRICE-only y-axis (volume excluded)", () => {
  const rows = [
    { date: "d1", open: 188, high: 191, low: 187, close: 190, volume: 1_000_000 },
    { date: "d2", open: 190, high: 194, low: 189, close: 193, volume: 1_200_000 },
  ];
  const svg = H.svgForChart(H.inferChartModel(rows, undefined));
  assert.match(svg, /<svg/);
  // candlesticks render as <rect> bodies (one per candle) + <line> wicks
  assert.ok((svg.match(/<rect/g) || []).length >= 2, "expected candle body rects");
  // The price axis labels must reflect PRICE magnitude (~1e2), NOT volume (~1e6).
  // If volume shared the axis, the top label would be ~1,200,000.
  const labelMatch = [...svg.matchAll(/font-size="10">([^<]+)<\/text>/g)].map((x) => x[1]);
  assert.ok(labelMatch.length >= 2, "expected y-axis labels");
  assert.ok(
    labelMatch.every((t) => !/\d{7}/.test(t) && !/M$/.test(t)),
    `price axis labels must be price-scale, got ${JSON.stringify(labelMatch)}`,
  );
});

test("inferChartModel: numeric year column is the x-axis, not a plotted series (#1885)", () => {
  const rows = [
    { year: 2023, revenue: 383_000, net_income: 97_000 },
    { year: 2024, revenue: 391_000, net_income: 94_000 },
    { year: 2025, revenue: 400_000, net_income: 99_000 },
  ];
  const m = H.inferChartModel(rows, undefined);
  assert.equal(m.kind, "line");
  assert.equal(m.xKey, "year", "year must be treated as the x-axis");
  const keys = m.series.map((s) => s.key).sort().join(",");
  assert.equal(keys, "net_income,revenue", "year must not be a plotted series");
});

// --------------------------------------------------------------------------
// #1887 — y-axis labels must not clip past the left edge (compact big numbers)
// --------------------------------------------------------------------------
test("svgForChart compacts large y-axis labels so they do not overflow (#1887)", () => {
  const rows = [
    { date: "d1", pnl: 103_060 },
    { date: "d2", pnl: 118_500 },
  ];
  const svg = H.svgForChart(H.inferChartModel(rows, undefined));
  const labels = [...svg.matchAll(/font-size="10">([^<]+)<\/text>/g)].map((x) => x[1]);
  // large magnitudes must be compacted (k / M), never a raw 6+ digit run
  assert.ok(
    labels.some((t) => /[kMB]$/.test(t)),
    `expected compacted axis label (k/M/B), got ${JSON.stringify(labels)}`,
  );
  assert.ok(
    labels.every((t) => !/\d{6}/.test(t)),
    `no raw 6+ digit label may remain, got ${JSON.stringify(labels)}`,
  );
});

// --------------------------------------------------------------------------
// #1886 — params with an inline options array must build a <select> dropdown
// --------------------------------------------------------------------------
test("inlineOptionsHtml builds selectable <option>s from an inline array (#1886)", () => {
  const html = H.inlineOptionsHtml(
    [{ value: "line", label: "Line" }, { value: "candle", label: "Candlestick" }],
    "candle",
  );
  assert.match(html, /<option value="line">Line<\/option>/);
  assert.match(html, /<option value="candle" selected>Candlestick<\/option>/);
});

test("inlineOptionsHtml tolerates bare-string options and empty input (#1886)", () => {
  assert.match(H.inlineOptionsHtml(["PASS", "FAIL"], "FAIL"), /<option value="FAIL" selected>FAIL<\/option>/);
  assert.equal(H.inlineOptionsHtml(undefined, ""), "");
  assert.equal(H.inlineOptionsHtml([], ""), "");
});

// --------------------------------------------------------------------------
// #1890 — app switcher moves into a left sidebar (nav buttons, active marked)
// --------------------------------------------------------------------------
test("sidebarAppsHtml builds one nav button per app, marks the active one (#1890)", () => {
  const html = H.sidebarAppsHtml(
    [{ name: "Overview" }, { name: "Terminal" }, { name: "Techtrade" }],
    1,
  );
  assert.equal((html.match(/data-app=/g) || []).length, 3, "one nav entry per app");
  assert.match(html, /data-app="0"[^>]*>Overview</);
  // the active index (1) carries the active class
  assert.match(html, /class="[^"]*active[^"]*"[^>]*data-app="1"[^>]*>Terminal</);
  // non-active entries must NOT be marked active
  assert.doesNotMatch(html, /class="[^"]*active[^"]*"[^>]*data-app="0"/);
});

test("sidebarAppsHtml escapes app names and loud-empties on no apps (#1890)", () => {
  assert.match(H.sidebarAppsHtml([{ name: "<x>&\"" }], 0), /&lt;x&gt;&amp;&quot;/);
  assert.equal(H.sidebarAppsHtml([], 0), "");
  assert.equal(H.sidebarAppsHtml(undefined, 0), "");
});

// --------------------------------------------------------------------------
// #1893 / #1892 — floating grid math: px<->grid snap, clamp, style, merge
// --------------------------------------------------------------------------
test("pxToGridRect rounds pixel rect to grid units (#1893)", () => {
  const geom = { colW: 10, rowH: 30 };
  // left=98 -> 10, top=61 -> 2, width=201 -> 20, height=89 -> 3
  assert.deepEqual(
    { ...H.pxToGridRect({ left: 98, top: 61, width: 201, height: 89 }, geom) },
    { x: 10, y: 2, w: 20, h: 3 },
  );
});

// --------------------------------------------------------------------------
// #1894 — copyable widget reference string (click-to-copy header chip)
// --------------------------------------------------------------------------
test("widgetRefString builds a stable, paste-friendly @id reference (#1894)", () => {
  assert.equal(
    H.widgetRefString(
      "pi_equity_profile",
      "Portfolio Intelligence - Terminal",
      "F1 Overview",
      "Equity Profile",
    ),
    "@pi_equity_profile (app: Portfolio Intelligence - Terminal | tab: F1 Overview | widget: Equity Profile)",
  );
});

test("clampGridItem enforces min size, column bounds, and no negatives (#1892)", () => {
  const opts = { cols: 40, minW: 8, minH: 4 };
  // w below min -> minW; h below min -> minH; negative x -> 0
  assert.deepEqual({ ...H.clampGridItem({ x: -5, y: -3, w: 2, h: 1 }, opts) }, { x: 0, y: 0, w: 8, h: 4 });
  // x pushed so x+w would exceed cols -> x clamped to cols-w
  assert.deepEqual({ ...H.clampGridItem({ x: 39, y: 5, w: 20, h: 9 }, opts) }, { x: 20, y: 5, w: 20, h: 9 });
  // w wider than the grid -> clamped to cols, x -> 0
  assert.deepEqual({ ...H.clampGridItem({ x: 3, y: 0, w: 99, h: 9 }, opts) }, { x: 0, y: 0, w: 40, h: 9 });
});

test("gridItemStyle maps grid units to pixel box (#1893)", () => {
  const geom = { colW: 12, rowH: 30 };
  assert.deepEqual(
    { ...H.gridItemStyle({ x: 2, y: 3, w: 20, h: 9 }, geom) },
    { left: 24, top: 90, width: 240, height: 270 },
  );
});

test("mergeLayout applies saved per-id overrides over apps.json defaults (#1893)", () => {
  const def = [
    { i: "a", x: 0, y: 0, w: 20, h: 9 },
    { i: "b", x: 20, y: 0, w: 20, h: 9 },
  ];
  const merged = H.mergeLayout(def, { b: { x: 0, y: 9, w: 40, h: 12 } });
  const a = merged.find((m) => m.i === "a");
  const b = merged.find((m) => m.i === "b");
  assert.deepEqual({ x: a.x, y: a.y, w: a.w, h: a.h }, { x: 0, y: 0, w: 20, h: 9 }, "unoverridden default unchanged");
  assert.deepEqual({ x: b.x, y: b.y, w: b.w, h: b.h }, { x: 0, y: 9, w: 40, h: 12 }, "override applied");
  // must not mutate the input defaults
  assert.equal(def[1].x, 20, "mergeLayout must not mutate the default layout");
});

test("mergeLayout loud-empties gracefully on missing inputs (#1893)", () => {
  assert.equal(H.mergeLayout(undefined, undefined).length, 0);
  assert.equal(H.mergeLayout([{ i: "a", x: 1, y: 2, w: 3, h: 4 }], undefined).length, 1);
});

// --------------------------------------------------------------------------
// VS Code-style dual side-panel toggles — both the left "Apps" sidebar and
// the right "Copilot" panel must be collapsible, and Copilot defaults hidden.
// These are DOM/localStorage glue (not pure fns) so we guard the contract at
// the source level: a regression that drops a toggle or flips the default
// back to "Copilot visible" fails here rather than silently in the browser.
// --------------------------------------------------------------------------
test("both side panels expose a header toggle AND an in-panel hide button", () => {
  // Left "Apps" sidebar
  assert.match(HTML, /id="side-toggle"/, "left sidebar header toggle must exist");
  assert.match(HTML, /id="side-hide"/, "left sidebar in-panel hide (×) must exist");
  // Right "Copilot" panel
  assert.match(HTML, /id="chat-toggle"/, "Copilot header toggle must exist");
  assert.match(HTML, /id="chat-hide"/, "Copilot in-panel hide (×) must exist");
});

test("both side panels have a collapse CSS rule that zeroes their width", () => {
  assert.match(HTML, /body\.side-collapsed\s+\.sidebar\s*\{[^}]*width:\s*0/, "left collapse rule missing");
  assert.match(HTML, /body\.chat-collapsed\s+\.chat\s*\{[^}]*width:\s*0/, "Copilot collapse rule missing");
});

test("Copilot panel is HIDDEN BY DEFAULT (collapsed unless the user opted in)", () => {
  // The bootstrap must collapse chat whenever the stored pref is not exactly
  // "0" (the only value that means "user pinned it open"). A regression to
  // `=== "1"` (default open) would be caught here.
  assert.match(
    HTML,
    /applyChatCollapsed\(\s*localStorage\.getItem\("viewer:chatCollapsed"\)\s*!==\s*"0"\s*\)/,
    "Copilot must default to collapsed (getItem(...) !== \"0\")",
  );
  // The left sidebar keeps its original default-OPEN behavior (collapse only
  // when the stored pref is exactly "1").
  assert.match(
    HTML,
    /applySideCollapsed\(\s*localStorage\.getItem\("viewer:sideCollapsed"\)\s*===\s*"1"\s*\)/,
    "left sidebar must default to open (=== \"1\" to collapse)",
  );
});

// --------------------------------------------------------------------------
// x-axis date labels — line/candle charts previously drew only the y-axis
// (price) labels, leaving the x-axis (dates) blank so the series had "nothing
// on the x-axis" (user report on pi_equity_price_history). Both renderers must
// now emit x-axis tick <text> labels sourced from model.xLabels. The x-axis
// labels use font-size="9" (y-axis price labels use font-size="10") so the two
// axes are distinguishable in these assertions.
// --------------------------------------------------------------------------
function xAxisLabelTexts(svg) {
  // Collect the text content of every x-axis tick label (font-size="9").
  return [...svg.matchAll(/font-size="9"[^>]*>([^<]+)<\/text>/g)].map((m) => m[1]);
}

test("svgForChart line: renders x-axis date labels from xLabels", () => {
  const rows = [
    { date: "2026-06-01", close: 188 },
    { date: "2026-06-02", close: 190 },
    { date: "2026-06-03", close: 191 },
    { date: "2026-06-04", close: 193 },
  ];
  const model = H.inferChartModel(rows, undefined);
  assert.equal(model.kind, "line");
  const svg = H.svgForChart(model);
  const xLabels = xAxisLabelTexts(svg);
  // The first and last dates must appear as x-axis tick labels (endpoints
  // are always shown so the reader can bound the time domain).
  assert.ok(xLabels.includes("2026-06-01"), `first date missing from x-axis; got ${JSON.stringify(xLabels)}`);
  assert.ok(xLabels.includes("2026-06-04"), `last date missing from x-axis; got ${JSON.stringify(xLabels)}`);
});

test("svgForChart candle: renders x-axis date labels from xLabels", () => {
  const rows = [
    { date: "2026-06-01", open: 188, high: 191, low: 187, close: 190, volume: 1_000_000 },
    { date: "2026-06-02", open: 190, high: 194, low: 189, close: 193, volume: 1_200_000 },
    { date: "2026-06-03", open: 193, high: 195, low: 190, close: 191, volume: 900_000 },
  ];
  const model = H.inferChartModel(rows, undefined);
  assert.equal(model.kind, "candle");
  const svg = H.svgForChart(model);
  const xLabels = xAxisLabelTexts(svg);
  assert.ok(xLabels.includes("2026-06-01"), `first date missing from candle x-axis; got ${JSON.stringify(xLabels)}`);
  assert.ok(xLabels.includes("2026-06-03"), `last date missing from candle x-axis; got ${JSON.stringify(xLabels)}`);
});

test("svgForChart x-axis: dense series is thinned (<= 6 tick labels, endpoints kept)", () => {
  // 30-day daily series must not print 30 overlapping x-axis labels.
  const rows = Array.from({ length: 30 }, (_, i) => ({
    date: `2026-06-${String(i + 1).padStart(2, "0")}`,
    close: 100 + i,
  }));
  const svg = H.svgForChart(H.inferChartModel(rows, undefined));
  const xLabels = xAxisLabelTexts(svg);
  assert.ok(xLabels.length >= 2, `expected at least the two endpoints, got ${xLabels.length}`);
  assert.ok(xLabels.length <= 6, `x-axis labels must be thinned to <= 6, got ${xLabels.length}: ${JSON.stringify(xLabels)}`);
  assert.ok(xLabels.includes("2026-06-01"), "first date must be kept");
  assert.ok(xLabels.includes("2026-06-30"), "last date must be kept");
});

// --------------------------------------------------------------------------
// TradingView Lightweight Charts data mapping — the viewer's PRIMARY
// time-series renderer. inferChartModel(candle|line) must convert into
// LWC-ready {time, open/high/low/close} / {time, value} arrays sourced from
// xLabels, sorted ascending, nulls dropped. These are pure (no DOM), so the
// mapping is fully unit-testable; the DOM wrapper stays thin.
// --------------------------------------------------------------------------
test("isTimeSeriesModel: true for ISO-date candle/line, false for categorical", () => {
  const candle = H.inferChartModel(
    [
      { date: "2026-06-01", open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
      { date: "2026-06-02", open: 1.5, high: 2.5, low: 1, close: 2, volume: 12 },
    ],
    undefined,
  );
  assert.equal(H.isTimeSeriesModel(candle), true);
  // Categorical x-axis (sector names) must NOT route to LWC.
  const cat = H.inferChartModel([{ sector: "Tech", a: 1 }, { sector: "Energy", a: 2 }], undefined);
  assert.equal(H.isTimeSeriesModel(cat), false);
});

test("toLwcSeries candle: maps OHLC+volume from xLabels, sorted ascending", () => {
  // Deliberately supply rows in DESCENDING date order to prove the mapper sorts.
  const model = H.inferChartModel(
    [
      { date: "2026-06-03", open: 193, high: 195, low: 190, close: 191, volume: 900 },
      { date: "2026-06-02", open: 190, high: 194, low: 189, close: 193, volume: 1200 },
      { date: "2026-06-01", open: 188, high: 191, low: 187, close: 190, volume: 1000 },
    ],
    undefined,
  );
  const out = H.toLwcSeries(model);
  assert.equal(out.kind, "candle");
  assert.equal(out.candles.length, 3);
  // Ascending by time
  assert.deepEqual(out.candles.map((c) => c.time), ["2026-06-01", "2026-06-02", "2026-06-03"]);
  // First bar's OHLC comes from the 2026-06-01 row
  assert.deepEqual(
    { o: out.candles[0].open, h: out.candles[0].high, l: out.candles[0].low, c: out.candles[0].close },
    { o: 188, h: 191, l: 187, c: 190 },
  );
  // Volume histogram is separate, colored up/down by that bar's close>=open
  assert.equal(out.volume.length, 3);
  assert.equal(out.volume[0].time, "2026-06-01");
  assert.equal(out.volume[0].value, 1000);
  assert.equal(out.volume[0].color, "#3fb950"); // 190 close >= 188 open -> up
});

test("toLwcSeries line: maps {time,value} per series, drops nulls, sorted", () => {
  const model = H.inferChartModel(
    [
      { date: "2026-06-02", close: 190 },
      { date: "2026-06-01", close: 188 },
      { date: "2026-06-03", close: null },
    ],
    undefined,
  );
  const out = H.toLwcSeries(model);
  assert.equal(out.kind, "line");
  assert.equal(out.lines.length, 1);
  // null close dropped; remaining sorted ascending
  assert.deepEqual(out.lines[0].data.map((p) => p.time), ["2026-06-01", "2026-06-02"]);
  assert.deepEqual(out.lines[0].data.map((p) => p.value), [188, 190]);
});

// #1982 — LWC requires plain unique ascending yyyy-mm-dd times. Feeds like
// analyst price targets carry full ISO datetimes with several rows per day;
// passing those raw makes LWC throw an uncaught "Value is null". toLwcSeries
// must normalize to the day and dedupe (last row per day wins).
test("toLwcSeries line: ISO datetimes normalize to unique ascending yyyy-mm-dd", () => {
  const model = H.inferChartModel(
    [
      { date: "2025-10-31T11:31:29+00:00", target: 246.99 },
      { date: "2025-10-31T13:28:11+00:00", target: 325.0 },
      { date: "2025-10-20T11:04:40+00:00", target: 315.0 },
      { date: "2025-11-03T11:39:17+00:00", target: 325.0 },
    ],
    undefined,
  );
  const out = H.toLwcSeries(model);
  assert.equal(out.kind, "line");
  const times = out.lines[0].data.map((p) => p.time);
  // day-only, unique, ascending
  assert.deepEqual(times, ["2025-10-20", "2025-10-31", "2025-11-03"]);
  assert.equal(new Set(times).size, times.length, "times must be unique");
  // last row of the duplicated day wins (325.0, not 246.99)
  const oct31 = out.lines[0].data.find((p) => p.time === "2025-10-31");
  assert.equal(oct31.value, 325.0);
});

test("toLwcSeries candle: duplicate-day intraday candles dedupe to unique days", () => {
  const model = H.inferChartModel(
    [
      { date: "2026-06-01T09:30:00+00:00", open: 1, high: 2, low: 1, close: 1.5 },
      { date: "2026-06-01T15:59:00+00:00", open: 1.5, high: 3, low: 1.4, close: 2.8 },
      { date: "2026-06-02T10:00:00+00:00", open: 2.8, high: 3.2, low: 2.7, close: 3.0 },
    ],
    undefined,
  );
  const out = H.toLwcSeries(model);
  assert.equal(out.kind, "candle");
  assert.deepEqual(out.candles.map((c) => c.time), ["2026-06-01", "2026-06-02"]);
  // last intraday candle of the day wins its close
  assert.equal(out.candles[0].close, 2.8);
});

// --------------------------------------------------------------------------
// helpText / helpButtonHtml (#1951) — the "?" widget-help affordance.
// helpText resolves the manifest `help` field, falling back to `description`;
// helpButtonHtml emits the button only when there is something to show.
// --------------------------------------------------------------------------
test("helpText prefers help field over description", () => {
  assert.equal(H.helpText({ help: "read me", description: "one-liner" }), "read me");
});

test("helpText falls back to description when help absent", () => {
  assert.equal(H.helpText({ description: "one-liner" }), "one-liner");
});

test("helpText is empty string when neither help nor description present", () => {
  assert.equal(H.helpText({ name: "x" }), "");
  assert.equal(H.helpText(null), "");
});

test("helpButtonHtml emits a ? button only when help text exists", () => {
  const withHelp = H.helpButtonHtml({ help: "### How to read\n- x" });
  assert.match(withHelp, /class="whelp"/);
  assert.match(withHelp, />\?<\/button>/);
  // Load-bearing: no button for an undocumented widget (keeps header clean).
  assert.equal(H.helpButtonHtml({ name: "x" }), "");
});

test("helpButtonHtml renders through mdToHtml to real markup", () => {
  // The popover body is mdToHtml(helpText(def)); prove the manifest help
  // formats as headings + lists rather than raw text.
  const html = H.mdToHtml(H.helpText({ help: "### How to read this chart\n\n- **x-axis** is time\n- **y-axis** is price" }));
  assert.match(html, /<h3>How to read this chart<\/h3>/);
  assert.match(html, /<li><strong>x-axis<\/strong> is time<\/li>/);
});

// dataSourceBadge (#1953) — the live-vs-demo provenance badge. Maps the
// X-PI-Data-Source response header (serving provider tier) to a badge
// descriptor; null when no source is known so the badge stays hidden.
test("dataSourceBadge maps stub to an amber demo badge", () => {
  const b = H.dataSourceBadge("stub");
  assert.equal(b.text, "demo");
  assert.equal(b.cls, "wsrc-demo");
  assert.match(b.title, /NOT live/);
});

test("dataSourceBadge maps a live provider tier to a green live badge", () => {
  const b = H.dataSourceBadge("fmp_cached");
  assert.equal(b.text, "live");
  assert.equal(b.cls, "wsrc-live");
  assert.match(b.title, /fmp_cached/);
});

test("dataSourceBadge treats 'demo' alias like stub (amber, not live)", () => {
  // Guard the stub/demo branch: a mutation collapsing it to the live branch
  // would flip cls to wsrc-live and fail here.
  assert.equal(H.dataSourceBadge("demo").cls, "wsrc-demo");
  assert.equal(H.dataSourceBadge("DEMO").cls, "wsrc-demo");
});

test("dataSourceBadge is null when source header is absent", () => {
  assert.equal(H.dataSourceBadge(null), null);
  assert.equal(H.dataSourceBadge(undefined), null);
  assert.equal(H.dataSourceBadge(""), null);
  assert.equal(H.dataSourceBadge("   "), null);
});

test("dataSourceBadge is case-insensitive for tier names", () => {
  assert.equal(H.dataSourceBadge("FMP_Cached").text, "live");
});

// resolveParams / contextParamLabel (#1954) — the app-level shared context bar.
// A single symbol selection must drive every widget declaring `symbol`, so the
// global value wins over per-widget saved state and widget defaults.
const PH_DEF = { params: [{ paramName: "symbol", value: "AAPL" }, { paramName: "chart_type", value: "line" }] };

test("resolveParams: app-level global wins over saved state and default", () => {
  const out = H.resolveParams(PH_DEF.params, { symbol: "TSLA" }, { symbol: "NVDA" });
  assert.equal(out.symbol, "NVDA");        // global beats the saved TSLA
  assert.equal(out.chart_type, "line");    // untouched -> default
});

test("resolveParams: saved state used when no global for that key", () => {
  const out = H.resolveParams(PH_DEF.params, { symbol: "TSLA" }, {});
  assert.equal(out.symbol, "TSLA");
});

test("resolveParams: widget default used when neither global nor state", () => {
  const out = H.resolveParams(PH_DEF.params, {}, {});
  assert.equal(out.symbol, "AAPL");
  assert.equal(out.chart_type, "line");
});

test("resolveParams: global key the widget does NOT declare never leaks in", () => {
  // A book-scoped widget (only account_id) must not receive the global symbol.
  const bookDef = { params: [{ paramName: "account_id", value: "demo" }] };
  const out = H.resolveParams(bookDef.params, {}, { symbol: "NVDA", account_id: "acct-7" });
  assert.equal(out.account_id, "acct-7");
  assert.ok(!("symbol" in out), "symbol must not appear on a widget that does not declare it");
});

test("resolveParams: empty-string global override is honored (not skipped)", () => {
  const out = H.resolveParams(PH_DEF.params, { symbol: "TSLA" }, { symbol: "" });
  assert.equal(out.symbol, "");
});

// appContextParams (#1270): the context bar is seeded from the schema-native
// parameter groups (apps.json no longer carries a non-schema app `params`).
const APPS = JSON.parse(
  readFileSync(join(__dirname, "..", "..", "..", "..", "..", "extensions", "portfolio_intel", "openbb_portfolio_intel", "widget_backend", "apps.json"), "utf-8")
);

test("appContextParams: ticker group seeds symbol, param groups seed their paramName", () => {
  const app = { groups: [
    { name: "Group 1", type: "ticker", widgetIds: ["a"], defaultValue: "AAPL" },
    { name: "Group 2", type: "param", paramName: "account_id", widgetIds: ["b"], defaultValue: "demo" },
    { name: "Group 3", type: "endpointParam", paramName: "region", widgetIds: ["c"] },
  ] };
  assert.deepEqual({ ...H.appContextParams(app) }, { symbol: "AAPL", account_id: "demo", region: "" });
});

test("appContextParams: first group wins for a repeated param; no groups -> no context", () => {
  const app = { groups: [
    { name: "Group 1", type: "param", paramName: "symbol", widgetIds: ["a"], defaultValue: "MSFT" },
    { name: "Group 2", type: "ticker", widgetIds: ["b"], defaultValue: "AAPL" },
  ] };
  assert.deepEqual({ ...H.appContextParams(app) }, { symbol: "MSFT" });
  assert.deepEqual({ ...H.appContextParams({ params: { symbol: "AAPL" } }) }, {});
  assert.deepEqual({ ...H.appContextParams(null) }, {});
});

test("appContextParams: the shipped Terminal keeps its symbol + account context bar", () => {
  const terminal = APPS.find((a) => a.id === "custom-portfolio-intelligence-terminal");
  assert.deepEqual({ ...H.appContextParams(terminal) }, { symbol: "AAPL", account_id: "demo" });
  const desk = APPS.find((a) => a.id === "custom-techtrade-desk");
  assert.deepEqual({ ...H.appContextParams(desk) }, { symbol: "AAPL" });
});

test("contextParamLabel maps known shared params and title-cases the rest", () => {
  assert.equal(H.contextParamLabel("symbol"), "Symbol");
  assert.equal(H.contextParamLabel("account_id"), "Account");
  assert.equal(H.contextParamLabel("benchmark_symbol"), "Benchmark");
  assert.equal(H.contextParamLabel("some_other_key"), "Some Other Key");
});