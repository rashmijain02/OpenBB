"""Transport-accounted budget, egress allowlist and deadline guard (#1344-T02).

Requests are counted at ``requests.Session.send`` inside this process with an
injected inner transport (nothing leaves the machine). The conftest still blocks
MySQL and non-loopback sockets.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
import requests
from portfolio_utils.fmp_sync import budget
from portfolio_utils.fmp_sync.budget import (
    BudgetExhausted,
    BudgetLedger,
    CancelController,
    DeadlineExceeded,
    EgressDenied,
    Limits,
    TransportGuard,
)

from .conftest import PORTFOLIO_UTILS_ROOT

FMP_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"


def response(status=200, body=b"[]", headers=None, url=FMP_URL):
    resp = requests.Response()
    resp.status_code = status
    resp._content = body  # noqa: SLF001
    resp.headers.update(headers or {})
    resp.url = url
    return resp


class Clock:
    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self):
        return self.t


def make_guard(tmp_path, *, limits=None, inner=None, clock=None, mono=None, **kw):
    limits = limits or Limits(
        per_run=100, per_minute=100, per_day=100, bytes_per_day=10**9
    )
    clock = clock or Clock()
    mono = mono or Clock(0.0)
    sent = []

    def _inner(session, request, **kwargs):
        sent.append((request.url, kwargs))
        return (inner or (lambda: response()))()

    ledger = BudgetLedger(tmp_path / "state", "acct", limits, now_fn=clock)
    cancel = CancelController(
        run_id="run1", state_root=tmp_path / "state", deadline_s=900.0, clock=mono
    )
    guard = TransportGuard(
        ledger=ledger,
        cancel=cancel,
        inner_send=_inner,
        allowed_hosts=("financialmodelingprep.com",),
        mysql_port=3306,
        clock=mono,
    )
    return guard, ledger, cancel, sent, clock, mono


def test_limits_require_every_cap():
    with pytest.raises(ValueError):
        Limits.model_validate({"per_run": 1, "per_minute": 1, "per_day": 1})
    with pytest.raises(ValueError):
        Limits.model_validate(
            {"per_run": 0, "per_minute": 1, "per_day": 1, "bytes_per_day": 1}
        )
    assert Limits.from_map(None) == (None, "LIMITS_MISSING")
    assert Limits.from_map({"per_run": 1})[1] == "LIMITS_INVALID"


def test_budget_blocks_before_socket(tmp_path):
    guard, ledger, _, sent, _, _ = make_guard(
        tmp_path,
        limits=Limits(per_run=2, per_minute=10, per_day=10, bytes_per_day=10**6),
    )
    with guard:
        requests.get(FMP_URL)
        requests.get(FMP_URL)
        with pytest.raises(BudgetExhausted):
            requests.get(FMP_URL)
    assert len(sent) == 2
    assert guard.stats["reserved"] == 2 and guard.stats["sent"] == 2
    assert guard.cancel.reason == "QUOTA"
    assert ledger.snapshot()["reserved"] == 2


def test_session_send_restored_after_guard(tmp_path):
    original = requests.Session.send
    guard, *_ = make_guard(tmp_path)
    with guard:
        assert requests.Session.send is not original
    assert requests.Session.send is original


def test_minute_window(tmp_path):
    guard, ledger, _, sent, clock, _ = make_guard(
        tmp_path,
        limits=Limits(per_run=100, per_minute=2, per_day=100, bytes_per_day=10**6),
    )
    with guard:
        requests.get(FMP_URL)
        requests.get(FMP_URL)
        with pytest.raises(BudgetExhausted) as err:
            requests.get(FMP_URL)
        assert err.value.kind == "per_minute"
        clock.t += 61
        guard.cancel.reason = None  # a later run is not poisoned by the window
        requests.get(FMP_URL)
    assert len(sent) == 3


def test_daily_ledger_survives_restart(tmp_path):
    limits = Limits(per_run=100, per_minute=100, per_day=2, bytes_per_day=10**6)
    clock = Clock()
    first = BudgetLedger(tmp_path / "state", "acct", limits, now_fn=clock)
    first.reserve()
    first.reserve()
    restarted = BudgetLedger(tmp_path / "state", "acct", limits, now_fn=clock)
    with pytest.raises(BudgetExhausted) as err:
        restarted.reserve()
    assert err.value.kind == "per_day"
    clock.t += 86_400
    restarted.reserve()  # new UTC day, new ledger file
    files = sorted(
        p.name for p in (tmp_path / "state" / "budget" / "acct").glob("*.json")
    )
    assert len(files) == 2, "previous day ledger is retained, never deleted"


def test_bytes_cap(tmp_path):
    guard, *_ = make_guard(
        tmp_path,
        limits=Limits(per_run=100, per_minute=100, per_day=100, bytes_per_day=100),
        inner=lambda: response(body=b"x" * 150),
    )
    with guard:
        requests.get(FMP_URL)
        with pytest.raises(BudgetExhausted) as err:
            requests.get(FMP_URL)
    assert err.value.kind == "bytes"
    assert guard.stats["bytes"] == 150


def test_429_retry_after_defers(tmp_path):
    guard, ledger, _, sent, clock, _ = make_guard(
        tmp_path, inner=lambda: response(429, headers={"Retry-After": "120"})
    )
    with guard:
        requests.get(FMP_URL)  # the 429 itself is returned to the provider
        assert guard.cancel.reason == "RATE_LIMIT"
        with pytest.raises(BudgetExhausted) as err:
            requests.get(FMP_URL)
        assert err.value.kind == "defer"
    assert len(sent) == 1
    assert ledger.snapshot()["defer_until"] == pytest.approx(clock.t + 120)
    again, *_rest = make_guard(tmp_path, clock=clock)
    with again, pytest.raises(BudgetExhausted):
        requests.get(FMP_URL)
    clock.t += 121
    with again:
        requests.get(FMP_URL)


def test_429_without_retry_after_still_defers(tmp_path):
    guard, ledger, _, _, clock, _ = make_guard(tmp_path, inner=lambda: response(429))
    with guard:
        requests.get(FMP_URL)
    assert ledger.snapshot()["defer_until"] > clock.t


def test_402_blocked_plan_no_retry(tmp_path):
    guard, _, _, sent, _, _ = make_guard(tmp_path, inner=lambda: response(402))
    with guard:
        requests.get(FMP_URL)
        assert guard.cancel.reason == "PLAN"
        with pytest.raises(BudgetExhausted):
            requests.get(FMP_URL)
    assert len(sent) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_auth_status_stops_run(tmp_path, status):
    guard, *_ = make_guard(tmp_path, inner=lambda: response(status))
    with guard:
        requests.get(FMP_URL)
    assert guard.cancel.reason == "AUTH"


def test_unreserved_connect_fails_closed(tmp_path):
    guard, *_ = make_guard(tmp_path)
    with guard:
        with pytest.raises(EgressDenied) as err:
            sys.audit("socket.connect", None, ("203.0.113.7", 443))
        assert err.value.code == "ACCOUNTING_GAP"
    assert guard.stats["denied"] == 1


def test_egress_to_litellm_port_denied(tmp_path):
    guard, *_ = make_guard(tmp_path)
    with guard:
        with pytest.raises(EgressDenied):
            sys.audit("socket.connect", None, ("127.0.0.1", 4000))
        with pytest.raises(EgressDenied):
            sys.audit("socket.getaddrinfo", "api.openai.com", 443, 0, 0, 0, 0)
        with pytest.raises(EgressDenied):
            sys.audit("socket.getaddrinfo", "127.0.0.1", 4000, 0, 0, 0, 0)
        # allowlist: loopback MySQL and the FMP host name
        sys.audit("socket.connect", None, ("127.0.0.1", 3306))
        sys.audit("socket.getaddrinfo", "financialmodelingprep.com", 443, 0, 0, 0, 0)
        sys.audit("socket.getaddrinfo", "localhost", 3306, 0, 0, 0, 0)
    assert guard.stats["denied"] == 3
    # inactive guard: the hook is inert
    sys.audit("socket.getaddrinfo", "api.openai.com", 443, 0, 0, 0, 0)


def test_send_to_other_host_refused_before_reservation(tmp_path):
    guard, ledger, _, sent, _, _ = make_guard(tmp_path)
    with guard:
        with pytest.raises(EgressDenied):
            requests.get("http://127.0.0.1:4000/v1/chat/completions")
    assert sent == [] and ledger.snapshot()["reserved"] == 0


def test_connect_inside_send_is_reserved(tmp_path):
    """A connect made while a reserved FMP send is in flight is accounted, not a gap."""

    def inner():
        sys.audit("socket.connect", None, ("203.0.113.7", 443))
        return response()

    guard, *_ = make_guard(tmp_path, inner=inner)
    with guard:
        requests.get(FMP_URL)
    assert guard.stats["denied"] == 0


def test_send_timeout_capped(tmp_path):
    guard, _, _, sent, _, mono = make_guard(tmp_path)
    with guard:
        requests.get(FMP_URL, timeout=120)
        requests.get(FMP_URL, timeout=(5, 120))
        requests.get(FMP_URL)  # no timeout at all
        mono.t += 880  # 20 s left, reserve 5 s
        requests.get(FMP_URL, timeout=60)
    timeouts = [kw["timeout"] for _, kw in sent]
    assert timeouts[0] == 60 and timeouts[1] == (5, 60) and timeouts[2] == 60
    assert timeouts[3] == pytest.approx(15)


def test_no_time_left_refuses_before_reservation(tmp_path):
    guard, ledger, cancel, sent, _, mono = make_guard(tmp_path)
    with guard:
        mono.t += 899  # inside the 5 s reserve
        with pytest.raises(DeadlineExceeded):
            requests.get(FMP_URL)
    assert sent == [] and ledger.snapshot()["reserved"] == 0
    assert cancel.reason == "DEADLINE"


def test_cancel_controller_reasons(tmp_path):
    mono = Clock(0.0)
    cancel = CancelController("rid", tmp_path, deadline_s=10, clock=mono)
    assert cancel.should_cancel() is False
    (tmp_path / "cancel").mkdir()
    (tmp_path / "cancel" / "other").write_text("x")
    assert cancel.should_cancel() is False
    (tmp_path / "cancel" / "rid").write_text("x")
    assert cancel.should_cancel() is True and cancel.reason == "CANCEL"
    cancel2 = CancelController("rid2", tmp_path, deadline_s=10, clock=mono)
    mono.t = 10
    assert cancel2.should_cancel() is True and cancel2.reason == "DEADLINE"
    cancel2.reason = None
    cancel3 = CancelController("rid3", tmp_path, deadline_s=10, clock=Clock(0.0))
    cancel3.signal_flag = True
    assert cancel3.should_cancel() and cancel3.reason == "SIGNAL"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_no_openbb_agents_config_or_litellm_import():
    pkg = PORTFOLIO_UTILS_ROOT / "portfolio_utils" / "fmp_sync"
    for name in ("budget.py", "outcome.py", "dispatcher.py", "locking.py"):
        imports = _imports(pkg / name)
        banned = {"litellm", "openai", "anthropic", "subprocess"}
        if name != "locking.py":  # locking lazily resolves the target DB (D9)
            banned.add("openbb_agents")
        assert not imports & banned, name
    text = (pkg / "dispatcher.py").read_text(encoding="utf-8")
    assert "openbb_agents" not in text and "litellm" not in text.lower()


def test_no_delete_paths():
    pkg = PORTFOLIO_UTILS_ROOT / "portfolio_utils" / "fmp_sync"
    banned_names = {"cache_prune", "replace_rows", "pi_fmp_record", "rmtree"}
    banned_words = ("DELETE FROM", "TRUNCATE", "DROP TABLE")
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = (
                node.id
                if isinstance(node, ast.Name)
                else node.attr if isinstance(node, ast.Attribute) else None
            )
            assert name not in banned_names, (path.name, name)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not any(w in node.value.upper() for w in banned_words), path.name


def test_ledger_is_json_with_counts_only(tmp_path):
    guard, ledger, *_ = make_guard(tmp_path)
    with guard:
        requests.get(FMP_URL + "?apikey=SENTINEL-KEY&symbol=AAPL")
    text = (next((tmp_path / "state" / "budget" / "acct").glob("*.json"))).read_text(
        encoding="utf-8"
    )
    assert "SENTINEL-KEY" not in text and "AAPL" not in text
    assert json.loads(text)["reserved"] == 1
    assert budget.EgressDenied.__mro__  # exported
