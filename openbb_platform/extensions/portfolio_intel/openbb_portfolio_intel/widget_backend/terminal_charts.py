"""Plotly figure adapters for the Terminal chart widgets (#1268).

Workspace renders a ``type: chart`` endpoint's default response as a Plotly
figure. The chart endpoints keep computing the rows they always did;
:func:`plotly_chart` wraps each one so the default response is a figure
built from those rows and ``raw=true`` returns the rows. The figure builders
only re-shape: every plotted value is a row value, unscaled.

Each figure carries the request's provenance record in ``layout.meta``
(``state``, ``source``, ``asOf``, ``reason``; #1269) and never sets
``layout.title`` (Workspace shows the widget name). Every state except
``live`` is also written into an annotation. ``raw=true`` rows carry the
same record as three string columns (``data_state``, ``data_source``,
``data_as_of``), so agents reading rows see it too. Trace
``meta.glossaryKey`` names the Local Viewer glossary record, and the hover
text repeats that record's one-line summary.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from openbb_portfolio_intel.widget_backend import provenance as pv
from openbb_portfolio_intel.widget_backend.overview_charts import (
    Figure,
    brinson_attribution_figure,
    finish,
    unavailable_figure,
    weight_pie,
    xray_sector_figure,
)
from openbb_portfolio_intel.widget_backend.provenance import (
    DataState,
    Provenance,
    with_state,
)

Rows = Sequence[Mapping[str, Any]]
STUB = pv.STUB


@dataclass(frozen=True)
class ChartContext:
    """What a figure builder knows besides the rows."""

    params: Mapping[str, Any]
    provenance: Provenance

    @property
    def source(self) -> str:
        """Return the tier or source that served the rows."""
        return self.provenance.source

    @property
    def symbol(self) -> str:
        """Return the normalized ticker parameter (validated upstream)."""
        return str(self.params.get("symbol", "")).strip().upper()


ChartBuilder = Callable[[Rows, ChartContext], Figure]
#: Demo reason, fixed or computed from the endpoint's bound parameters.
DemoReason = str | Callable[[Mapping[str, Any]], str]
#: Optional re-assessment of the record from the rows (e.g. partial weights).
Assess = Callable[[Rows, Provenance], Provenance]


def plotly_chart(
    build: ChartBuilder, *, demo: DemoReason, assess: Assess | None = None
) -> Callable[[Callable[..., Any]], Any]:
    """Serve a row endpoint as a Plotly figure, keeping rows for ``raw=true``.

    The wrapped function's rows are first validated and serialized through its
    declared return annotation, exactly as FastAPI's inferred response model
    did before #1268, so raw row values keep their JSON types. The wrapper
    adds a ``raw`` query parameter and drops the return annotation, so FastAPI
    infers no response model that would reject the figure.

    The request's provenance (tier, explicit mark, or ``demo``) is resolved
    once; no rows means ``unavailable``; ``assess`` may refine it (partial).
    The figure and the raw rows carry that same record, and it is published
    for the response headers.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func, eval_str=True)
        annotation = signature.return_annotation
        adapter = (
            None if annotation is inspect.Signature.empty else TypeAdapter(annotation)
        )

        @functools.wraps(func)
        def wrapper(*args: Any, raw: bool = False, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)
            with pv.scope() as holder:
                rows = func(*args, **kwargs)
                if adapter is not None:
                    rows = adapter.dump_python(
                        adapter.validate_python(rows), mode="json"
                    )
                reason = demo(params) if callable(demo) else demo
                record, withheld = pv.gate_demo(
                    pv.resolve(holder, demo=reason),
                    explicit=holder.marked is not None or pv.explicit_demo(params),
                )
                if withheld:
                    rows = []
                elif not rows and record.state is not DataState.UNAVAILABLE:
                    record = with_state(
                        record, DataState.UNAVAILABLE, "no rows were returned"
                    )
                elif assess is not None:
                    record = assess(rows, record)
                if raw:
                    pv.publish(record)
                    if not rows:
                        return [pv.unavailable_row(record)]
                    return pv.stamp_rows(rows, record)
                figure = build(rows, ChartContext(params, record))
                pv.publish(Provenance.from_meta(figure["layout"]["meta"]))
                return figure

        raw_param = inspect.Parameter(
            "raw", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool
        )
        setattr(
            wrapper,
            "__signature__",
            signature.replace(
                parameters=[*signature.parameters.values(), raw_param],
                return_annotation=inspect.Signature.empty,
            ),
        )
        return wrapper

    return decorator


def weights_assess(field: str, *, whole: float = 1.0, of: str = "the book") -> Assess:
    """Mark a weight pie ``partial`` when its weights do not sum to ``whole``.

    The pie's ``%{percent}`` is the share of the plotted total, so with
    partial or unnormalised weights it is not the stored weight; the state
    says so and the hover shows each stored value.
    """

    def assess(rows: Rows, record: Provenance) -> Provenance:
        if record.state is DataState.UNAVAILABLE:
            return record
        total = sum(
            float(row[field])
            for row in rows
            if isinstance(row.get(field), int | float)
            and not isinstance(row.get(field), bool)
        )
        if abs(total - whole) <= 0.005 * whole:
            return record
        return with_state(
            record,
            DataState.PARTIAL,
            f"weights sum to {total / whole:.1%} of {of}, so slice shares are of "
            "the plotted total; hover shows each stored weight "
            f"({record.state.value} data: {record.reason})",
        )

    return assess


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

# Glossary key -> the Local Viewer record's one-line summary (index.html).
GLOSSARY_SUMMARY: dict[str, str] = {
    "closing_price": "Last regular-session traded price.",
    "analyst_price_target": "Analyst forecast of a future share price.",
    "twenty_day_volatility": "Annualized volatility from a rolling 20-day window.",
    "sixty_day_volatility": "Annualized volatility from a rolling 60-day window.",
    "portfolio_equity": "Net market value of the portfolio account.",
    "revenue_b": "Annual sales expressed in billions of dollars.",
    "net_income_b": (
        "Annual profit after expenses, taxes, and interest, shown in billions."
    ),
    "net_margin_pct": "Net income as a percentage of revenue.",
    "volume": "The number of shares traded during a period.",
}

#: Demo reason for the synthetic book (#1269).
DEMO_BOOK = "demo portfolio (synthetic); not your account"


def demo_symbol(params: Mapping[str, Any]) -> str:
    """Return the demo reason for sample symbol data."""
    symbol = str(params.get("symbol", "")).strip().upper()
    return (
        "no live provider answered, so these are sample values, "
        f"not live {symbol} data"
    )


def _guard(rows: Rows, ctx: ChartContext, *, what: str) -> Figure | None:
    """Return the unavailable figure when there is nothing real to plot."""
    if ctx.provenance.state is DataState.UNAVAILABLE or not rows:
        return unavailable_figure(ctx.provenance, what)
    return None


def _finish(traces: list[dict[str, Any]], ctx: ChartContext, **extra: Any) -> Figure:
    return finish(traces, ctx.provenance, **extra)


def _line(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    rows: Rows,
    x: str,
    field: str,
    name: str,
    glossary_key: str | None,
    value_format: str,
    **extra: Any,
) -> dict[str, Any]:
    summary = GLOSSARY_SUMMARY.get(glossary_key or "", "")
    trace: dict[str, Any] = {
        "type": "scatter",
        "mode": "lines",
        "name": name,
        "x": [row[x] for row in rows],
        "y": [row[field] for row in rows],
        "hovertemplate": (
            f"%{{x}}<br>{name}: {value_format}"
            + (f"<br>{summary}" if summary else "")
            + "<extra></extra>"
        ),
        **extra,
    }
    if glossary_key:
        trace["meta"] = {"glossaryKey": glossary_key}
    return trace


def _pie(rows: Rows, label: str, value: str, name: str, hover: str) -> dict:
    return {
        "type": "pie",
        "name": name,
        "labels": [row[label] for row in rows],
        "values": [row[value] for row in rows],
        "sort": False,
        "hovertemplate": f"%{{label}}<br>{hover}<extra></extra>",
    }


def _date_axis() -> dict[str, Any]:
    return {"type": "date", "title": {"text": "Date"}}


# ---------------------------------------------------------------------------
# Pies (shares of a whole)
# ---------------------------------------------------------------------------


def xray_sector_chart(rows: Rows, ctx: ChartContext) -> Figure:
    """Sector weights (fractions of the book) as a pie (#1267)."""
    return xray_sector_figure(rows, ctx.provenance)


def brinson_chart(rows: Rows, ctx: ChartContext) -> Figure:
    """Brinson-Fachler effects per sector (#1267)."""
    return brinson_attribution_figure(rows, ctx.provenance)


def xray_country_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Country weights (fractions of the book) as a pie."""
    early = _guard(rows, ctx, what="country weights")
    if early:
        return early
    trace = weight_pie(rows, "country", "Country Weight")
    return _finish([trace], ctx, legend={"title": {"text": "Country"}})


def revenue_geography_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Latest-period revenue by region as a pie."""
    early = _guard(rows, ctx, what="regional revenue")
    if early:
        return early
    trace = _pie(
        rows,
        "region",
        "revenue",
        "Revenue by Region",
        "Revenue (millions): %{value:,.0f}<br>Share: %{percent}",
    )
    return _finish([trace], ctx, legend={"title": {"text": "Region"}})


def revenue_business_line_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Latest-period revenue by business segment as a pie."""
    early = _guard(rows, ctx, what="segment revenue")
    if early:
        return early
    trace = _pie(
        rows,
        "segment",
        "revenue",
        "Revenue by Segment",
        "Revenue (millions): %{value:,.0f}<br>Share: %{percent}",
    )
    return _finish([trace], ctx, legend={"title": {"text": "Segment"}})


def stock_ownership_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Ownership split (percent of shares outstanding) as a pie."""
    early = _guard(rows, ctx, what="ownership split")
    if early:
        return early
    trace = _pie(
        rows,
        "bucket",
        "pct",
        "Ownership Share",
        "Held: %{value:.1f}% of shares<br>Share of chart: %{percent}",
    )
    return _finish([trace], ctx, legend={"title": {"text": "Holder type"}})


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


def risk_vol_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Return rolling 20/60-day realized volatility (already percentage points)."""
    early = _guard(rows, ctx, what="volatility series")
    if early:
        return early
    traces = [
        _line(rows, "date", "vol_20d", "20-Day Volatility (%)",
              "twenty_day_volatility", "%{y:.2f}%"),
        _line(rows, "date", "vol_60d", "60-Day Volatility (%)",
              "sixty_day_volatility", "%{y:.2f}%"),
    ]  # fmt: skip
    return _finish(
        traces,
        ctx,
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Realized volatility (%)"}},
    )


def paper_performance_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Paper-account equity curve in account currency."""
    early = _guard(rows, ctx, what="paper equity curve")
    if early:
        return early
    trace = _line(
        rows,
        "date",
        "equity",
        "Portfolio Equity",
        "portfolio_equity",
        "%{y:,.2f}",
    )
    return _finish(
        [trace],
        ctx,
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Equity (account currency)"}},
    )


def price_target_history_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Analyst price targets against the close when each was published."""
    early = _guard(rows, ctx, what="price targets")
    if early:
        return early
    traces = [
        _line(rows, "date", "close", "Closing Price", "closing_price",
              "%{y:,.2f}", mode="lines+markers"),
        _line(rows, "date", "target", "Analyst Price Target",
              "analyst_price_target", "%{y:,.2f}", mode="lines+markers"),
    ]  # fmt: skip
    return _finish(
        traces,
        ctx,
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Price"}},
    )


def _candles(rows: Rows) -> dict[str, Any]:
    return {
        "type": "candlestick",
        "name": "OHLC",
        "x": [row["date"] for row in rows],
        "open": [row["open"] for row in rows],
        "high": [row["high"] for row in rows],
        "low": [row["low"] for row in rows],
        "close": [row["close"] for row in rows],
    }


def _two_pane(lower_title: str, **lower: Any) -> dict[str, Any]:
    """Price pane on top, a lower pane on ``y2`` sharing the date axis."""
    return {
        "xaxis": {**_date_axis(), "rangeslider": {"visible": False}},
        "yaxis": {"title": {"text": "Price"}, "domain": [0.3, 1.0]},
        "yaxis2": {"title": {"text": lower_title}, "domain": [0.0, 0.22], **lower},
        "showlegend": True,
    }


def price_history_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Daily close (line mode) or OHLC candles with a volume pane (candle mode)."""
    early = _guard(rows, ctx, what="price history")
    if early:
        return early
    if ctx.params.get("chart_type") == "candle":
        volume = {
            "type": "bar",
            "name": "Volume",
            "x": [row["date"] for row in rows],
            "y": [row["volume"] for row in rows],
            "yaxis": "y2",
            "meta": {"glossaryKey": "volume"},
            "hovertemplate": (
                "%{x}<br>Volume: %{y:,.0f}<br>"
                f"{GLOSSARY_SUMMARY['volume']}<extra></extra>"
            ),
        }
        return _finish(
            [_candles(rows), volume],
            ctx,
            **_two_pane("Volume"),
        )
    trace = _line(rows, "date", "close", "Closing Price", "closing_price", "%{y:,.2f}")
    return _finish(
        [trace],
        ctx,
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Price"}},
    )


def charting_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """OHLC candles with SMA20/SMA50 overlays and RSI14 in a 0-100 lower pane."""
    early = _guard(rows, ctx, what="OHLC rows")
    if early:
        return early
    traces = [
        _candles(rows),
        _line(rows, "date", "sma20", "SMA 20", None, "%{y:,.2f}<br>"
              "20-day simple moving average of the close."),
        _line(rows, "date", "sma50", "SMA 50", None, "%{y:,.2f}<br>"
              "50-day simple moving average of the close."),
        _line(rows, "date", "rsi14", "RSI 14", None, "%{y:.1f}<br>"
              "14-day Relative Strength Index (0-100; above 70 overbought, "
              "below 30 oversold).", yaxis="y2"),
    ]  # fmt: skip
    return _finish(
        traces,
        ctx,
        **_two_pane("RSI", range=[0, 100]),
    )


# ---------------------------------------------------------------------------
# Financial statement comparison
# ---------------------------------------------------------------------------


def equity_financials_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Revenue/net income bars ($B, left axis) and net margin line (%, right)."""
    early = _guard(rows, ctx, what="annual financials")
    if early:
        return early
    bars = [
        ("revenue_b", "Revenue ($B)", "revenue_b"),
        ("net_income_b", "Net Income ($B)", "net_income_b"),
    ]
    traces: list[dict[str, Any]] = [
        {
            "type": "bar",
            "name": name,
            "x": [row["year"] for row in rows],
            "y": [row[field] for row in rows],
            "meta": {"glossaryKey": key},
            "hovertemplate": (
                f"FY %{{x}}<br>{name}: %{{y:,.1f}}<br>"
                f"{GLOSSARY_SUMMARY[key]}<extra></extra>"
            ),
        }
        for field, name, key in bars
    ]
    traces.append(
        _line(
            rows,
            "year",
            "net_margin_pct",
            "Net Margin (%)",
            "net_margin_pct",
            "%{y:.2f}%",
            mode="lines+markers",
            yaxis="y2",
        )
    )
    traces[-1]["hovertemplate"] = traces[-1]["hovertemplate"].replace(
        "%{x}", "FY %{x}", 1
    )
    return _finish(
        traces,
        ctx,
        barmode="group",
        xaxis={"type": "category", "title": {"text": "Fiscal year"}},
        yaxis={"title": {"text": "Billions ($B)"}},
        yaxis2={
            "title": {"text": "Net margin (%)"},
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
        },
    )
