"""Plotly figure adapters for the Portfolio Overview chart widgets (#1267).

Workspace renders a ``type: chart`` endpoint's default response as a Plotly
figure (``{"data": [...], "layout": {...}}``). These pure functions turn the
rows the endpoints already compute into that figure. They add no financial
math: every plotted value is a row value, unchanged.

Every figure carries its provenance record in ``layout.meta`` (state,
source, as-of and reason, #1269) and, for every state except ``live``, shows
it in an annotation, so demo, partial and unavailable figures cannot be
mistaken for real data. An unavailable figure has no traces; the annotation
explains why. Figures never set ``layout.title``: Workspace shows the widget
name as the title (#1268).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from openbb_portfolio_intel.widget_backend.provenance import (
    DataState,
    Provenance,
    with_state,
)

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


def layout(provenance: Provenance, **extra: Any) -> dict[str, Any]:
    """Return a title-free layout whose ``meta`` is the provenance record."""
    return {"meta": provenance.meta(), **extra}


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


def state_figure(provenance: Provenance, message: str | None = None) -> Figure:
    """Return a trace-free figure that states why there is nothing to plot."""
    return {
        "data": [],
        "layout": layout(
            provenance,
            annotations=[note(message or f"{provenance.summary()}.")],
            xaxis={"visible": False},
            yaxis={"visible": False},
        ),
    }


def unavailable_figure(provenance: Provenance, what: str) -> Figure:
    """Return the unavailable figure, or turn an empty result into one.

    An empty result for valid parameters is not a success: it becomes
    ``unavailable`` with the reason, keeping the source that answered.
    """
    if provenance.state is not DataState.UNAVAILABLE:
        provenance = with_state(
            provenance,
            DataState.UNAVAILABLE,
            f"no {what} returned for these parameters",
        )
    return state_figure(provenance, f"Unavailable: no {what}, {provenance.reason}.")


def finish(
    traces: list[dict[str, Any]], provenance: Provenance, **extra: Any
) -> Figure:
    """Return a figure; every state but ``live`` also gets a header annotation."""
    if provenance.state is not DataState.LIVE:
        extra["annotations"] = [
            *extra.get("annotations", []),
            header_note(f"{provenance.summary()}."),
        ]
    return {"data": traces, "layout": layout(provenance, **extra)}


def weight_pie(rows: Sequence[Mapping[str, Any]], label: str, name: str) -> dict:
    """Return a weight pie whose hover shows each stored weight (#1269).

    ``%{percent}`` is only the share of the plotted total; with partial or
    unnormalised weights it differs from the stored weight, so the hover
    always shows both.
    """
    return {
        "type": "pie",
        "name": name,
        "labels": [row[label] for row in rows],
        "values": [row["weight"] for row in rows],
        "sort": False,
        "hovertemplate": (
            "%{label}<br>Weight: %{value:.1%} of the book"
            "<br>Share of chart: %{percent}<extra></extra>"
        ),
    }


def xray_sector_figure(
    rows: Sequence[Mapping[str, Any]], provenance: Provenance
) -> Figure:
    """Return a sector-weight pie from ``{sector, weight}`` rows."""
    if provenance.state is DataState.UNAVAILABLE or not rows:
        return unavailable_figure(provenance, "sector data")
    return finish(
        [weight_pie(rows, "sector", "Sector Weight")],
        provenance,
        legend={"title": {"text": "Sector"}},
    )


def brinson_attribution_figure(
    rows: Sequence[Mapping[str, Any]], provenance: Provenance
) -> Figure:
    """Return the Brinson-Fachler effects per sector, in percentage points.

    Allocation, selection, and interaction are stacked bars (``relative``
    barmode, so negative effects stack below zero); total active return is a
    marker series. The book is the synthetic Brinson reference fixture, which
    the demo annotation says, together with the window and benchmark.
    """
    if not rows:
        return unavailable_figure(provenance, "attribution rows")
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
    return finish(
        traces,
        provenance,
        barmode="relative",
        xaxis={"title": {"text": "Sector"}},
        yaxis={"title": {"text": "Effect (percentage points)"}},
    )
