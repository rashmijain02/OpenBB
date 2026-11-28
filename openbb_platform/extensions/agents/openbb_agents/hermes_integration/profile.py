"""Finance runtime profile: pinned SHAs, remotes, Python and database names (#1338)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ComponentPin(_Strict):
    """A git checkout pinned by SHA and remote; its directory comes from an env var."""

    dir_env: str
    expected_sha: str = Field(min_length=7)
    expected_remote: str
    agent_dir_env: str | None = None  # WebUI only: env var naming its agent dir


class PythonPin(_Strict):
    """Interpreter the Hermes runtime must use."""

    requires: str
    supported: str
    venv_env: str


class DatabasePin(_Strict):
    """Expected fmp_cached database name."""

    expected: str


class WebProfilePin(_Strict):
    """Finance-web WebUI profile (#1342): the MCP server, tool allowlist and bundle pin."""

    mcp_server: str = Field(default="openbb", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # Hermes toolsets the WebUI ``cli`` surface may list besides the MCP toolset.
    allowed_toolsets: list[str] = Field(default_factory=lambda: ["clarify"])
    # ``skills_admission.tree_sha256`` of the rendered ``openbb-hfp`` bundle.
    extension_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FinanceRuntimeProfile(_Strict):
    """Pins that define the qualified finance runtime. No paths or secrets."""

    schema_version: int
    hermes_agent: ComponentPin
    hermes_webui: ComponentPin
    python: PythonPin
    database: DatabasePin
    gateway_base_url: str
    gateway_key_env: str | None = None  # env var NAME holding the scoped gateway key
    mcp_catalog_sha256: str | None = (
        None  # pinned hash of the admitted MCP tool catalog
    )
    private_alias_allowlist: list[str] = Field(default_factory=list)
    # Loopback base URLs of allowlisted local inference runtimes (#1338-T03).
    local_backends: list[str] = Field(default_factory=list)
    skills_roots: list[str] = Field(default_factory=list)
    # Admitted local-tier skills (#1339-T02): POSIX path relative to
    # ``$HERMES_HOME/skills`` -> ``skills_admission.tree_sha256`` pin.
    admitted_skills: dict[str, str] = Field(default_factory=dict)
    # Finance-web WebUI profile (#1342); absent means no web rows are evaluated.
    web: WebProfilePin | None = None


def load_profile(path: Path) -> FinanceRuntimeProfile:
    """Load a profile YAML; raises ``OSError``/``ValueError`` when unreadable."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FinanceRuntimeProfile.model_validate(data)
