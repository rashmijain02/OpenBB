"""Record FMP's hosted MCP server as parity fixtures for ``openbb_fmp_cached_mcp`` (#1299).

Subcommands (all write under
``openbb_platform/extensions/fmp_cached_mcp/tests/fixtures/hosted/``):

``inventory``
    ``initialize`` + ``tools/list`` (+ prompts/resources probes) ->
    ``inventory-<date>.json``.
``paths``
    Discover the FMP REST path behind every hosted endpoint. Endpoints with
    required parameters are called without them; the hosted error text names
    the path (``endpoint /<path>``). Paths of endpoints without required
    parameters are confirmed by comparing the hosted payload with candidate
    ``/stable/<path>`` REST responses. -> ``paths-<date>.json``.
``errors``
    Record hosted error texts for schema violations -> ``errors-<date>.json``.
``samples``
    Call every endpoint with public sample arguments, record the hosted text
    and the raw REST body for replay -> ``samples-<date>/``.

The FMP key is read from ``FMP_API_KEY`` or ``user_settings.json``. It is sent
only in request headers or the REST query string and is scrubbed from
everything written to disk; a final scan fails the run if it leaks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HOSTED_URL = "https://financialmodelingprep.com/mcp"
REST_BASE = "https://financialmodelingprep.com/stable"
PROTOCOL = "2025-06-18"
REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / (
    "openbb_platform/extensions/fmp_cached_mcp/tests/fixtures/hosted"
)
# Replay fixtures larger than this keep only hashes plus an excerpt.
FULL_BODY_LIMIT = 64 * 1024
PAUSE_S = 0.2


def _load_key() -> str:
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        try:
            from openbb_core.app.service.user_service import (  # noqa: PLC0415
                UserService,
            )

            creds = UserService().default_user_settings.credentials.model_dump(
                mode="json"
            )
            key = creds.get("fmp_cached_api_key") or creds.get("fmp_api_key") or ""
        except Exception:  # noqa: BLE001
            key = ""
    if len(key) < 16:
        sys.exit("error: no FMP key in FMP_API_KEY or user_settings.json")
    return key


KEY = ""


def scrub(text: str) -> str:
    """Remove the key and any apikey query value from ``text``."""
    if KEY:
        text = text.replace(KEY, "<redacted>")
    return re.sub(r"(?i)(apikey=)[^&\s\"'\\]+", r"\1<redacted>", text)


class Hosted:
    """Minimal streamable-HTTP MCP client for the hosted server."""

    def __init__(self) -> None:
        self.session: str | None = None
        self._id = 0

    def post(self, method: str, params: dict | None = None, notify: bool = False):
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            self._id += 1
            body["id"] = self._id
        if params is not None:
            body["params"] = params
        headers = {
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(
            HOSTED_URL, json.dumps(body).encode(), headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
                self.session = resp.headers.get("Mcp-Session-Id") or self.session
                raw = resp.read().decode()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return {"_http": exc.code, "_body": scrub(exc.read().decode()[:500])}
        if notify or not raw.strip():
            return None
        if "event-stream" in ctype:
            msgs = [json.loads(x[5:]) for x in raw.splitlines() if x.startswith("data:")]
            return msgs[-1] if msgs else None
        return json.loads(raw)

    def start(self) -> dict:
        init = self.post(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "openbb-parity-recorder", "version": "1"},
            },
        )
        self.post("notifications/initialized", notify=True)
        return init

    def call(self, tool: str, args: dict) -> dict:
        time.sleep(PAUSE_S)
        resp = self.post("tools/call", {"name": tool, "arguments": args})
        return (resp or {}).get("result") or {"_rpc": resp}


def rest(path: str, params: dict) -> tuple[int, bytes, str]:
    query = urllib.parse.urlencode({**params, "apikey": KEY})
    url = f"{REST_BASE}/{path.lstrip('/')}?{query}"
    time.sleep(PAUSE_S)
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def load_inventory(date: str) -> dict:
    return json.loads((OUT_DIR / f"inventory-{date}.json").read_text("utf-8"))


def endpoint_specs(inv: dict) -> list[dict]:
    """Parse ``- slug (a*, b*): Title`` lines out of each tool description."""
    out = []
    for tool in inv["tools"]:
        enum = tool["inputSchema"]["properties"]["endpoint"]["enum"]
        for line in tool["description"].splitlines():
            m = re.match(r"^- ([^\s:(]+)(?: \(([^)]*)\))?: (.*)$", line)
            if m and m.group(1) in enum:
                req = [p.strip().rstrip("*") for p in (m.group(2) or "").split(",") if p.strip()]
                out.append(
                    {"tool": tool["name"], "endpoint": m.group(1), "required": req,
                     "title": m.group(3)}
                )
    return out


def cmd_inventory(date: str) -> None:
    h = Hosted()
    init = h.start()
    res: dict[str, Any] = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "url": HOSTED_URL,
        "initialize": (init or {}).get("result"),
    }
    tools, cursor = [], None
    while True:
        r = h.post("tools/list", {"cursor": cursor} if cursor else {})
        tools += r["result"]["tools"]
        cursor = r["result"].get("nextCursor")
        if not cursor:
            break
    res["tools"] = tools
    for method, key in (
        ("prompts/list", "prompts"),
        ("resources/list", "resources"),
        ("resources/templates/list", "resourceTemplates"),
    ):
        r = h.post(method, {}) or {}
        res[key] = r.get("result", {}).get(key) if "result" in r else {"error": r.get("error")}
    write_json(OUT_DIR / f"inventory-{date}.json", res)
    print(f"tools={len(tools)}")


PATH_RE = re.compile(r'\(endpoint (/[^)]*)\)')


def cmd_paths(date: str, candidates_file: Path | None) -> None:
    inv = load_inventory(date)
    specs = endpoint_specs(inv)
    cands = json.loads(candidates_file.read_text("utf-8")) if candidates_file else {}
    only = set(cands) if candidates_file and os.environ.get("PATHS_ONLY_CANDIDATES") else None
    previous = OUT_DIR / f"paths-{date}.json"
    found_prev = json.loads(previous.read_text("utf-8")) if previous.exists() else {}
    h = Hosted()
    h.start()
    found: dict[str, Any] = {}
    for spec in specs:
        key = f"{spec['tool']}/{spec['endpoint']}"
        if only is not None and key not in only:
            found[key] = found_prev.get(key, {"path": None, "how": "skipped"})
            continue
        hosted = h.call(spec["tool"], {"endpoint": spec["endpoint"]})
        htext = "".join(c.get("text", "") for c in hosted.get("content", []))
        m = PATH_RE.search(htext) if hosted.get("isError") else None
        if m:
            found[key] = {
                "path": m.group(1),
                "how": "hosted-error",
                "missing_required_error": scrub(htext)[:400],
            }
        else:
            # Either no required parameters, or the hosted server filled in
            # defaults for them; confirm the path (and defaults) over REST.
            found[key] = {"path": None, "how": "unresolved", "tried": [],
                          "hosted_filled_defaults": bool(spec["required"])}
            try:
                hjson = json.loads(htext)
            except ValueError:
                hjson = None
            for cand in cands.get(key, [spec["endpoint"]]):
                cpath, cparams = (cand, {}) if isinstance(cand, str) else (
                    cand["path"], cand.get("params", {}))
                status, body, _ = rest(cpath, cparams)
                found[key]["tried"].append({"path": cpath, "params": cparams,
                                            "status": status})
                cand = cpath
                try:
                    rjson = json.loads(body) if status == 200 else None
                except ValueError:
                    rjson = None
                if rjson is not None and rjson == hjson:
                    found[key].update(path="/" + cand.lstrip("/"), how="rest-json-equal",
                                      defaults=cparams)
                    break
                if rjson is not None and _same_shape(rjson, hjson):
                    # Live feeds can move between the two calls.
                    found[key].update(path="/" + cand.lstrip("/"), how="rest-shape-match",
                                      defaults=cparams)
                    break
        print(key, found[key]["path"], found[key]["how"])
    write_json(OUT_DIR / f"paths-{date}.json", found)


def _same_shape(a: Any, b: Any) -> bool:
    """Both non-empty lists of objects whose first rows have the same keys."""
    return (
        isinstance(a, list) and isinstance(b, list) and bool(a) and bool(b)
        and isinstance(a[0], dict) and isinstance(b[0], dict)
        and list(a[0]) == list(b[0])
    )


ERROR_CASES = [
    ("quote", {"endpoint": "no-such"}, "invalid_enum_value"),
    ("quote", {"endpoint": "quote", "symbol": 5}, "invalid_type_string"),
    ("statements", {"endpoint": "income-statement", "symbol": "AAPL", "limit": "2"},
     "invalid_type_number"),
    ("news", {"endpoint": "search-stock-news", "symbols": "AAPL"}, "invalid_type_array"),
    ("quote", {"endpoint": "quote", "symbol": "AAPL", "bogus": 1}, "unrecognized_keys"),
    ("quote", {}, "missing_endpoint"),
    ("quote", {"symbol": 5, "bogus": 1}, "multiple_issues"),
    ("chart", {"endpoint": "intraday-1-min", "symbol": "AAPL", "extended": "yes"},
     "invalid_type_boolean"),
    ("no_such_tool", {"endpoint": "x"}, "unknown_tool"),
    ("quote", {"endpoint": "quote"}, "fmp_missing_param"),
    ("quote", {"endpoint": "quote", "symbol": "ZZZZNOTREAL123"}, "fmp_unknown_symbol"),
]


def cmd_errors(date: str) -> None:
    h = Hosted()
    h.start()
    cases = []
    for tool, args, label in ERROR_CASES:
        time.sleep(PAUSE_S)
        resp = h.post("tools/call", {"name": tool, "arguments": args})
        cases.append({"label": label, "tool": tool, "arguments": args,
                      "response": json.loads(scrub(json.dumps(resp)))})
        print(label, json.dumps(resp)[:160])
    write_json(OUT_DIR / f"errors-{date}.json", {"cases": cases})


def cmd_samples(date: str, args_file: Path, only: str | None) -> None:
    inv = load_inventory(date)
    paths = json.loads((OUT_DIR / f"paths-{date}.json").read_text("utf-8"))
    sample_args = json.loads(args_file.read_text("utf-8"))
    out = OUT_DIR / f"samples-{date}"
    out.mkdir(parents=True, exist_ok=True)
    h = Hosted()
    h.start()
    for spec in endpoint_specs(inv):
        key = f"{spec['tool']}/{spec['endpoint']}"
        if only and not re.search(only, key):
            continue
        args = {"endpoint": spec["endpoint"], **sample_args.get(key, {})}
        hosted = h.call(spec["tool"], args)
        htext = "".join(c.get("text", "") for c in hosted.get("content", []))
        rec: dict[str, Any] = {
            "tool": spec["tool"], "arguments": args, "isError": hosted.get("isError"),
            "result_keys": sorted(hosted), "content_types":
            [c.get("type") for c in hosted.get("content", [])],
            "hosted_text_sha256": hashlib.sha256(htext.encode()).hexdigest(),
            "hosted_text_len": len(htext),
        }
        path = (paths.get(key) or {}).get("path")
        rec["rest_path"] = path
        if path and not hosted.get("isError"):
            params = sample_args.get("__rest__" + key) or _rest_params(args)
            status, body, ctype = rest(path, params)
            rec.update(rest_status=status, rest_content_type=ctype.split(";")[0],
                       rest_body_sha256=hashlib.sha256(body).hexdigest(),
                       rest_body_len=len(body))
            try:
                rec["json_equal"] = json.loads(body) == json.loads(htext)
                rec["compact_equal"] = json.dumps(
                    json.loads(body), separators=(",", ":"), ensure_ascii=False
                ) == htext
            except ValueError:
                rec["json_equal"] = rec["compact_equal"] = None
            if len(body) <= FULL_BODY_LIMIT and len(htext) <= FULL_BODY_LIMIT:
                rec["rest_body_gz_hex"] = gzip.compress(body, mtime=0).hex()
                rec["hosted_text"] = htext
        else:
            rec["hosted_text"] = htext[:2000]
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json"
        write_json(out / name, json.loads(scrub(json.dumps(rec))))
        print(key, rec.get("rest_status"), rec.get("json_equal"), rec.get("compact_equal"),
              rec["hosted_text_len"])


RENAMES = {"from_date": "from", "to_date": "to"}


def _rest_params(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        if k == "endpoint":
            continue
        k = RENAMES.get(k, k)
        if isinstance(v, list):
            v = ",".join(map(str, v))
        elif isinstance(v, bool):
            v = str(v).lower()
        out[k] = v
    return out


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    if KEY and KEY in text:
        sys.exit(f"error: refusing to write {path.name}: it contains the key")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    global KEY  # noqa: PLW0603
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command", choices=["inventory", "paths", "errors", "samples"])
    p.add_argument("--date", default=dt.date.today().isoformat())
    p.add_argument("--candidates", type=Path, help="paths: JSON {tool/endpoint: [path,...]}")
    p.add_argument("--args", type=Path, help="samples: JSON {tool/endpoint: {arg: value}}")
    p.add_argument("--only", help="samples: regex over tool/endpoint")
    a = p.parse_args()
    KEY = _load_key()
    if a.command == "inventory":
        cmd_inventory(a.date)
    elif a.command == "paths":
        cmd_paths(a.date, a.candidates)
    elif a.command == "errors":
        cmd_errors(a.date)
    else:
        if not a.args:
            p.error("samples needs --args")
        cmd_samples(a.date, a.args, a.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
