"""The parity MCP server: hosted FMP tool surface over an ``Upstream`` (#1299).

Built on the low-level ``mcp`` server so ``tools/list`` is served verbatim from
the recorded hosted inventory and every tool result is constructed here:
``content`` is byte-identical to the hosted server, provenance goes in
``_meta["openbb/provenance"]`` only.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server

from openbb_fmp_cached_mcp import __version__
from openbb_fmp_cached_mcp.endpoint_map import PARAM_RENAMES, endpoint_spec, load_tools
from openbb_fmp_cached_mcp.render import Rendered, render_response
from openbb_fmp_cached_mcp.upstream import Upstream, to_rest_params
from openbb_fmp_cached_mcp.validation import validate_arguments

logger = logging.getLogger(__name__)

SERVER_NAME = "fmp_cached MCP Server"
PROVENANCE_KEY = "openbb/provenance"


class Scrubber:
    """Removes the server's FMP key from any outgoing text."""

    def __init__(self, secret: str = "") -> None:
        self.secret = secret

    def __call__(self, text: str) -> str:
        """Return ``text`` with the key replaced by ``<redacted>``."""
        if self.secret and self.secret in text:
            text = text.replace(self.secret, "<redacted>")
        return text


def _apply_defaults(spec: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Fill required parameters the hosted server defaults (e.g. ``symbol=AAPL``)."""
    defaults: dict[str, Any] = spec.get("defaults") or {}
    if not defaults:
        return args
    reverse = {v: k for k, v in PARAM_RENAMES.items()}
    out = dict(args)
    for rest_name, value in defaults.items():
        name = reverse.get(rest_name, rest_name)
        if name not in out:
            out[name] = value.split(",") if name == "symbols" else value
    return out


def _result(rendered: Rendered, meta: dict[str, Any] | None) -> types.CallToolResult:
    content: list[types.ContentBlock] = [
        types.TextContent(type="text", text=rendered.text)
    ]
    if rendered.is_error:
        return types.CallToolResult(content=content, isError=True, _meta=meta)
    # Hosted success results carry no ``isError`` key at all; model_construct
    # keeps it ``None`` so the exclude-none wire dump omits it the same way.
    return types.CallToolResult.model_construct(
        content=content, isError=None, meta=meta, structuredContent=None
    )


def _provenance(
    state: str,
    source: str,
    reason: str | None = None,
    as_of: dt.datetime | None = None,
) -> dict[str, Any]:
    """``_meta`` provenance in the #1269 DataState vocabulary."""
    when = as_of or dt.datetime.now(dt.timezone.utc)
    prov: dict[str, Any] = {
        "state": state,
        "source": source,
        "asOf": when.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if reason:
        prov["reason"] = reason
    return {PROVENANCE_KEY: prov}


async def call_tool(
    upstream: Upstream | None,
    scrub: Scrubber,
    name: str,
    arguments: dict[str, Any] | None,
) -> types.CallToolResult:
    """Validate, map, fetch and render one hosted-compatible tool call."""
    cleaned, error = validate_arguments(name, arguments)
    if error is not None:
        return _result(Rendered(error, True), None)
    if cleaned is None:  # validate_arguments returns one of the two
        return _result(Rendered("fmp_cached: invalid arguments", True), None)
    endpoint = cleaned["endpoint"]
    spec = endpoint_spec(name, endpoint)
    args = _apply_defaults(spec, cleaned)
    params = to_rest_params(args, PARAM_RENAMES)
    if upstream is None:
        return _result(Rendered("fmp_cached: no upstream configured", True), None)
    fetch_tool = getattr(upstream, "fetch_tool", None)
    try:
        if fetch_tool is not None:  # persistent store in front of FMP (#1300)
            result = await fetch_tool(name, args)
            resp, state, source = result.response, result.state, result.source
            reason, as_of = result.reason, result.as_of
        else:
            resp = await upstream.fetch(spec["path"], params)
            state, source, reason, as_of = "live", "fmp", None, None
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-except
        # Never echo exception text: it can carry URLs or credentials.
        logger.warning("upstream %s failed: %s", spec["path"], type(exc).__name__)
        text = (
            f'Bad request for tool "{name}" (endpoint {spec["path"]}): '
            f"upstream unavailable ({type(exc).__name__})"
        )
        return _result(
            Rendered(text, True), _provenance("unavailable", "fmp", "upstream-error")
        )
    rendered = render_response(
        tool=name, arguments=args, path=spec["path"], status=resp.status, body=resp.body
    )
    rendered = Rendered(scrub(rendered.text), rendered.is_error)
    if rendered.is_error:
        state = "unavailable"
    return _result(rendered, _provenance(state, source, reason, as_of))


def build_server(upstream: Upstream | None) -> Server:
    """Return a low-level MCP server exposing the hosted tool surface."""
    server: Server = Server(SERVER_NAME, version=__version__)
    scrub = Scrubber(getattr(upstream, "secret", "") or "")
    tools = [types.Tool.model_validate(t) for t in load_tools()]

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return tools

    @server.call_tool(validate_input=False)
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        return await call_tool(upstream, scrub, name, arguments)

    # The hosted server advertises ``tools.listChanged: true``; match it for
    # every transport (stdio and the streamable-HTTP session manager).
    base_init = server.create_initialization_options

    def _init_options(notification_options=None, experimental_capabilities=None):
        return base_init(
            notification_options or NotificationOptions(tools_changed=True),
            experimental_capabilities,
        )

    server.create_initialization_options = _init_options  # type: ignore[method-assign]
    return server
