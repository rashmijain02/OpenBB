"""Payload rendering parity: FMP REST body -> hosted ``content[0].text`` (#1299)."""

from __future__ import annotations

import gzip
import json
import math
import re

import pytest
from openbb_fmp_cached_mcp.render import js_dumps, js_number, render_response

from .conftest import HOSTED, SNAPSHOT, load_hosted

SAMPLES = sorted((HOSTED / f"samples-{SNAPSHOT}").glob("*.json"))


def _replayable(rec: dict) -> bool:
    """Recorded body and hosted text that must map deterministically.

    Live endpoints (quotes) moved between the hosted and REST calls; those
    samples are skipped unless the body is empty (hosted not_found envelope).
    """
    if "rest_body_gz_hex" not in rec or rec.get("isError"):
        return False
    body = gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"]))
    return bool(rec.get("json_equal")) or body.strip() == b"[]"


REPLAY = [p for p in SAMPLES if _replayable(json.loads(p.read_text("utf-8")))]


def test_replay_set_is_not_ceremonial():
    # R3 loud empties: the fixture drain must leave a meaningful replay set.
    assert len(SAMPLES) == 208
    assert len(REPLAY) >= 175, len(REPLAY)
    tools = {json.loads(p.read_text("utf-8"))["tool"] for p in REPLAY}
    assert len(tools) == 24, sorted(tools)


@pytest.mark.parametrize("path", REPLAY, ids=[p.stem for p in REPLAY])
def test_rest_body_renders_to_hosted_text(path):
    rec = json.loads(path.read_text("utf-8"))
    body = gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"]))
    result = render_response(
        tool=rec["tool"],
        arguments=rec["arguments"],
        path=rec["rest_path"],
        status=rec["rest_status"],
        body=body,
    )
    assert result.is_error is False
    # Documented divergence (DIVERGENCES.md D1): the hosted server writes the
    # caller's FMP key into report links; we keep FMP's own placeholder.
    assert _mask_keys(result.text) == _mask_keys(rec["hosted_text"])
    if "apikey=" not in rec["hosted_text"]:
        assert result.text == rec["hosted_text"]


def _mask_keys(text: str) -> str:
    return re.sub(r"apikey=[^&\"]+", "apikey=<key>", text)


@pytest.mark.parametrize(
    "value, expected",
    [
        (8e-05, "0.00008"),
        (1e-05, "0.00001"),
        (1e-06, "0.000001"),
        (1.234e-06, "0.000001234"),
        (1e-07, "1e-7"),
        (1.5e-07, "1.5e-7"),
        (123456789012345680000.0, "123456789012345680000"),
        (1e21, "1e+21"),
        (2.5e22, "2.5e+22"),
        (-0.00012, "-0.00012"),
        (0.1, "0.1"),
        (100.0, "100"),
        (-0.0, "0"),
        (5072900376000, "5072900376000"),
        (958871.0126499981, "958871.0126499981"),
    ],
)
def test_js_number_matches_javascript(value, expected):
    assert js_number(value) == expected


def test_js_number_non_finite_is_null():
    assert js_number(math.nan) == "null"
    assert js_number(math.inf) == "null"


def test_js_dumps_is_compact_and_keeps_order_and_unicode():
    obj = {"b": 1, "a": [1.0, 8e-05, None, True], "t": "Q1–Q4 é"}
    assert js_dumps(obj) == '{"b":1,"a":[1,0.00008,null,true],"t":"Q1–Q4 é"}'


def test_empty_list_with_identifier_becomes_not_found_envelope():
    result = render_response(
        tool="senate",
        arguments={"endpoint": "senate-trading-by-name", "name": "Pelosi", "limit": 2},
        path="/senate-trades-by-name",
        status=200,
        body=b"[]",
    )
    expected = load_hosted(f"samples-{SNAPSHOT}/senate_senate-trading-by-name.json")
    assert result.text == expected["hosted_text"]


def test_empty_list_without_identifier_stays_empty():
    cases = load_hosted(f"not-found-{SNAPSHOT}.json")
    no_ident = [c for c in cases if c["text"] == "[]"]
    assert no_ident, "fixture must contain plain-[] cases"
    for case in no_ident:
        result = render_response(
            tool=case["tool"],
            arguments=case["arguments"],
            path="/x",
            status=200,
            body=b"[]",
        )
        assert result.text == "[]", case["arguments"]


def test_not_found_cases_from_probe_fixture():
    for case in load_hosted(f"not-found-{SNAPSHOT}.json"):
        if not case["text"].startswith('{"status":"not_found"'):
            continue
        result = render_response(
            tool=case["tool"],
            arguments=case["arguments"],
            path="/x",
            status=200,
            body=b"[]",
        )
        assert result.text == case["text"]


@pytest.mark.parametrize("idx", range(4))
def test_upstream_errors_render_like_hosted(idx):
    case = load_hosted(f"rest-errors-{SNAPSHOT}.json")["cases"][idx]
    result = render_response(
        tool=case["tool"],
        arguments=case["arguments"],
        path=case["rest_path"],
        status=case["rest_status"],
        body=case["rest_body"].encode(),
    )
    assert result.is_error is True
    assert result.text == case["hosted_text"]


def test_binary_body_is_json_string_of_lossy_utf8_text():
    body = b"PK\x03\x04\x14\x00\xff\xfe\x08\n"
    result = render_response(
        tool="statements",
        arguments={"endpoint": "financial-reports-form-10-k-xlsx"},
        path="/financial-reports-xlsx",
        status=200,
        body=body,
    )
    assert result.text == json.dumps(
        body.decode("utf-8", "replace"), ensure_ascii=False
    )
    assert result.text.startswith(r'"PK\u0003\u0004\u0014\u0000')


# --- Review findings (PR-A code review): JavaScript JSON edge cases ------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (12345678901234567890, "12345678901234567000"),
        (9007199254740993, "9007199254740992"),
        (123456789012345678901234, "1.2345678901234569e+23"),  # node-verified
        (9007199254740991, "9007199254740991"),
        (-12345678901234567890, "-12345678901234567000"),
    ],
)
def test_big_integers_print_as_javascript_doubles(value, expected):
    assert js_number(value) == expected


def test_integer_like_keys_come_first_in_ascending_order():
    obj = {"b": 1, "2024": 2, "a": 3, "10": 4, "01": 5, "4294967295": 6}
    # JS: array-index keys (0..2**32-2) first, ascending; then insertion order.
    assert js_dumps(obj) == '{"10":4,"2024":2,"b":1,"a":3,"01":5,"4294967295":6}'


def test_lone_surrogates_are_escaped_like_well_formed_stringify():
    # node: JSON.stringify("a\ud800b") -> "a\ud800b" (six escaped characters)
    assert js_dumps("a\ud800b") == r'"a\ud800b"'
    assert js_dumps("\U0001f600") == '"\U0001f600"'


def test_nan_and_infinity_literals_are_not_json():
    result = render_response(
        tool="quote",
        arguments={"endpoint": "quote"},
        path="/quote",
        status=200,
        body=b'[{"x": NaN}]',
    )
    assert result.text == '"[{\\"x\\": NaN}]"'


# --- Final review: hosted Node does res.text() (lossy, BOM-stripped) first ---


def test_invalid_utf8_byte_in_json_body_still_parses_with_replacement_char():
    # Node: JSON.parse(await res.text()) where text() decodes \xe9 to U+FFFD.
    result = render_response(
        tool="news",
        arguments={"endpoint": "stock-news"},
        path="/news/stock",
        status=200,
        body=b'[{"t":"Ren\xe9e"}]',
    )
    assert result.text == '[{"t":"Ren\ufffde"}]'


def test_leading_bom_is_stripped_before_json_parse():
    # Node: res.text() strips one leading U+FEFF before JSON.parse.
    result = render_response(
        tool="quote",
        arguments={"endpoint": "quote"},
        path="/quote",
        status=200,
        body=b'\xef\xbb\xbf[{"symbol":"AAPL"}]',
    )
    assert result.text == '[{"symbol":"AAPL"}]'


def test_js_dumps_matches_node_on_edge_corpus_and_fixtures(tmp_path):
    """Differential check against real ``JSON.stringify(JSON.parse(x))``."""
    import random  # pylint: disable=import-outside-toplevel
    import shutil  # pylint: disable=import-outside-toplevel
    import subprocess  # pylint: disable=import-outside-toplevel

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    rng = random.Random(1298)
    corpus = [
        [rng.uniform(-1e-9, 1e-9) for _ in range(200)],
        [rng.uniform(-1e25, 1e25) for _ in range(200)],
        [rng.randint(-(2**70), 2**70) for _ in range(200)],
        [10.0**e for e in range(-30, 30)],
        {"b": 1, "2024": 2, "a": [1.5, {"9": 0, "x": None}], "01": 3},
        'control  tab	 quote" slash\  ',
    ]
    bodies = [json.dumps(c) for c in corpus]
    for path in SAMPLES[:60]:
        rec = json.loads(path.read_text("utf-8"))
        if "rest_body_gz_hex" in rec:
            bodies.append(
                gzip.decompress(bytes.fromhex(rec["rest_body_gz_hex"])).decode()
            )
    src = tmp_path / "bodies.json"
    src.write_text(json.dumps(bodies), encoding="utf-8")
    script = (
        "const b=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(JSON.stringify(b.map(x=>{try{return JSON.stringify(JSON.parse(x))}"
        "catch(e){return null}})))"
    )
    out = subprocess.run(
        [node, "-e", script, str(src)],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout
    expected = json.loads(out)
    for body, want in zip(bodies, expected):
        if want is None:
            continue
        assert js_dumps(json.loads(body)) == want


def test_lone_surrogates_from_fmp_render_and_encode():
    """FMP text can hold a truncated emoji; JSON.stringify escapes it."""
    out = js_dumps(json.loads('{"title":"Rally \\ud83d"}'))
    assert out == '{"title":"Rally \\ud83d"}'
    out.encode("utf-8")
    assert js_dumps("\U0001f600") == '"\U0001f600"', "valid pairs stay as characters"
