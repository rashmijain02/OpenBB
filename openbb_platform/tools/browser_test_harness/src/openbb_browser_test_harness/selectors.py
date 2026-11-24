"""Workspace selector graph (B10, #1735).

Maps ``widget_id`` -> a Playwright locator selector so ``WorkspaceDriver``
can turn ``widget_visible`` and ``not_blank`` from ``"unverified"`` sentinels
into real UI assertions.

Design principle
----------------

The Workspace UI wraps every widget in a container carrying
``data-widget-id="<widget_id>"`` (the same identifier the backend serves
in ``widgets.json``). Inside each container the render is a table, chart,
markdown block, or metric card — one of four shapes determined by the
widget's ``type`` field.

We therefore build the selector graph in **two layers**:

1. **Container selector** (uniform across widgets):
   ``[data-widget-id="<widget_id>"]``
2. **Content selector** (dispatched by widget type):

   ==========  =====================================================
   type        content-not-blank selector (rooted inside container)
   ==========  =====================================================
   table       ``role=table`` OR ``table`` OR ``[data-testid=table]``
   chart       ``canvas`` OR ``svg`` OR ``[data-testid=chart]``
   markdown    ``[data-testid=markdown-body]`` OR any ``> *`` with text
   metric      ``[data-testid=metric-value]`` OR ``[class*=metric]``
   ==========  =====================================================

If a specific widget's DOM diverges from the type default, register an
override in ``_WIDGET_ID_OVERRIDES`` and the graph respects it.

Why not per-widget CSS classes
-------------------------------

Workspace ships a shared component library — every ``table`` widget uses
the same table component, every ``chart`` widget uses the same chart
component. Encoding type-based defaults keeps the graph small
(N ≈ 4 lines instead of N ≈ 60 lines) and the failure mode is loud: if
Workspace changes the container attribute name from ``data-widget-id`` to
``data-widget-slug``, EVERY widget fails at once, immediately flagging
the migration. That's the invariant we want.

Self-hosted Workspace (#1274)
-----------------------------

The real self-hosted Workspace run showed that ``data-widget-id`` on each
grid item is a **per-instance UUID** (``routes/tab.tsx`` renders
``data-widget-id={layout.i}``), so ``[data-widget-id="pi_xray_sector"]``
never matched and every step reported ``widget_visible=False``. The pinned
Workspace source exposes the backend id elsewhere:

- the widget card root carries the class ``widget-<backend widget id>``
  (``DraggableCard.tsx``; ``widgetId`` is the ``widgets.json`` key,
  ``backendConnector.ts``);
- the title is ``._left-navbar p.font-semibold`` with the widget ``name``;
- the body is ``#widget-content-<uuid>``; Plotly mounts ``.js-plotly-plot``
  / ``svg.main-svg`` there only when the figure has a trace.

:data:`RENDERED_WIDGETS_JS` reads one record per grid item
(:class:`RenderedWidget`); :func:`match_rendered` maps a backend widget to
its rendered item by the ``widget-<id>`` class, the legacy
``data-widget-id`` equal to the backend id, or the exact title, in that
order; :func:`judge_rendered` decides visible and not-blank from the
record. :func:`parse_rendered_widgets` applies the same rules to static
HTML so the mapping is unit-tested on a captured DOM fixture.

This module is import-safe with or without Playwright installed — it only
returns strings and plain records.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------
# Public data
# ----------------------------------------------------------------------

CONTAINER_ATTR: str = "data-widget-id"
"""Attribute Workspace puts on every widget container."""


_TYPE_CONTENT_SELECTORS: dict[str, tuple[str, ...]] = {
    "table": (
        "[role='table']",
        "table",
        "[data-testid='widget-table']",
    ),
    "chart": (
        "canvas",
        "svg",
        "[data-testid='widget-chart']",
    ),
    "markdown": (
        "[data-testid='markdown-body']",
        "[data-testid='widget-markdown']",
        ".markdown-body",
    ),
    "metric": (
        "[data-testid='metric-value']",
        "[class*='metric']",
        "[data-testid='widget-metric']",
    ),
}
"""Ordered content-selector candidates per widget type.

The driver iterates them and considers the widget non-blank if ANY match
has non-empty ``innerText`` or non-zero bounding-box area.
"""

# Per-widget-id overrides for widgets whose DOM doesn't match its type default.
# Empty at launch — file an entry here when a widget's render is bespoke and
# has a stable ``data-testid`` we can pin.
_WIDGET_ID_OVERRIDES: dict[str, tuple[str, ...]] = {
    # example (currently unused, kept as documentation):
    # "pi_charting": ("[data-testid='trading-view-frame']",),
}


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class WidgetSelector:
    """Resolved selectors for a single widget."""

    widget_id: str
    widget_type: str  # "table" | "chart" | "markdown" | "metric"
    container: str  # e.g. '[data-widget-id="pi_xray_sector"]'
    content_candidates: tuple[str, ...]
    """Content selectors to try inside the container, in priority order."""
    name: str = ""
    """Widget title from ``widgets.json`` (``name``), the title fallback."""


def container_selector(widget_id: str) -> str:
    """Return the Playwright selector for a widget's container."""
    # Quote for CSS attribute selectors; widget_ids in Workspace are
    # ``[a-z0-9_]``, but defensively escape any double-quotes.
    safe = widget_id.replace('"', r"\"")
    return f'[{CONTAINER_ATTR}="{safe}"]'


def content_selectors_for_type(widget_type: str) -> tuple[str, ...]:
    """Return content-not-blank selector candidates for the given type.

    Unknown types fall back to the union of the four defaults so we never
    return an empty tuple (silent failure).
    """
    known = _TYPE_CONTENT_SELECTORS.get(widget_type)
    if known:
        return known
    all_defaults: list[str] = []
    for sels in _TYPE_CONTENT_SELECTORS.values():
        all_defaults.extend(sels)
    return tuple(all_defaults)


def resolve(widget_id: str, widget_type: str, name: str = "") -> WidgetSelector:
    """Build a fully-resolved WidgetSelector for a widget id + type.

    Overrides in ``_WIDGET_ID_OVERRIDES`` take precedence over the type
    default.
    """
    if widget_id in _WIDGET_ID_OVERRIDES:
        content = _WIDGET_ID_OVERRIDES[widget_id]
    else:
        content = content_selectors_for_type(widget_type)
    return WidgetSelector(
        widget_id=widget_id,
        widget_type=widget_type,
        container=container_selector(widget_id),
        content_candidates=content,
        name=name,
    )


# ----------------------------------------------------------------------
# widgets.json -> endpoint->widget-selector index
# ----------------------------------------------------------------------


def _widgets_manifest_path() -> Path:
    """Absolute path to the extension's widgets.json.

    Layout (from ``src/openbb_browser_test_harness/selectors.py``):

        parents[0] = openbb_browser_test_harness/
        parents[1] = src/
        parents[2] = browser_test_harness/
        parents[3] = tools/
        parents[4] = openbb_platform/  <- widgets.json lives under here
    """
    return (
        Path(__file__).resolve().parents[4]
        / "extensions"
        / "portfolio_intel"
        / "openbb_portfolio_intel"
        / "widget_backend"
        / "widgets.json"
    )


@lru_cache(maxsize=1)
def load_endpoint_to_widget_selector() -> dict[str, WidgetSelector]:
    """Return endpoint -> WidgetSelector for every widget in the manifest.

    A step's ``endpoint`` field is the join key. The driver looks up the
    selector by endpoint (steps carry endpoint, not widget_id, in the
    current story model).

    Returns:
        Mapping from endpoint (str) to WidgetSelector.
    """
    manifest = json.loads(_widgets_manifest_path().read_text(encoding="utf-8"))
    out: dict[str, WidgetSelector] = {}
    for widget_id, spec in manifest.items():
        endpoint = spec.get("endpoint")
        widget_type = spec.get("type", "unknown")
        if not endpoint:
            continue
        # A single endpoint may back multiple widgets (rare in this
        # backend but possible). Keep the FIRST binding; test asserts
        # this is unambiguous.
        if endpoint not in out:
            out[endpoint] = resolve(widget_id, widget_type, str(spec.get("name") or ""))
    return out


def selector_for_endpoint(endpoint: str) -> WidgetSelector | None:
    """Look up the WidgetSelector backing an endpoint, or None."""
    return load_endpoint_to_widget_selector().get(endpoint)


# ----------------------------------------------------------------------
# Self-hosted Workspace: map backend widget ids to rendered widgets (#1274)
# ----------------------------------------------------------------------

#: Class prefix the card root carries with the backend widget id.
CARD_CLASS_PREFIX = "widget-"
#: Widget body (``id="widget-content-<uuid>"``).
BODY_ID_PREFIX = "widget-content-"

RENDERED_WIDGETS_JS = """() => [...document.querySelectorAll('[data-widget-id]')]
  .map((item) => {
    const box = item.getBoundingClientRect();
    const ids = new Set();
    for (const el of [item, ...item.querySelectorAll('[class*="widget-"]')]) {
      for (const token of el.classList) {
        if (token.startsWith('widget-') && token.length > 7) ids.add(token.slice(7));
      }
    }
    const title = item.querySelector('._left-navbar p.font-semibold');
    const body = item.querySelector('[id^="widget-content-"]');
    return {
      uid: item.getAttribute('data-widget-id') || '',
      widget_ids: [...ids],
      title: title ? title.textContent.trim() : '',
      width: box.width,
      height: box.height,
      body_text: body ? body.innerText.trim().length : 0,
      plots: body ? body.querySelectorAll(
        '.js-plotly-plot, svg.main-svg, canvas').length : 0,
      tables: body ? body.querySelectorAll(
        "[role='grid'], [role='table'], table, .ag-root").length : 0,
    };
  })"""
"""Playwright ``page.evaluate`` source returning one record per grid item."""


@dataclass(frozen=True)
class RenderedWidget:  # pylint: disable=too-many-instance-attributes
    """What the live DOM shows for one grid item."""

    uid: str
    widget_ids: tuple[str, ...] = ()
    title: str = ""
    width: float = 0.0
    height: float = 0.0
    body_text: int = 0
    plots: int = 0
    tables: int = 0

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> RenderedWidget:
        """Build from a :data:`RENDERED_WIDGETS_JS` record."""
        return cls(
            uid=str(record.get("uid") or ""),
            widget_ids=tuple(str(i) for i in record.get("widget_ids") or ()),
            title=str(record.get("title") or ""),
            width=float(record.get("width") or 0),
            height=float(record.get("height") or 0),
            body_text=int(record.get("body_text") or 0),
            plots=int(record.get("plots") or 0),
            tables=int(record.get("tables") or 0),
        )


def _norm(text: str) -> str:
    return " ".join(text.split())


def match_rendered(
    selector: WidgetSelector, rendered: Iterable[RenderedWidget]
) -> tuple[RenderedWidget | None, str]:
    """Return the rendered item for a backend widget and how it matched.

    Order: the card class ``widget-<id>``, then a legacy ``data-widget-id``
    equal to the backend id, then the exact widget title. Among several
    matches the first with a non-zero box wins. ``(None, "none")`` when the
    widget is not on the page.
    """
    items = list(rendered)
    name = _norm(selector.name)
    rules = (
        ("card-class", lambda r: selector.widget_id in r.widget_ids),
        ("data-widget-id", lambda r: r.uid == selector.widget_id),
        ("title", lambda r: bool(name) and _norm(r.title) == name),
    )
    for how, rule in rules:
        hits = [r for r in items if rule(r)]
        if hits:
            sized = [r for r in hits if r.width > 0 and r.height > 0]
            return (sized or hits)[0], how
    return None, "none"


def judge_rendered(
    selector: WidgetSelector, item: RenderedWidget | None
) -> tuple[bool, bool]:
    """Return ``(visible, not_blank)`` for a matched item.

    Visible needs a non-zero box. Not blank is per type: a chart needs a
    mounted plot (Workspace mounts none for ``data: []``), a table a grid,
    markdown and metric body text; unknown types accept any of these.
    """
    if item is None or item.width <= 0 or item.height <= 0:
        return False, False
    checks = {
        "chart": item.plots > 0,
        "table": item.tables > 0,
        "markdown": item.body_text > 0,
        "metric": item.body_text > 0,
    }
    fallback = item.plots > 0 or item.tables > 0 or item.body_text > 0
    return True, checks.get(selector.widget_type, fallback)


_VOID = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[Any] = field(default_factory=list)

    @property
    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()

    def walk(self) -> Iterable[_Node]:
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.root = _Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _is_plot(node: _Node) -> bool:
    return (
        "js-plotly-plot" in node.classes
        or (node.tag == "svg" and "main-svg" in node.classes)
        or node.tag == "canvas"
    )


def _is_table(node: _Node) -> bool:
    return (
        node.attrs.get("role") in ("grid", "table")
        or node.tag == "table"
        or "ag-root" in node.classes
    )


def _title(item: _Node) -> str:
    for navbar in item.walk():
        if "_left-navbar" in navbar.classes:
            for node in navbar.walk():
                if node.tag == "p" and "font-semibold" in node.classes:
                    return node.text().strip()
            return ""
    return ""


def parse_rendered_widgets(html: str) -> list[RenderedWidget]:
    """Apply the :data:`RENDERED_WIDGETS_JS` rules to static HTML.

    A captured DOM has no layout, so the box comes from ``data-test-width``
    / ``data-test-height`` attributes on the grid item (default 0: hidden).
    """
    builder = _TreeBuilder()
    builder.feed(html)
    out = []
    for item in builder.root.walk():
        if "data-widget-id" not in item.attrs:
            continue
        ids: list[str] = []
        body: _Node | None = None
        for node in item.walk():
            for token in node.classes:
                if token.startswith(CARD_CLASS_PREFIX) and len(token) > 7:
                    ids.append(token[len(CARD_CLASS_PREFIX) :])
            if body is None and node.attrs.get("id", "").startswith(BODY_ID_PREFIX):
                body = node
        nodes = list(body.walk()) if body is not None else []
        out.append(
            RenderedWidget(
                uid=item.attrs["data-widget-id"],
                widget_ids=tuple(dict.fromkeys(ids)),
                title=_title(item),
                width=float(item.attrs.get("data-test-width", 0)),
                height=float(item.attrs.get("data-test-height", 0)),
                body_text=len(body.text().strip()) if body is not None else 0,
                plots=sum(1 for n in nodes if _is_plot(n)),
                tables=sum(1 for n in nodes if _is_table(n)),
            )
        )
    return out


@lru_cache(maxsize=1)
def load_widget_tabs() -> dict[str, dict[str, str]]:
    """Return ``{app name: {widget id: tab name}}`` from ``apps.json``."""
    path = _widgets_manifest_path().with_name("apps.json")
    apps = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for app in apps:
        tabs = out.setdefault(str(app.get("name") or ""), {})
        for tab in (app.get("tabs") or {}).values():
            for item in tab.get("layout") or []:
                tabs.setdefault(str(item.get("i")), str(tab.get("name") or ""))
    return out
