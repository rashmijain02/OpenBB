"""Regression tests for the Project 1 claim lifecycle helper."""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "pi_claim.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pi_claim", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["pi_claim"] = module
    spec.loader.exec_module(module)
    return module


def _project_item(number: int, title: str, status: str) -> dict:
    return {
        "id": f"item-{number}",
        "content": {"number": number, "title": title},
        "fieldValues": {
            "nodes": [
                {
                    "name": status,
                    "field": {"name": "Status"},
                }
            ]
        },
    }


def test_list_stale_paginates_every_project_item(monkeypatch, capsys):
    """A stale claim after the first 100 project items must be reported."""
    module = _load_module()
    pages = iter(
        [
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "nodes": [_project_item(1, "First page", "Todo")],
                                "pageInfo": {
                                    "hasNextPage": True,
                                    "endCursor": "cursor-100",
                                },
                            }
                        }
                    }
                }
            },
            {
                "data": {
                    "user": {
                        "projectV2": {
                            "items": {
                                "nodes": [
                                    _project_item(
                                        2042, "Stale promotion", "In Progress"
                                    )
                                ],
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                            }
                        }
                    }
                }
            },
        ]
    )
    calls: list[tuple[str, ...]] = []

    def fake_gh_json(*args: str) -> object:
        calls.append(args)
        return next(pages)

    monkeypatch.setattr(module, "gh_json", fake_gh_json)
    monkeypatch.setattr(
        module,
        "latest_heartbeat",
        lambda _issue: (
            {
                "owner": "Rashmi Jain",
                "hb": "2026-08-01T00:00:00Z",
                "action": "heartbeat",
            },
            "comment-id",
        ),
    )
    monkeypatch.setattr(module, "_age", lambda _heartbeat: timedelta(days=30))

    assert module.cmd_list_stale() == 0

    output = capsys.readouterr().out
    assert "#2042" in output
    assert "STALE" in output
    assert len(calls) == 2
    assert any("cursor-100" in arg for arg in calls[1])


def test_item_id_for_falls_back_to_live_project_items(monkeypatch, tmp_path):
    """New project items need not be present in the legacy JSON snapshot."""
    module = _load_module()
    missing_snapshot = tmp_path / "pi_project_items.json"
    monkeypatch.setattr(module, "ITEMS_JSON", missing_snapshot)
    monkeypatch.setattr(
        module,
        "_project_items",
        lambda: [_project_item(2045, "Lifecycle bug", "In Progress")],
    )

    assert module.item_id_for("2045") == "item-2045"


# ---------------------------------------------------------------------------
# --mine (#1279, pi_claim: add --mine to list my claims and flag overdue
# heartbeats). Spec: specs/gh-1279-pi-claim-mine/
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
ME = "me-login"
OTHER = "other-login"


def _freeze(module, monkeypatch, now: datetime = FIXED_NOW) -> None:
    """Pin datetime.now() inside the module so ages are exact."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _Frozen)


def _iso(age: timedelta) -> str:
    return (FIXED_NOW - age).strftime("%Y-%m-%dT%H:%M:%SZ")


def _marker(
    owner: str,
    age: timedelta = timedelta(minutes=1),
    action: str = "heartbeat",
    assoc: str = "COLLABORATOR",
    hb: str | None = None,
    cid: int = 1,
) -> dict:
    return {
        "id": cid,
        "author_association": assoc,
        "body": f"<!-- pi-claim: owner={owner} hb={hb or _iso(age)} action={action} -->",
    }


def _comments_path(number: int) -> str:
    return f"/repos/rashmijain02/OpenBB/issues/{number}/comments?per_page=100"


def _fake_comments(monkeypatch, module, by_issue: dict[int, list[dict]]) -> list:
    """Serve comment histories through the real latest_heartbeat()."""
    calls: list[tuple[str, ...]] = []

    def fake_gh_json(*args: str) -> object:
        calls.append(args)
        for number, comments in by_issue.items():
            if args == ("api", _comments_path(number)):
                return comments
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(module, "gh_json", fake_gh_json)
    return calls


def test_mine_filters_status_and_owner(monkeypatch, capsys):
    """Only In Progress issues whose latest trusted marker names me are listed."""
    module = _load_module()
    _freeze(module, monkeypatch)
    items = [
        _project_item(1, "Mine in progress", "In Progress"),
        _project_item(2, "Other owner", "In Progress"),
        _project_item(3, "Mine but Todo", "Todo"),
        _project_item(4, "Mine but Done", "Done"),
        _project_item(5, "No marker at all", "In Progress"),
        _project_item(6, "Mine, latest marker is release", "In Progress"),
        _project_item(7, "Taken over by other", "In Progress"),
        _project_item(8, "Newer untrusted impersonation", "In Progress"),
        _project_item(9, "Newer malformed timestamp", "In Progress"),
        {"id": "draft", "content": None, "fieldValues": {"nodes": []}},
        # Real GraphQL shape: drafts/PRs miss the Issue fragment and come back as {}.
        {"id": "draft-real", "content": {}, "fieldValues": {"nodes": [{}]}},
        {"id": "no-number", "content": {"title": "x"}, "fieldValues": {"nodes": []}},
        {"id": "no-status", "content": {"number": 10, "title": "x"}},
        # Real GraphQL shape: non-single-select values are {} and Status need not be first.
        {
            "id": "item-11",
            "content": {"number": 11, "title": "Mine, realistic field values"},
            "fieldValues": {
                "nodes": [
                    {},
                    {"name": "P1", "field": {"name": "Phase"}},
                    {"name": "In Progress", "field": {"name": "Status"}},
                ]
            },
        },
    ]
    monkeypatch.setattr(module, "_project_items", lambda: items)
    whoami_calls: list[int] = []

    def fake_whoami() -> str:
        whoami_calls.append(1)
        return ME

    monkeypatch.setattr(module, "whoami", fake_whoami)
    _fake_comments(
        monkeypatch,
        module,
        {
            1: [_marker(ME)],
            2: [_marker(OTHER)],
            3: [_marker(ME)],
            4: [_marker(ME)],
            5: [{"id": 1, "author_association": "OWNER", "body": "no marker"}],
            6: [_marker(ME, action="release")],
            7: [
                _marker(ME, timedelta(minutes=30), cid=1),
                _marker(OTHER, timedelta(minutes=2), cid=2),
            ],
            8: [
                _marker(ME, timedelta(minutes=3), cid=1),
                _marker(OTHER, timedelta(minutes=1), assoc="NONE", cid=2),
            ],
            9: [
                _marker(ME, timedelta(minutes=4), cid=1),
                _marker(OTHER, hb="not-a-time", cid=2),
            ],
            11: [_marker(ME)],
        },
    )

    assert module.cmd_mine() == 0

    out = capsys.readouterr().out
    listed = {int(n) for n in re.findall(r"#\s*(\d+)", out)}
    assert listed == {1, 6, 8, 9, 11}
    assert len(whoami_calls) == 1


def test_mine_empty_is_explicit(monkeypatch, capsys):
    """No eligible claims prints a clear line and succeeds, never a blank listing."""
    module = _load_module()
    _freeze(module, monkeypatch)
    monkeypatch.setattr(module, "whoami", lambda: ME)
    scenarios = [
        ([], {}),
        ([_project_item(1, "Other only", "In Progress")], {1: [_marker(OTHER)]}),
        (
            [_project_item(2, "Untrusted only", "In Progress")],
            {2: [_marker(ME, assoc="NONE")]},
        ),
    ]
    for items, comments in scenarios:
        monkeypatch.setattr(module, "_project_items", lambda items=items: items)
        _fake_comments(monkeypatch, module, comments)

        assert module.cmd_mine() == 0

        out = capsys.readouterr().out
        assert "no In Progress claims" in out
        assert "#" not in out


def test_mine_lookup_failures_surface(monkeypatch, capsys):
    """Identity, project and comment failures raise; they are not an empty result."""
    import pytest

    module = _load_module()
    _freeze(module, monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError("gh failed")

    failing = [
        ("whoami", boom, None),
        ("_project_items", boom, None),
        ("gh_json", boom, [_project_item(1, "Mine", "In Progress")]),
    ]
    for name, fn, items in failing:
        monkeypatch.setattr(module, "whoami", lambda: ME)
        monkeypatch.setattr(module, "_project_items", lambda items=items: items or [])
        monkeypatch.setattr(module, name, fn)

        with pytest.raises(RuntimeError):
            module.cmd_mine()

        assert "no In Progress claims" not in capsys.readouterr().out


def _graphql_page(nodes: list[dict], cursor: str | None) -> dict:
    return {
        "data": {
            "user": {
                "projectV2": {
                    "items": {
                        "nodes": nodes,
                        "pageInfo": {
                            "hasNextPage": cursor is not None,
                            "endCursor": cursor,
                        },
                    }
                }
            }
        }
    }


def _fake_transport(monkeypatch, module, pages: list[dict], comments: dict) -> list:
    """Replace the gh subprocess layer; record every call; refuse writes."""
    import json

    calls: list[tuple[str, ...]] = []
    page_iter = iter(pages)

    def fake_gh(*args: str, check: bool = True) -> str:
        calls.append(args)
        joined = " ".join(args)
        assert "-X" not in args, f"write attempted: {joined}"
        assert "mutation" not in joined, f"GraphQL mutation attempted: {joined}"
        if args == ("api", "user"):
            return json.dumps({"login": ME})
        if args[:2] == ("api", "graphql"):
            return json.dumps(next(page_iter))
        for number, history in comments.items():
            if args == ("api", _comments_path(number)):
                return json.dumps(history)
        raise AssertionError(f"unexpected gh call: {joined}")

    monkeypatch.setattr(module, "gh", fake_gh)
    return calls


def test_mine_main_read_only_paginated(monkeypatch, capsys):
    """`--mine` walks every project page through main() and only reads."""
    module = _load_module()
    _freeze(module, monkeypatch)
    calls = _fake_transport(
        monkeypatch,
        module,
        [
            _graphql_page([_project_item(1, "First page Todo", "Todo")], "cursor-100"),
            _graphql_page(
                [_project_item(2042, "Second page claim", "In Progress")], None
            ),
        ],
        {2042: [_marker(ME)]},
    )
    monkeypatch.setattr(sys, "argv", ["pi_claim.py", "--mine"])

    assert module.main() == 0

    out = capsys.readouterr().out
    assert "#2042" in out
    graphql = [c for c in calls if c[:2] == ("api", "graphql")]
    assert len(graphql) == 2
    assert any("cursor-100" in arg for arg in graphql[1])


def test_mine_main_failure_is_nonzero(monkeypatch, capsys):
    """A failed lookup through main() is a visible, nonzero error."""
    module = _load_module()

    def boom(*_args, **_kwargs):
        raise RuntimeError("gh auth failed")

    monkeypatch.setattr(module, "gh", boom)
    monkeypatch.setattr(sys, "argv", ["pi_claim.py", "--mine"])

    assert module.main() == 1

    captured = capsys.readouterr()
    assert "gh auth failed" in captured.err
    assert "no In Progress claims" not in captured.out


def test_mine_rejects_conflicting_arguments(monkeypatch, capsys):
    """`--mine` with another mode or transition is a usage error before any gh call."""
    module = _load_module()
    calls: list[tuple[str, ...]] = []

    def record(*args: str, **_kwargs) -> str:
        calls.append(args)
        raise AssertionError("no gh call expected")

    monkeypatch.setattr(module, "gh", record)
    conflicts = [
        ["--mine", "5"],
        ["--mine", "5", "heartbeat"],
        ["--mine", "--note", "x"],
        ["--mine", "--note", ""],
        ["--mine", "--list-stale"],
        ["--mine", "--status", "5"],
    ]
    for argv in conflicts:
        monkeypatch.setattr(sys, "argv", ["pi_claim.py", *argv])

        assert module.main() == 2, argv

        assert "--mine" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["pi_claim.py", "--mine", "--help"])
    assert module.main() == 0
    assert calls == []


def test_mine_rows_include_issue_and_title_in_project_order(monkeypatch, capsys):
    """Rows keep project traversal order and the 60-character title convention."""
    module = _load_module()
    _freeze(module, monkeypatch)
    long_title = "L" * 80
    items = [
        _project_item(30, "Third by number, first on board", "In Progress"),
        _project_item(10, long_title, "In Progress"),
        _project_item(20, "Middle", "In Progress"),
    ]
    monkeypatch.setattr(module, "whoami", lambda: ME)
    monkeypatch.setattr(module, "_project_items", lambda: items)
    _fake_comments(monkeypatch, module, {n: [_marker(ME)] for n in (10, 20, 30)})

    assert module.cmd_mine() == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if "#" in line]
    assert [int(re.search(r"#\s*(\d+)", line).group(1)) for line in lines] == [
        30,
        10,
        20,
    ]
    assert "Third by number, first on board" in lines[0]
    assert "L" * 60 in lines[1] and "L" * 61 not in lines[1]


def test_mine_help_and_legacy_dispatch(monkeypatch, capsys):
    """Help documents --mine; modes without --mine dispatch exactly as before."""
    module = _load_module()
    seen: list[tuple] = []
    monkeypatch.setattr(
        module, "cmd_status", lambda issue: seen.append(("status", issue)) or 0
    )
    monkeypatch.setattr(module, "cmd_list_stale", lambda: seen.append(("stale",)) or 0)
    monkeypatch.setattr(
        module,
        "cmd_transition",
        lambda issue, action, note=None: seen.append(
            ("transition", issue, action, note)
        )
        or 0,
    )
    monkeypatch.setattr(module, "cmd_mine", lambda: seen.append(("mine",)) or 0)

    for argv in ([], ["--help"]):
        monkeypatch.setattr(sys, "argv", ["pi_claim.py", *argv])
        assert module.main() == 0
        assert "--mine" in capsys.readouterr().out

    for argv in (
        ["--status", "7"],
        ["--list-stale"],
        ["7", "heartbeat", "--note", "n"],
    ):
        monkeypatch.setattr(sys, "argv", ["pi_claim.py", *argv])
        assert module.main() == 0

    assert seen == [("status", "7"), ("stale",), ("transition", "7", "heartbeat", "n")]
