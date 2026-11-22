"""Plotly figure adapters for the TechTrade Desk chart widgets (#1271).

The two TechTrade chart widgets read persisted EOD snapshot rows. Like the
Terminal charts (#1268), the endpoints keep computing those rows and
:func:`~openbb_portfolio_intel.widget_backend.terminal_charts.plotly_chart`
serves them as a Plotly figure by default and as rows with ``raw=true``.
The builders here only re-shape: every plotted value is a row value,
unscaled.

Every figure carries the snapshot provenance in ``layout.meta`` and, unless
live, a header annotation (``finish``); a footnote repeats the snapshot
disclaimer (an EOD planning snapshot, not a live quote) and any
survivorship or earnings warning the rows carry. No figure sets
``layout.title``. These widgets are read-only views: nothing here places,
writes or cancels an order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openbb_portfolio_intel.widget_backend.overview_charts import (
    Figure,
    finish,
    unavailable_figure,
)
from openbb_portfolio_intel.widget_backend.provenance import DataState
from openbb_portfolio_intel.widget_backend.terminal_charts import ChartContext, Rows

#: ``plotly_chart`` demo reason. TechTrade widgets never serve sample data:
#: every response is marked from the snapshot store, so this is never shown.
NO_DEMO = "TechTrade widgets read persisted snapshots only; no sample data"
_FOOTNOTE_FIELDS = ("disclaimer", "survivorship", "earnings_annotation")


def snapshot_footnote(rows: Rows) -> dict[str, Any] | None:
    """Return a footnote annotation with the snapshot warnings, if any."""
    first: Mapping[str, Any] = rows[0] if rows else {}
    parts = [str(first[field]) for field in _FOOTNOTE_FIELDS if first.get(field)]
    if not parts:
        return None
    return {
        "text": " · ".join(parts),
        "xref": "paper",
        "yref": "paper",
        "x": 0,
        "y": -0.25,
        "xanchor": "left",
        "yanchor": "top",
        "showarrow": False,
        "font": {"size": 10},
    }


def _finish(
    traces: list[dict[str, Any]], rows: Rows, ctx: ChartContext, **extra: Any
) -> Figure:
    footnote = snapshot_footnote(rows)
    if footnote:
        extra["annotations"] = [footnote]
        extra["margin"] = {"b": 90}
    return finish(traces, ctx.provenance, **extra)


def _guard(rows: Rows, ctx: ChartContext, what: str) -> Figure | None:
    if ctx.provenance.state is DataState.UNAVAILABLE or not rows:
        return unavailable_figure(ctx.provenance, what)
    return None


def segment_movers_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Plot the strongest mover per segment as bars of its percent change.

    Rows are ``{segment, symbol, change_pct, bucket}`` (one per segment, the
    largest absolute move); the bar label names the symbol.
    """
    early = _guard(rows, ctx, "segment movers")
    if early:
        return early
    trace = {
        "type": "bar",
        "name": "Change (%)",
        "x": [row["segment"] for row in rows],
        "y": [row["change_pct"] for row in rows],
        "text": [row["symbol"] for row in rows],
        "textposition": "outside",
        "hovertemplate": (
            "%{x}<br>Strongest mover: %{text}<br>Change: %{y:+.2f}%" "<extra></extra>"
        ),
    }
    return _finish(
        [trace],
        rows,
        ctx,
        xaxis={"type": "category", "title": {"text": "Segment"}},
        yaxis={"title": {"text": "Change (%)"}, "zeroline": True},
        showlegend=False,
    )


def simulate_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Plot the marked P&L of the simulated fills by simulation day.

    Rows are the ``techtrade.simulate`` snapshot rows ``{symbol, segment, day,
    timestamp, price, pnl, source}``; P&L is in account currency, marked at
    each fill price. One line per segment the symbol was planned in.
    """
    # Only complete rows are plotted: an exclusion or marker row carries no
    # ``day``/``pnl`` (#1271 review).
    rows = [
        row
        for row in rows
        if isinstance(row.get("day"), int | float)
        and isinstance(row.get("pnl"), int | float)
    ]
    early = _guard(rows, ctx, "simulation fills")
    if early:
        return early
    by_segment: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_segment.setdefault(str(row.get("segment") or ""), []).append(row)
    several = len(by_segment) > 1
    symbol = str(rows[0].get("symbol") or ctx.symbol)
    traces = [
        {
            "type": "scatter",
            "mode": "lines+markers",
            "name": (
                f"{symbol} marked P&L ({segment})"
                if several
                else f"{symbol} marked P&L"
            ),
            "x": [row["day"] for row in segment_rows],
            "y": [row["pnl"] for row in segment_rows],
            "hovertemplate": ("Day %{x}<br>Marked P&L: %{y:,.2f}<extra></extra>"),
        }
        for segment, segment_rows in by_segment.items()
    ]
    return _finish(
        traces,
        rows,
        ctx,
        xaxis={"title": {"text": "Simulation day"}},
        yaxis={"title": {"text": "Marked P&L (account currency)"}},
    )
