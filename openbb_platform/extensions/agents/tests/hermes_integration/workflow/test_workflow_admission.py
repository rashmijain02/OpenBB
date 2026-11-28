"""Fail-closed admission tests for notebook-free workflows (#1340, T01)."""

from __future__ import annotations

import copy

import pytest
from openbb_agents.hermes_integration.admission import admit_workflow
from openbb_agents.hermes_integration.workflow import workflow_manifest_sha256

from .conftest import load_fixture


def codes(admission) -> set[str]:
    return {r.code for r in admission.rejections}


def test_shipped_synthetic_workflow_admits_against_matching_live_hashes(
    shipped_document, live_tools
):
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert admission.admitted, admission.rejections
    assert admission.rejections == ()
    assert admission.workflow_id == "synthetic.concentration_review"
    assert admission.workflow_manifest_sha256 == workflow_manifest_sha256(
        shipped_document
    )


def test_unknown_access_literal_rejected(live_tools):
    admission = admit_workflow(load_fixture("unknown-access"), live_tools=live_tools)
    assert not admission.admitted
    assert "unknown_access" in codes(admission)


def test_unknown_access_version_rejected(live_tools):
    admission = admit_workflow(load_fixture("unknown-version"), live_tools=live_tools)
    assert not admission.admitted
    assert "access_version_unsupported" in codes(admission)


def test_supported_but_undefined_access_version_rejected(shipped_document, live_tools):
    shipped_document["access_version"] = 99
    admission = admit_workflow(
        shipped_document, live_tools=live_tools, supported_access_versions={1, 99}
    )
    assert "access_version_unsupported" in codes(admission)


def test_v2_household_literal_denied_as_unmapped(live_tools):
    admission = admit_workflow(
        load_fixture("v2-household"),
        live_tools=live_tools,
        supported_access_versions={1, 2},
    )
    assert not admission.admitted
    assert "access_unmapped" in codes(admission)
    assert "unknown_access" not in codes(admission)


def test_v2_manifest_is_unsupported_by_default(live_tools):
    admission = admit_workflow(load_fixture("v2-household"), live_tools=live_tools)
    assert "access_version_unsupported" in codes(admission)


def test_v2_literal_inside_a_v1_manifest_is_unknown(shipped_document, live_tools):
    pin = shipped_document["capabilities"]["platform:story_concentration"]
    pin["access"] = "household_meta"
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "unknown_access" in codes(admission)


def test_access_outside_allowed_set_not_granted(shipped_document, live_tools):
    admission = admit_workflow(
        shipped_document, live_tools=live_tools, allowed_access={"metadata"}
    )
    assert not admission.admitted
    assert "access_not_granted" in codes(admission)
    granted = admit_workflow(
        shipped_document,
        live_tools=live_tools,
        allowed_access={"analysis", "artifact"},
    )
    assert granted.admitted


def test_live_hash_mismatch_is_schema_drift(live_tools):
    admission = admit_workflow(load_fixture("drifted"), live_tools=live_tools)
    assert not admission.admitted
    drift = [r for r in admission.rejections if r.code == "schema_drift"]
    assert len(drift) == 1  # only the one drifted pin


def test_tool_absent_from_server_rejected(shipped_document, live_tools):
    del live_tools["platform:story_construction_targets"]
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "tool_absent" in codes(admission)
    assert "schema_drift" not in codes(admission)


def test_tool_of_same_name_on_other_server_never_counts(shipped_document, live_tools):
    live = {
        ("other:story_concentration" if k.endswith("story_concentration") else k): v
        for k, v in live_tools.items()
    }
    admission = admit_workflow(shipped_document, live_tools=live)
    assert "tool_absent" in codes(admission)


def test_unknown_manifest_field_is_schema_invalid(shipped_document, live_tools):
    shipped_document["surprise"] = True
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "schema_invalid" in codes(admission)
    assert not admission.admitted


def test_schema_version_2_rejected(shipped_document, live_tools):
    shipped_document["schema_version"] = 2
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "schema_invalid" in codes(admission)


@pytest.mark.parametrize("name", ["notebook-path", "cells-field", "kernel-server"])
def test_notebook_dependency_rejected(name, live_tools):
    admission = admit_workflow(load_fixture(name), live_tools=live_tools)
    assert not admission.admitted
    assert "notebook_dependency" in codes(admission)


@pytest.mark.parametrize(
    "text",
    [
        "see portfolio/03.ipynb for the walkthrough",
        "reads notebooks/portfolio/03.py",
        "reads notebooks_local\\scratch",
        "see docs/examples/foo",
    ],
)
def test_notebook_reference_inside_free_text_rejected(
    shipped_document, live_tools, text
):
    shipped_document["limitations"].append(text)
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "notebook_dependency" in codes(admission)


def test_plain_words_about_notebooks_are_not_a_dependency(shipped_document, live_tools):
    shipped_document["limitations"].append("Runs without notebooks of any kind.")
    assert admit_workflow(shipped_document, live_tools=live_tools).admitted


def test_cyclic_graph_rejected(live_tools):
    admission = admit_workflow(load_fixture("cyclic"), live_tools=live_tools)
    assert not admission.admitted
    assert "graph_invalid" in codes(admission)


def test_unresolved_stage_capability_rejected(shipped_document, live_tools):
    shipped_document["stages"][0]["capabilities"] = ["platform:nope"]
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "capability_unresolved" in codes(admission)


def test_stage_without_capability_is_graph_invalid(shipped_document, live_tools):
    shipped_document["stages"][0]["capabilities"] = []
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "graph_invalid" in codes(admission)


def test_input_from_non_upstream_stage_is_graph_invalid(shipped_document, live_tools):
    shipped_document["stages"][0]["inputs"] = [
        {"name": "x", "output": "construction_result", "from_stage": "construction"}
    ]
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "graph_invalid" in codes(admission)


@pytest.mark.parametrize(
    "garbage",
    [None, 42, "text", b"\x00\xff", [], {}, {"schema_version": 1}],
)
def test_admission_never_raises_on_garbage(garbage, live_tools):
    admission = admit_workflow(garbage, live_tools=live_tools)
    assert not admission.admitted
    assert admission.rejections


def test_admission_never_raises_on_deep_nesting(shipped_document, live_tools):
    deep: dict = {}
    node = deep
    for _ in range(50_000):
        node["x"] = {}
        node = node["x"]
    shipped_document["limitations"] = [deep]
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert not admission.admitted


def test_admission_does_not_mutate_its_input(shipped_document, live_tools):
    before = copy.deepcopy(shipped_document)
    admit_workflow(shipped_document, live_tools=live_tools)
    assert shipped_document == before


def test_rejection_detail_never_echoes_input_values(shipped_document, live_tools):
    shipped_document["title"] = ["SECRET-VALUE-123"]
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert "SECRET-VALUE-123" not in repr(admission)


def _run_cli(argv, capsys):
    from openbb_agents.hermes_integration import (  # pylint: disable=import-outside-toplevel
        workflow_admit,
    )

    code = workflow_admit.main(argv)
    return code, capsys.readouterr().out


def test_cli_exit_codes(tmp_path, live_tools, capsys):
    import json  # pylint: disable=import-outside-toplevel

    live = tmp_path / "live.json"
    live.write_text(json.dumps(live_tools), encoding="utf-8")
    ok, out = _run_cli(
        ["--workflow", "synthetic.concentration_review", "--live-file", str(live)],
        capsys,
    )
    assert ok == 0 and json.loads(out)["admitted"] is True

    drifted = str(
        __import__("pathlib").Path(__file__).parent
        / "fixtures"
        / "drifted.workflow.json"
    )
    bad, out = _run_cli(["--workflow-file", drifted, "--live-file", str(live)], capsys)
    assert bad == 2
    assert [r["code"] for r in json.loads(out)["rejections"]] == ["schema_drift"]

    usage, _ = _run_cli(
        ["--workflow", "../../etc/passwd", "--live-file", str(live)], capsys
    )
    assert usage == 3
    missing, _ = _run_cli(
        ["--workflow", "no.such.one", "--live-file", str(live)], capsys
    )
    assert missing == 3


# --- Review finding 3: declared access is checked against the reviewed class.


def test_shipped_pins_declare_at_least_their_reviewed_access_class():
    """The real classes come from the reviewed capability policy, not the manifest."""
    # pylint: disable=import-outside-toplevel
    from openbb_agents.hermes_integration.tool_access import reviewed_tool_access

    classes = reviewed_tool_access()
    assert classes["platform:story_concentration"] == {"provider_read"}
    assert classes["platform:story_run_checkpoint"] == {"story_state"}
    assert classes["platform:story_run_create"] == {"story_state"}


def test_state_writing_tool_declared_as_analysis_is_access_understated(
    shipped_document, live_tools
):
    pin = shipped_document["capabilities"]["platform:story_run_checkpoint"]
    pin["access"] = "analysis"
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert not admission.admitted
    assert codes(admission) == {"access_understated"}


def test_access_understated_against_an_explicit_class_map(shipped_document, live_tools):
    """A tool whose real class is financial_mutation is covered by no v1 word."""
    tool_access = {key: {"provider_read"} for key in live_tools}
    tool_access["platform:story_concentration"] = {"financial_mutation"}
    admission = admit_workflow(
        shipped_document, live_tools=live_tools, tool_access=tool_access
    )
    assert codes(admission) == {"access_understated"}
    assert admit_workflow(
        shipped_document,
        live_tools=live_tools,
        tool_access={key: {"provider_read"} for key in live_tools},
    ).admitted


def test_unclassified_tool_is_rejected(shipped_document, live_tools):
    tool_access = {key: {"provider_read"} for key in live_tools}
    del tool_access["platform:story_construction_targets"]
    admission = admit_workflow(
        shipped_document, live_tools=live_tools, tool_access=tool_access
    )
    assert codes(admission) == {"access_unclassified"}


# --- Review finding 5: one capability per stage until fan-out is supported.


def test_multi_capability_stage_is_rejected(shipped_document, live_tools):
    shipped_document["stages"][1]["capabilities"].append("platform:story_concentration")
    admission = admit_workflow(shipped_document, live_tools=live_tools)
    assert codes(admission) == {"multi_capability_unsupported"}


# --- Review finding 8: behaviour, not vocabulary constants.


@pytest.mark.parametrize(
    "literal", ["household_meta", "tax_compute", "document_evidence"]
)
def test_v2_only_literal_is_unknown_under_v1_and_unmapped_under_v2(
    shipped_document, live_tools, literal
):
    shipped_document["capabilities"]["platform:story_concentration"]["access"] = literal
    under_v1 = admit_workflow(
        shipped_document, live_tools=live_tools, supported_access_versions={1, 2}
    )
    assert codes(under_v1) == {"unknown_access"}
    shipped_document["access_version"] = 2
    under_v2 = admit_workflow(
        shipped_document, live_tools=live_tools, supported_access_versions={1, 2}
    )
    assert codes(under_v2) == {"access_unmapped"}


# --- Re-review N3: whole-tool classification and the disposition decision.


class _Decision:
    def __init__(self, access_class, disposition="direct"):
        self.access_class = access_class
        self.disposition = disposition


class _SyntheticPolicy:
    """Synthetic reviewed policy: ``classify_operation`` by (method, path)."""

    def __init__(self, table):
        self.table = table

    def classify_operation(
        self, scope, method, path
    ):  # pylint: disable=unused-argument
        outcome = self.table[(method, path)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _row(tool, method, path):
    return {"scope": "s", "mcp_tool": tool, "method": method, "path": path}


def test_one_unclassifiable_row_leaves_the_whole_tool_unclassified():
    """A tool is never left with a partial class when any of its rows fails."""
    # pylint: disable=import-outside-toplevel
    from openbb_agents.hermes_integration.tool_access import derive_tool_policy

    policy = _SyntheticPolicy(
        {
            ("GET", "/a"): _Decision("provider_read"),
            ("POST", "/a"): ValueError("ambiguous"),
            ("GET", "/b"): _Decision("provider_read"),
        }
    )
    rows = [_row("a", "GET", "/a"), _row("a", "POST", "/a"), _row("b", "GET", "/b")]
    result = derive_tool_policy(policy, rows, {"platform": "s"})
    assert "platform:a" not in result.classes
    assert result.classes["platform:b"] == {"provider_read"}
    assert not result.denied


def test_a_denied_disposition_makes_the_tool_unadmittable():
    """Any non-admittable row disposition denies the tool; the rest is unaffected."""
    # pylint: disable=import-outside-toplevel
    from openbb_agents.hermes_integration.tool_access import derive_tool_policy

    policy = _SyntheticPolicy(
        {
            ("GET", "/a"): _Decision("provider_read", "direct"),
            ("POST", "/a"): _Decision("financial_mutation", "restricted"),
            ("GET", "/b"): _Decision("provider_read", "workspace_indirect"),
        }
    )
    rows = [_row("a", "GET", "/a"), _row("a", "POST", "/a"), _row("b", "GET", "/b")]
    result = derive_tool_policy(policy, rows, {"platform": "s"})
    assert result.denied == {"platform:a"}
    assert "platform:a" not in result.classes
    assert "platform:b" in result.classes


def test_admission_rejects_a_policy_denied_tool(shipped_document, live_tools):
    tool_access = {key: {"provider_read"} for key in live_tools}
    admission = admit_workflow(
        shipped_document,
        live_tools=live_tools,
        tool_access=tool_access,
        denied_tools={"platform:story_concentration"},
    )
    assert codes(admission) == {"access_denied_by_policy"}
    assert admit_workflow(
        shipped_document, live_tools=live_tools, tool_access=tool_access
    ).admitted
