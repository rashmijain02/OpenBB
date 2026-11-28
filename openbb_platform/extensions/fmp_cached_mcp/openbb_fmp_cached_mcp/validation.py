"""Validate tool arguments the way the hosted server's zod schemas do (#1299).

The hosted server converts each tool's JSON schema to zod: one object schema,
``endpoint`` a required string enum, every other property optional. Unknown
keys are stripped silently (despite ``additionalProperties: false``), and a
failure becomes a tool result whose text is::

    MCP error -32602: Input validation error: Invalid arguments for tool <tool>: <issues>

where ``<issues>`` is ``JSON.stringify(zodIssues, null, 2)``. Issue key order
follows zod's own construction order, which differs between issue kinds.
"""

from __future__ import annotations

import json
from typing import Any

from openbb_fmp_cached_mcp.endpoint_map import load_tools

PREFIX = "MCP error -32602: Input validation error: Invalid arguments for tool {tool}: "


def _parsed_type(value: Any) -> str:
    """Zod ``getParsedType`` for JSON values."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _join(options: list[str]) -> str:
    return " | ".join(f"'{o}'" for o in options)


def _check(schema: dict[str, Any], value: Any, path: list[Any]) -> list[dict[str, Any]]:
    if "enum" in schema:
        options = schema["enum"]
        if not isinstance(value, str):
            received = _parsed_type(value)
            return [
                {
                    "expected": _join(options),
                    "received": received,
                    "code": "invalid_type",
                    "path": path,
                    "message": f"Expected {_join(options)}, received {received}",
                }
            ]
        if value not in options:
            return [
                {
                    "received": value,
                    "code": "invalid_enum_value",
                    "options": options,
                    "path": path,
                    "message": (
                        f"Invalid enum value. Expected {_join(options)}, received '{value}'"
                    ),
                }
            ]
        return []
    expected = schema.get("type")
    received = _parsed_type(value)
    if expected != received:
        return [
            {
                "code": "invalid_type",
                "expected": expected,
                "received": received,
                "path": path,
                "message": f"Expected {expected}, received {received}",
            }
        ]
    if expected == "array":
        issues: list[dict[str, Any]] = []
        for i, item in enumerate(value):
            issues += _check(schema.get("items", {}), item, [*path, i])
        return issues
    return []


def _tool_schemas() -> dict[str, dict[str, Any]]:
    return {t["name"]: t["inputSchema"] for t in load_tools()}


def validate_arguments(
    tool: str, arguments: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(cleaned_arguments, None)`` or ``(None, hosted_error_text)``."""
    schema = _tool_schemas().get(tool)
    if schema is None:
        return None, f"MCP error -32602: Tool {tool} not found"
    args = arguments or {}
    props: dict[str, Any] = schema["properties"]
    required = set(schema.get("required", []))
    issues: list[dict[str, Any]] = []
    for name, prop in props.items():  # zod walks the shape in definition order
        if name not in args:
            if name in required:
                expected = _join(prop["enum"]) if "enum" in prop else prop.get("type")
                issues.append(
                    {
                        "expected": expected,
                        "received": "undefined",
                        "code": "invalid_type",
                        "path": [name],
                        "message": "Required",
                    }
                )
            continue
        issues += _check(prop, args[name], [name])
    if issues:
        text = PREFIX.format(tool=tool) + json.dumps(
            issues, indent=2, ensure_ascii=False
        )
        return None, text
    return {k: v for k, v in args.items() if k in props}, None
