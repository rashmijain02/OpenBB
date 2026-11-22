"""Redaction and data minimization for the Workspace agent (#1272).

Everything the copilot sends to the external model provider passes through
:func:`sanitize` (structured widget data) or :func:`redact_text` (free text):

- identifier fields and columns (account, basket, owner, user, customer,
  ``portfolio_id`` and similar) are dropped, in row objects at any depth, in
  column-oriented payloads and in Markdown tables;
- credential fields (``apiKey``, ``authToken``, ``sessionId`` ...) are replaced
  by ``[redacted]``;
- credential-looking values (bearer/basic tokens, JWTs, AWS keys, ``key=`` /
  ``token:`` values, ``user:pass@`` in URLs) are redacted.

Every regular expression uses bounded quantifiers so redaction stays linear in
the input length; callers also cap the input size before calling in.
"""

import re
from collections.abc import Mapping
from typing import Any

# Keys are compared lowercased with every non-alphanumeric removed, so
# ``api_key``, ``apiKey``, ``x-api-key`` and ``API-KEY`` look alike.
_SECRET_KEYS_EXACT = frozenset(
    {
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "credentials",
        "jwt",
        "key",
        "passwd",
        "password",
        "pwd",
        "secret",
        "session",
        "sig",
        "signature",
        "token",
    }
)
_SECRET_KEY_SUFFIXES = (
    "accesskey",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "jwt",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "sessionid",
    "sessiontoken",
    "token",
)
_SECRET_KEY_PREFIXES = ("accesskey", "apikey", "password", "secretkey")

# Account, basket, owner and user identifiers are not needed to explain the
# data, so they never leave the backend. A key is split into camelCase /
# snake_case / kebab-case tokens; it is an identifier when any token is one of
# ``_ID_WORDS`` (at any position: ``pm_user``, ``primary_account_id``), when a
# ``_ID_QUALIFIED`` token sits next to an id-like token (``portfolio_id``), or
# when the joined key contains a word+id compound (``primaryaccountid``).
_ID_WORDS = frozenset(
    {
        "account",
        "accounts",
        "acct",
        "accts",
        "basket",
        "baskets",
        "client",
        "clients",
        "customer",
        "customers",
        "email",
        "login",
        "owner",
        "owners",
        "phone",
        "ssn",
        "user",
        "username",
        "users",
    }
)
_ID_QUALIFIED = frozenset({"book", "household", "member", "person", "portfolio"})
_ID_SUFFIXES = ("id", "ids", "key", "name", "no", "num", "number", "ref", "uuid")
_ID_COMPOUNDS = tuple(
    word + suffix
    for word in (
        "account",
        "acct",
        "basket",
        "client",
        "customer",
        "household",
        "member",
        "owner",
        "portfolio",
        "user",
    )
    for suffix in _ID_SUFFIXES
)
_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")

_SECRET_VALUE_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    # user:password@ inside a URL. Every quantifier is bounded so the scan is
    # linear in the text length (no backtracking blow-up on ``a-a-a-...``).
    (
        re.compile(
            r"(?i)\b([a-z][a-z0-9+.\-]{0,31}://)[^/\s:@]{1,256}:[^/\s@]{1,256}@"
        ),
        r"\1[redacted]@",
    ),
    # ``Bearer <token>`` / ``Basic <base64>``; the token must hold a digit or
    # symbol so prose ("Basic Materials", "bearer bonds") is untouched.
    (
        re.compile(
            r"(?i)\bbearer[ \t]{1,8}(?=[A-Za-z0-9._~+/=\-]{0,512}[0-9=+/_.\-])"
            r"[A-Za-z0-9._~+/=\-]{8,}"
        ),
        "Bearer [redacted]",
    ),
    (
        re.compile(
            r"(?i)\bbasic[ \t]{1,8}(?=[A-Za-z0-9._~+/=\-]{0,512}[0-9=+/_.\-])"
            r"[A-Za-z0-9._~+/=\-]{8,}"
        ),
        "Basic [redacted]",
    ),
    # JSON Web Tokens
    (
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"),
        "[redacted]",
    ),
    # AWS access key ids
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[redacted]"),
    # name=value (query strings, config lines)
    (
        re.compile(
            r"(?i)\b(api[_\-]?key|access[_\-]?key|secret[_\-]?key|access[_\-]?token|"
            r"auth[_\-]?token|session[_\-]?id|token|secret|password|passwd|key|"
            r"sig|signature|jwt)=([^&\s\"'#]+)"
        ),
        r"\1=[redacted]",
    ),
    # name: value
    (
        re.compile(
            r"(?i)\b(api[_\-]?key|access[_\-]?key|secret[_\-]?key|access[_\-]?token|"
            r"auth[_\-]?token|session[_\-]?id|token|secret|password|passwd|jwt)"
            r"[ \t]{0,8}:[ \t]{0,8}(?!\[redacted\])[^\s,;\"']+"
        ),
        r"\1: [redacted]",
    ),
    (
        re.compile(
            r"\b(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|"
            r"github_pat_[A-Za-z0-9_]{8,})"
        ),
        "[redacted]",
    ),
    # Identifiers written into text: ``account_id=…``, ``**Account ID:** …``
    (
        re.compile(
            r"(?i)\b((?:account|basket|owner|user|customer|client)[ _\-]?"
            r"(?:id|ids|number|no|name))\b[ \t]{0,4}(?:\*\*)?[ \t]{0,4}[:=]"
            r"[ \t]{0,4}(?:\*\*)?[ \t]{0,4}[^\s,;&|*]+"
        ),
        r"\1: [redacted]",
    ),
)
REDACTED = "[redacted]"


def _norm(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_secret_key(key: Any) -> bool:
    """Return whether a field name holds a credential."""
    norm = _norm(key)
    return (
        norm in _SECRET_KEYS_EXACT
        or norm.endswith(_SECRET_KEY_SUFFIXES)
        or norm.startswith(_SECRET_KEY_PREFIXES)
    )


def is_identifier_key(key: Any) -> bool:
    """Return whether a field name is an account/basket/owner/user identifier."""
    tokens = [token.lower() for token in _TOKEN_RE.findall(str(key)[:200])]
    if any(token in _ID_WORDS for token in tokens):
        return True
    if any(token in _ID_QUALIFIED for token in tokens) and any(
        token in _ID_SUFFIXES for token in tokens
    ):
        return True
    norm = _norm(key)[:200]
    return any(compound in norm for compound in _ID_COMPOUNDS)


def _table_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return body.split("|")


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return (
        "-" in stripped
        and stripped.startswith(("|", "-", ":"))
        and not stripped.replace("|", "").replace(":", "").replace("-", "").strip()
    )


def _mask_markdown_tables(text: str) -> str:
    """Mask the cells of Markdown table columns whose header is an identifier."""
    if "|" not in text:
        return text
    lines = text.split("\n")
    masked: set[int] = set()
    in_table = False
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            in_table = False
            masked = set()
            continue
        if (
            not in_table
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            masked = {
                i
                for i, cell in enumerate(_table_cells(line))
                if is_identifier_key(cell.strip())
            }
            in_table = True
            continue
        if not in_table or not masked or _is_table_separator(line):
            continue
        cells = _table_cells(line)
        for i in masked:
            if i < len(cells):
                cells[i] = f" {REDACTED} "
        lines[index] = "|" + "|".join(cells) + "|"
    return "\n".join(lines)


def redact_text(text: str) -> str:
    """Redact credentials and written-out identifiers (linear-time patterns)."""
    text = _mask_markdown_tables(text)
    for pattern, replacement in _SECRET_VALUE_RES:
        text = pattern.sub(replacement, text)
    return text


def _column_name(column: Any) -> Any:
    if isinstance(column, Mapping):
        for key in ("field", "name", "headerName", "id", "key"):
            if column.get(key) is not None:
                return column[key]
        return ""
    return column


def _drop_positions(rows: list[Any], drop: set[int]) -> list[Any]:
    return [
        (
            [cell for i, cell in enumerate(row) if i not in drop]
            if isinstance(row, list)
            else row
        )
        for row in rows
    ]


def _drop_identifier_columns(value: Any) -> Any:
    """Drop identifier columns from column- or row-oriented payloads.

    Handles ``{"columns": [...], "data"|"rows"|"values": [[...]]}`` (names as
    strings or objects with ``field`` / ``name`` / ``headerName``) and a list of
    lists whose first row is a header.
    """
    if isinstance(value, Mapping) and isinstance(value.get("columns"), list):
        columns = value["columns"]
        drop = {i for i, c in enumerate(columns) if is_identifier_key(_column_name(c))}
        if not drop:
            return value
        out = dict(value)
        out["columns"] = [c for i, c in enumerate(columns) if i not in drop]
        for key in ("data", "rows", "values"):
            if isinstance(out.get(key), list):
                out[key] = _drop_positions(out[key], drop)
        return out
    if (
        isinstance(value, list)
        and value
        and isinstance(value[0], list)
        and all(isinstance(cell, str) for cell in value[0])
    ):
        drop = {i for i, cell in enumerate(value[0]) if is_identifier_key(cell)}
        if drop:
            return _drop_positions(value, drop)
    return value


def sanitize(value: Any) -> Any:
    """Return a copy of widget data that is safe to send to the model.

    Identifier fields (account, basket, owner, user, ...) and identifier
    columns of column-oriented payloads and Markdown tables are dropped or
    masked, credential fields are replaced by ``[redacted]``, and
    credential-looking values inside strings are redacted. Callers bound the
    input size first (:func:`_preclip`).
    """
    value = _drop_identifier_columns(value)
    if isinstance(value, Mapping):
        return {
            str(key): (REDACTED if is_secret_key(key) else sanitize(item))
            for key, item in value.items()
            if not is_identifier_key(key)
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


__all__ = ["REDACTED", "is_identifier_key", "is_secret_key", "redact_text", "sanitize"]
