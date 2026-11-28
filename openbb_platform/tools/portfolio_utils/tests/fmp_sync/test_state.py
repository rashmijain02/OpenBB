"""Durable status/history receipts and atomic replacement (#1344-T03)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

import pytest
from portfolio_utils.fmp_sync import state
from portfolio_utils.fmp_sync.outcome import FmpSyncOutcome, Outcome

NOW = datetime(2027, 3, 15, 22, 30, tzinfo=timezone.utc)


def _outcome(kind=Outcome.OK, *findings, run_id="r1", **kwargs) -> FmpSyncOutcome:
    return FmpSyncOutcome(
        run_id=run_id,
        mode="execute",
        started_utc=NOW,
        ended_utc=NOW,
        outcome=kind,
        findings=findings,
        **kwargs,
    )


def _history(root):
    return [
        json.loads(line)
        for line in (root / "history.jsonl").read_text("utf-8").splitlines()
    ]


def _history_lenient(root):
    out = []
    for line in (root / "history.jsonl").read_text("utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def test_fingerprint_ignores_run_identity():
    a = _outcome(run_id="a")
    b = _outcome(run_id="b")
    assert state.fingerprint(a) == state.fingerprint(b)
    assert state.fingerprint(a) != state.fingerprint(_outcome(Outcome.PARTIAL))
    assert state.fingerprint(a) != state.fingerprint(_outcome(Outcome.OK, "X_FINDING"))


def test_transition_only_on_fingerprint_change(tmp_path):
    root = tmp_path / "st"
    first = state.record_end(root, _outcome(run_id="r1"), now=NOW)
    assert first.transition and first.emit and first.persisted
    again = state.record_end(root, _outcome(run_id="r2"), now=NOW)
    assert not again.transition and not again.emit  # unchanged -> empty stdout
    changed = state.record_end(root, _outcome(Outcome.PARTIAL, run_id="r3"), now=NOW)
    assert changed.transition and changed.emit
    rows = _history(root)
    assert [r["kind"] for r in rows].count("transition") == 2
    assert [r["kind"] for r in rows].count("end") == 3
    status = json.loads((root / "status.json").read_text("utf-8"))
    assert status["outcome"] == "PARTIAL" and status["run_id"] == "r3"


def test_start_receipt_and_history_has_no_free_text(tmp_path):
    root = tmp_path / "st"
    state.record_start(root, "r1", "execute", now=NOW)
    state.record_end(root, _outcome(), now=NOW)
    rows = _history(root)
    assert rows[0]["kind"] == "start" and rows[0]["run_id"] == "r1"
    assert all(set(r) <= set(state.HISTORY_KEYS) for r in rows)


def test_busy_run_still_appends_receipt(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(), now=NOW)
    before = (root / "status.json").read_bytes()
    busy = state.record_end(
        root, _outcome(Outcome.SKIPPED_BUSY, "TARGET_LOCK_BUSY", run_id="b"), now=NOW
    )
    assert not busy.emit
    assert (root / "status.json").read_bytes() == before  # holder owns status
    assert _history(root)[-1]["outcome"] == "SKIPPED_BUSY"


def test_history_torn_tail_finding(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(), now=NOW)
    with open(root / "history.jsonl", "ab") as handle:
        handle.write(b'{"v":1,"kind":"en')  # torn tail, no newline
    records, findings = state.read_history(root / "history.jsonl")
    assert "HISTORY_TORN_TAIL" in findings and records
    receipt = state.record_end(root, _outcome(Outcome.PARTIAL, run_id="r9"), now=NOW)
    assert "HISTORY_TORN_TAIL" in receipt.outcome.findings
    ends = [r for r in _history_lenient(root) if r["kind"] == "end"]
    assert ends[-1]["run_id"] == "r9"  # appended on its own line, not glued


def test_replace_retries_with_backoff_then_succeeds(tmp_path):
    target = tmp_path / "status.json"
    calls, sleeps = [], []
    real = os.replace

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 4:
            raise PermissionError(13, "busy", None, 32)
        return real(src, dst)

    result = state.atomic_write_json(
        target, {"a": 1}, replace_fn=flaky, sleep_fn=sleeps.append
    )
    assert result.ok and len(calls) == 4
    assert sleeps == sorted(sleeps) and len(sleeps) == 3
    assert json.loads(target.read_text("utf-8")) == {"a": 1}


def test_replace_exhaustion_keeps_old_snapshot_and_persist_failed(tmp_path):
    root = tmp_path / "st"
    state.record_end(root, _outcome(), now=NOW)
    old = (root / "status.json").read_bytes()
    attempts = []

    def deny(_src, _dst):
        attempts.append(1)
        raise PermissionError(13, "busy", None, 32)

    receipt = state.record_end(
        root,
        _outcome(Outcome.PARTIAL, run_id="r2"),
        now=NOW,
        replace_fn=deny,
        sleep_fn=lambda _s: None,
    )
    assert len(attempts) == state.REPLACE_ATTEMPTS == 8
    assert not receipt.persisted
    assert receipt.outcome.outcome is Outcome.PERSIST_FAILED
    assert receipt.emit  # a failed persist is never silent
    assert (root / "status.json").read_bytes() == old  # old snapshot intact
    assert not list(root.glob("*.tmp"))  # only our own temp is removed


def test_acl_denied_distinct_code(tmp_path):
    def acl(_src, _dst):
        raise PermissionError(13, "denied", None, 5)

    result = state.atomic_write_json(
        tmp_path / "s.json", {}, replace_fn=acl, sleep_fn=lambda _s: None
    )
    assert not result.ok and result.code == "STATE_ACL_DENIED"

    def sharing(_src, _dst):
        raise PermissionError(13, "busy", None, 32)

    other = state.atomic_write_json(
        tmp_path / "s.json", {}, replace_fn=sharing, sleep_fn=lambda _s: None
    )
    assert other.code == "STATE_REPLACE_FAILED"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing violation")
def test_replace_retries_on_sharing_violation(tmp_path):
    win32file = pytest.importorskip("win32file")
    target = tmp_path / "status.json"
    target.write_text('{"old": true}', encoding="utf-8")
    handle = win32file.CreateFile(  # no FILE_SHARE_DELETE: replace must fail
        str(target),
        win32file.GENERIC_READ,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    timer = threading.Timer(0.3, handle.Close)
    timer.start()
    try:
        started = time.monotonic()
        result = state.atomic_write_json(target, {"new": True})
    finally:
        timer.join()
    assert result.ok and result.attempts > 1
    assert json.loads(target.read_text("utf-8")) == {"new": True}
    assert time.monotonic() - started < 10
