"""Plotly figure adapters for the Portfolio Overview chart widgets (#1267).

Workspace renders a ``type: chart`` endpoint's default response as a Plotly
figure (``{"data": [...], "layout": {...}}``). These pure functions turn the
rows the endpoints already compute into that figure. They add no financial
math: every plotted value is a row value, unchanged.

Every figure carries its data state in ``layout.meta.state`` and shows it in
an annotation, so demo, empty, and unavailable states are visible rather than
looking like real data. An empty or unavailable figure has no traces; the
annotation explains why. Figures never set ``layout.title``: Workspace shows
the widget name as the title (#1268).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

Figure = dict[str, Any]

# (row field, series label, viewer glossary key, one-line definition).
# The definitions mirror the Local Viewer glossary summaries so Workspace
# users get the same help in the hover text.
BRINSON_SERIES: tuple[tuple[str, str, str, str], ...] = (
    (
        "allocation",
        "Allocation Effect (%)",
        "allocation_effect",
        "Attribution from benchmark-relative segment weights.",
    ),
    (
        "selection",
        "Selection Effect (%)",
        "selection_effect",
        "Attribution from security selection within segments.",
    ),
    (
        "interaction",
        "Interaction Effect (%)",
        "interaction_effect",
        "Combined allocation and selection attribution effect.",
    ),
    (
        "total",
        "Total Active Return (%)",
        "total_active_return",
        "Portfolio return minus benchmark return.",
    ),
)


def layout(state: str, *, source: str | None = None, **extra: Any) -> dict[str, Any]:
    """Return a title-free layout that records the data state (and source)."""
    meta: dict[str, Any] = {"state": state}
    if source is not None:
        meta["source"] = source
    return {"meta": meta, **extra}


def note(text: str) -> dict[str, Any]:
    """Return a centred paper-space annotation for state messages."""
    return {
        "text": text,
        "xref": "paper",
        "yref": "paper",
        "x": 0.5,
        "y": 0.5,
        "showarrow": False,
    }


def header_note(text: str) -> dict[str, Any]:
    """Return a state annotation placed above the plot area."""
    return {**note(text), "y": 1.08}


def state_figure(state: str, message: str, *, source: str | None = None) -> Figure:
    """Return a trace-free figure that states why there is nothing to plot."""
    return {
        "data": [],
        "layout": layout(
            state,
            source=source,
            annotations=[note(message)],
            xaxis={"visible": False},
            yaxis={"visible": False},
        ),
    }


def xray_sector_figure(
    rows: Sequence[Mapping[str, Any]], *, state: str, label: str
) -> Figure:
    """Return a sector-weight pie from ``{sector, weight}`` rows.

    ``label`` names the book (e.g. the synthetic demo portfolio) in a header
    annotation, since the figure carries no title.
    """
    if not rows:
        return state_figure("empty", "No sector weights returned.")
    return {
        "data": [
            {
                "type": "pie",
                "name": "Sector Weight",
                "labels": [row["sector"] for row in rows],
                "values": [row["weight"] for row in rows],
                "sort": False,
                "hovertemplate": "%{label}<br>Weight: %{percent}<extra></extra>",
            }
        ],
        "layout": layout(
            state,
            legend={"title": {"text": "Sector"}},
            annotations=[header_note(label)],
        ),
    }


def brinson_attribution_figure(
    rows: Sequence[Mapping[str, Any]], *, window: str, benchmark_symbol: str
) -> Figure:
    """Return the Brinson-Fachler effects per sector, in percentage points.

    Allocation, selection, and interaction are stacked bars (``relative``
    barmode, so negative effects stack below zero); total active return is a
    marker series. The book is the synthetic Brinson reference fixture, which
    an annotation says, together with the window and benchmark.
    """
    book = f"Synthetic demo book, {window} vs {benchmark_symbol}; not your portfolio."
    if not rows:
        return state_figure("empty", f"No attribution rows were produced. {book}")
    sectors = [row["sector"] for row in rows]
    traces: list[dict[str, Any]] = []
    for field, label, glossary_key, summary in BRINSON_SERIES:
        trace: dict[str, Any] = {
            "type": "bar" if field != "total" else "scatter",
            "name": label,
            "x": sectors,
            "y": [row[field] for row in rows],
            "meta": {"glossaryKey": glossary_key},
            "hovertemplate": (
                f"%{{x}}<br>{label}: %{{y:.3f}} pp<br>{summary}<extra></extra>"
            ),
        }
        if field == "total":
            trace["mode"] = "markers"
            trace["marker"] = {"symbol": "diamond", "size": 10}
        traces.append(trace)
    return {
        "data": traces,
        "layout": layout(
            "demo",
            barmode="relative",
            xaxis={"title": {"text": "Sector"}},
            yaxis={"title": {"text": "Effect (percentage points)"}},
            annotations=[header_note(book)],
        ),
    }
