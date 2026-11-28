"""In-process owner principal override of ``create_mcp_server`` (#1342)."""

import pytest
from openbb_mcp_server.app.owner_principal import effective_story_principal


def test_no_override_keeps_derived_principal():
    assert effective_story_principal("hermes#a", None) == "hermes#a"
    assert effective_story_principal(None, None) is None


def test_override_replaces_derived_principal():
    assert effective_story_principal("hermes#a", "hermes#owner") == "hermes#owner"


def test_override_without_token_credentials_is_refused():
    with pytest.raises(RuntimeError, match="effective token credentials"):
        effective_story_principal(None, "hermes#owner")
