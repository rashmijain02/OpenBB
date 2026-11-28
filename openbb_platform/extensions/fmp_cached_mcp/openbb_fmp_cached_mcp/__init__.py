"""MCP server with tool-for-tool parity to FMP's hosted MCP server (#1298).

Tools, arguments, error texts and payloads match
``https://financialmodelingprep.com/mcp`` (snapshot 2026-11-23); data is served
from the ``fmp_cached`` persistent store when it holds it and from FMP REST
otherwise. Provenance is reported in ``result._meta`` only.
"""

__version__ = "0.1.0"
