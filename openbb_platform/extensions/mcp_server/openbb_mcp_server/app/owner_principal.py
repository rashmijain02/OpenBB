"""In-process owner principal of ``create_mcp_server`` (#1342).

A jobs worker that runs an approved plan acts for the plan's recorded owner.
The override is in-process only (never from a request) and requires that the
server already derived a principal from effective token credentials.
"""

from __future__ import annotations


def effective_story_principal(
    derived: str | None, owner_principal: str | None
) -> str | None:
    """Return the story principal after the optional in-process owner override.

    ``derived`` is the principal from the server's token credentials. Without
    an override it is returned unchanged. With one, ``derived`` must exist.
    """
    if owner_principal is None:
        return derived
    if derived is None:
        raise RuntimeError("owner_principal needs effective token credentials (#1342).")
    return owner_principal
