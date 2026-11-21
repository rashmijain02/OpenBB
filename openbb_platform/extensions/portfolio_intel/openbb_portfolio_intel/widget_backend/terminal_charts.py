"""Plotly figure adapters for the Terminal chart widgets (#1268).

Workspace renders a ``type: chart`` endpoint's default response as a Plotly
figure. The ten Terminal chart endpoints keep computing the rows they always
did; :func:`plotly_chart` wraps each one so the default response is a figure
built from those rows and ``raw=true`` returns the rows unchanged. The figure
builders only re-shape: every plotted value is a row value, unscaled.

Each figure records its data state in ``layout.meta`` (``state`` plus the
``source`` tier that served the rows) and never sets ``layout.title``
(Workspace shows the widget name). Demo, empty, and unavailable states are
also written into an annotation so they cannot be mistaken for live data.
Trace ``meta.glossaryKey`` names the Local Viewer glossary record, and the
hover text repeats that record's one-line summary.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from openbb_portfolio_intel.widget_backend.overview_charts import (
    Figure,
    header_note,
    layout,
    state_figure,
)

Rows = Sequence[Mapping[str, Any]]

#: Tier that served the current request's rows (set by ``record_tier_used``).
#: A context variable rather than the shared ledger, so concurrent requests
#: to the same endpoint cannot read each other's tier.
SERVING_TIER: ContextVar[str | None] = ContextVar("pi_serving_tier", default=None)

STUB = "stub"


@dataclass(frozen=True)
class ChartContext:
    """What a figure builder knows besides the rows."""

    params: Mapping[str, Any]
    source: str

    @property
    def is_live(self) -> bool:
        """Return True when a provider tier (not the stub) served the rows."""
        return self.source != STUB

    @property
    def symbol(self) -> str:
        """Return the normalized ticker parameter (validated upstream)."""
        return str(self.params.get("symbol", "")).strip().upper()


ChartBuilder = Callable[[Rows, ChartContext], Figure]


def plotly_chart(build: ChartBuilder) -> Callable[[Callable[..., Any]], Any]:
    """Serve a row endpoint as a Plotly figure, keeping rows for ``raw=true``.

    The wrapped function's rows are first validated and serialized through its
    declared return annotation, exactly as FastAPI's inferred response model
    did before #1268, so ``raw=true`` stays byte-compatible. The wrapper adds
    a ``raw`` query parameter and drops the return annotation, so FastAPI
    infers no response model that would reject the figure.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func, eval_str=True)
        annotation = signature.return_annotation
        adapter = (
            None if annotation is inspect.Signature.empty else TypeAdapter(annotation)
        )

        @functools.wraps(func)
        def wrapper(*args: Any, raw: bool = False, **kwargs: Any) -> Any:
            token = SERVING_TIER.set(None)
            try:
                rows = func(*args, **kwargs)
                source = SERVING_TIER.get() or STUB
            finally:
                SERVING_TIER.reset(token)
            if adapter is not None:
                rows = adapter.dump_python(adapter.validate_python(rows), mode="json")
            if raw:
                return rows
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            return build(rows, ChartContext(dict(bound.arguments), source))

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

_DEMO_BOOK = "Demo portfolio (synthetic); not your account."
_UNWIRED = "account resolver not wired for this account."


def _demo_symbol_note(ctx: ChartContext) -> str:
    return (
        "Demo data: no live provider answered, so these are sample values, "
        f"not live {ctx.symbol} data."
    )


def _state(ctx: ChartContext, *, account_scoped: bool) -> str:
    if ctx.is_live:
        return "live"
    if account_scoped and ctx.params.get("account_id") != "demo":
        return "unavailable"
    return "demo"


def _finish(
    traces: list[dict[str, Any]],
    ctx: ChartContext,
    state: str,
    demo_note: str,
    **extra: Any,
) -> Figure:
    """Return the figure, adding the demo annotation when the rows are demo."""
    if state == "demo":
        extra["annotations"] = [*extra.get("annotations", []), header_note(demo_note)]
    return {"data": traces, "layout": layout(state, source=ctx.source, **extra)}


def _guard(
    rows: Rows, ctx: ChartContext, *, account_scoped: bool, what: str
) -> tuple[str, Figure | None]:
    """Return ``(state, figure)``; the figure is set for unavailable/empty."""
    state = _state(ctx, account_scoped=account_scoped)
    if state == "unavailable":
        return state, state_figure(
            state, f"Unavailable: no {what}, {_UNWIRED}", source=ctx.source
        )
    if not rows:
        return "empty", state_figure(
            "empty", f"No {what} returned for these parameters.", source=ctx.source
        )
    return state, None


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


def xray_country_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Country weights (fractions of the book) as a pie."""
    state, early = _guard(rows, ctx, account_scoped=True, what="country weights")
    if early:
        return early
    trace = _pie(rows, "country", "weight", "Country Weight", "Weight: %{percent}")
    return _finish(
        [trace], ctx, state, _DEMO_BOOK, legend={"title": {"text": "Country"}}
    )


def revenue_geography_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Latest-period revenue by region as a pie."""
    state, early = _guard(rows, ctx, account_scoped=False, what="regional revenue")
    if early:
        return early
    trace = _pie(
        rows,
        "region",
        "revenue",
        "Revenue by Region",
        "Revenue (millions): %{value:,.0f}<br>Share: %{percent}",
    )
    return _finish(
        [trace],
        ctx,
        state,
        _demo_symbol_note(ctx),
        legend={"title": {"text": "Region"}},
    )


def revenue_business_line_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Latest-period revenue by business segment as a pie."""
    state, early = _guard(rows, ctx, account_scoped=False, what="segment revenue")
    if early:
        return early
    trace = _pie(
        rows,
        "segment",
        "revenue",
        "Revenue by Segment",
        "Revenue (millions): %{value:,.0f}<br>Share: %{percent}",
    )
    return _finish(
        [trace],
        ctx,
        state,
        _demo_symbol_note(ctx),
        legend={"title": {"text": "Segment"}},
    )


def stock_ownership_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Ownership split (percent of shares outstanding) as a pie."""
    state, early = _guard(rows, ctx, account_scoped=False, what="ownership split")
    if early:
        return early
    trace = _pie(
        rows,
        "bucket",
        "pct",
        "Ownership Share",
        "Held: %{value:.1f}% of shares<br>Share of chart: %{percent}",
    )
    return _finish(
        [trace],
        ctx,
        state,
        _demo_symbol_note(ctx),
        legend={"title": {"text": "Holder type"}},
    )


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


def risk_vol_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Return rolling 20/60-day realized volatility (already percentage points)."""
    state, early = _guard(rows, ctx, account_scoped=True, what="volatility series")
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
        state,
        _DEMO_BOOK,
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Realized volatility (%)"}},
    )


def paper_performance_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Paper-account equity curve in account currency."""
    state, early = _guard(rows, ctx, account_scoped=True, what="paper equity curve")
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
        state,
        _DEMO_BOOK,
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Equity (account currency)"}},
    )


def price_target_history_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Analyst price targets against the close when each was published."""
    state, early = _guard(rows, ctx, account_scoped=False, what="price targets")
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
        state,
        _demo_symbol_note(ctx),
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
    state, early = _guard(rows, ctx, account_scoped=False, what="price history")
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
            state,
            _demo_symbol_note(ctx),
            **_two_pane("Volume"),
        )
    trace = _line(rows, "date", "close", "Closing Price", "closing_price", "%{y:,.2f}")
    return _finish(
        [trace],
        ctx,
        state,
        _demo_symbol_note(ctx),
        xaxis=_date_axis(),
        yaxis={"title": {"text": "Price"}},
    )


def charting_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """OHLC candles with SMA20/SMA50 overlays and RSI14 in a 0-100 lower pane."""
    state, early = _guard(rows, ctx, account_scoped=False, what="OHLC rows")
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
        state,
        _demo_symbol_note(ctx),
        **_two_pane("RSI", range=[0, 100]),
    )


# ---------------------------------------------------------------------------
# Financial statement comparison
# ---------------------------------------------------------------------------


def equity_financials_figure(rows: Rows, ctx: ChartContext) -> Figure:
    """Revenue/net income bars ($B, left axis) and net margin line (%, right)."""
    state, early = _guard(rows, ctx, account_scoped=False, what="annual financials")
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
        state,
        _demo_symbol_note(ctx),
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
