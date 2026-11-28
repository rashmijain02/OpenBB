"""Independent reference qualification of the statistical bridges (#1357 T02).

Every expected value lives in ``fixtures/independent_references.json`` and was
produced without the code under test: closed-form evaluations with the stdlib
``statistics.NormalDist`` (the code uses scipy / ``math.erf``), exact-fraction
enumerations of every CSCV partition, hand-built CPCV index tables, or values
verified against the public paper text (``paper_check``, cited by page). There
is no regeneration path.
"""

from __future__ import annotations

import copy
import importlib
import itertools
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from openbb_backtest.validation import qualify, stats

# ``validation/__init__`` re-exports the ``pbo`` / ``cpcv`` functions under the
# submodule names, so import the modules themselves explicitly.
pbo_mod = importlib.import_module("openbb_backtest.validation.pbo")
cpcv_mod = importlib.import_module("openbb_backtest.validation.cpcv")

FIXTURE = Path(__file__).parent / "fixtures" / "independent_references.json"
REFS = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in REFS["cases"]}


def _case(case_id: str) -> dict:
    return CASES[case_id]


def _ids(kind: str) -> list[str]:
    return [c["id"] for c in REFS["cases"] if c["kind"] == kind]


# ---- fixture hygiene -------------------------------------------------------


def test_every_case_declares_source_tolerance_and_derivation():
    allowed = {"exact", "abs", "half_ulp_published"}
    assert len(CASES) == len(REFS["cases"]), "duplicate case ids"
    for case in REFS["cases"]:
        assert case["source"] == "hand-computed" or "p." in case["source"], case["id"]
        assert case["tolerance"]["kind"] in allowed, case["id"]
        assert case["derivation"].strip(), case["id"]
        check = case.get("paper_check")
        if check:
            assert "p." in check["legible_text"] and "pp." in check["source"], case[
                "id"
            ]
            assert check["tolerance"]["kind"] == "half_ulp_published"


# ---- DSR / PSR / E[max] / MinBTL -------------------------------------------


@pytest.mark.parametrize("case_id", _ids("dsr"))
def test_dsr_matches_independent_reference(case_id):
    case = _case(case_id)
    inp = case["inputs"]
    got = stats.deflated_sharpe(
        inp["sr"],
        inp["n_trials"],
        inp["skew"],
        inp["kurt"],
        inp["n_obs"],
        sr_variance=inp["sr_variance"],
    )
    assert abs(got - case["expected"]) <= case["tolerance"]["value"]
    sr0 = stats.expected_max_sharpe(inp["n_trials"], sr_variance=inp["sr_variance"])
    assert abs(sr0 - case["intermediates"]["sr0"]) <= 1e-12


@pytest.mark.parametrize(
    "case_id", [i for i in _ids("dsr") if CASES[i].get("paper_check")]
)
def test_dsr_agrees_with_published_digits(case_id):
    case = _case(case_id)
    inp = case["inputs"]
    check = case["paper_check"]
    got = stats.deflated_sharpe(
        inp["sr"],
        inp["n_trials"],
        inp["skew"],
        inp["kurt"],
        inp["n_obs"],
        sr_variance=inp["sr_variance"],
    )
    half_ulp = 0.5 * 10 ** (-check["tolerance"]["digits"])
    assert abs(got - check["published"]) <= half_ulp


def test_dsr_unit_variance_default_unchanged():
    """D6: the legacy call (no ``sr_variance``) is bit-identical to ``V = 1``."""
    for sr, n, skew, kurt, n_obs in [
        (0.08, 100, -0.5, 4.0, 1250),
        (0.3, 7, 0.0, 3.0, 60),
        (1.2, 2, 0.1, 3.5, 400),
        (0.05, 1, 0.0, 3.0, 25),
    ]:
        legacy = stats.deflated_sharpe(sr, n, skew, kurt, n_obs)
        assert legacy == stats.deflated_sharpe(
            sr, n, skew, kurt, n_obs, sr_variance=1.0
        )
        bench = stats._expected_max_sharpe(n)  # pylint: disable=protected-access
        assert legacy == stats.probabilistic_sharpe(sr, bench, skew, kurt, n_obs)
        assert bench == stats.expected_max_sharpe(n)


def test_dsr_variance_input_changes_the_benchmark():
    """F1: per-observation SR with unit variance is deflated to ~0; V fixes it."""
    case = _case("dsr_bl2014_example_n100")["inputs"]
    unit = stats.deflated_sharpe(case["sr"], 100, -3.0, 10.0, 1250)
    assert unit < 1e-6
    assert stats.deflated_sharpe(
        case["sr"], 100, -3.0, 10.0, 1250, sr_variance=0.0
    ) == (stats.probabilistic_sharpe(case["sr"], 0.0, -3.0, 10.0, 1250))


@pytest.mark.parametrize("bad", [-1e-9, float("nan"), float("inf")])
def test_sr_variance_rejects_non_physical_values(bad):
    with pytest.raises(ValueError, match="sr_variance"):
        stats.deflated_sharpe(0.1, 10, 0.0, 3.0, 100, sr_variance=bad)


@pytest.mark.parametrize("case_id", _ids("psr"))
def test_psr_hits_tabulated_normal_quantile(case_id):
    case = _case(case_id)
    inp = case["inputs"]
    got = stats.probabilistic_sharpe(
        inp["sr"], inp["sr_benchmark"], inp["skew"], inp["kurt"], inp["n_obs"]
    )
    assert abs(got - case["expected"]) <= case["tolerance"]["value"]


@pytest.mark.parametrize("case_id", _ids("expected_max"))
def test_expected_max_literal_values(case_id):
    case = _case(case_id)
    inp = case["inputs"]
    got = stats.expected_max_sharpe(inp["n_trials"], sr_variance=inp["sr_variance"])
    assert abs(got - case["expected"]) <= case["tolerance"]["value"]


def test_expected_max_of_two_is_a_documented_approximation():
    case = _case("expected_max_n2_true_value_gap")
    assert case["expected"] == pytest.approx(1.0 / math.sqrt(math.pi), abs=1e-15)
    approx = stats.expected_max_sharpe(2)
    gap = case["expected"] - approx
    assert 0.0 < gap <= case["tolerance"]["value"]


@pytest.mark.parametrize("case_id", _ids("minbtl_exact") + _ids("minbtl_approx"))
def test_minbtl_literal_values(case_id):
    case = _case(case_id)
    inp = case["inputs"]
    fn = (
        stats.min_backtest_length_exact
        if case["kind"] == "minbtl_exact"
        else stats.min_backtest_length
    )
    got = fn(inp["target_sr"], inp["n_trials"])
    assert abs(got - case["expected"]) <= case["tolerance"]["value"]


def test_minbtl_approximation_bounds_exact_form():
    for n in [2, 3, 5, 10, 45, 100, 1_000, 100_000, 10_000_000]:
        for sr in (0.5, 1.0, 2.0):
            exact = stats.min_backtest_length_exact(sr, n)
            assert 0.0 < exact <= stats.min_backtest_length(sr, n)
    assert stats.min_backtest_length_exact(1.0, 1) == 0.0


# ---- PBO --------------------------------------------------------------------


@pytest.mark.parametrize("case_id", _ids("pbo"))
def test_pbo_matches_enumerated_partitions(case_id):
    case = _case(case_id)
    inp = case["inputs"]
    matrix = np.asarray(inp["matrix"], dtype=float)
    expected = float(Fraction(case["expected"]))
    detail = pbo_mod.pbo_detail(
        matrix, n_groups=inp["n_groups"], statistic=inp["statistic"]
    )
    assert detail.pbo == expected
    assert (
        pbo_mod.pbo(matrix, n_groups=inp["n_groups"], statistic=inp["statistic"])
        == expected
    )
    got = [
        (list(p.is_groups), list(p.oos_groups), p.is_best, p.oos_rank)
        for p in detail.partitions
    ]
    want = [
        (r["is_groups"], r["oos_groups"], r["is_best"], r["oos_rank"])
        for r in case["partitions"]
    ]
    assert got == want
    for part, row in zip(detail.partitions, case["partitions"]):
        assert part.logit == pytest.approx(row["logit"], abs=1e-12)


def test_pbo_small_matrix_defaults_to_every_row_partition():
    """``n_groups=None`` enumerates single-row groups for small matrices."""
    case = _case("pbo_tie_sum")
    detail = pbo_mod.pbo_detail(np.asarray(case["inputs"]["matrix"], dtype=float))
    assert detail.n_groups == 4
    assert len(detail.partitions) == math.comb(4, 2)
    assert detail.pbo == 0.5


def test_pbo_large_matrix_caps_groups():
    rng = np.random.default_rng(1357)
    detail = pbo_mod.pbo_detail(rng.standard_normal((41, 3)))
    assert detail.n_groups == 16


def test_pbo_sharpe_and_sum_disagree_on_discriminating_matrix():
    matrix = np.asarray(_case("pbo_sh_sum")["inputs"]["matrix"], dtype=float)
    assert pbo_mod.pbo(matrix, n_groups=4) == 1.0
    assert pbo_mod.pbo(matrix, n_groups=4, statistic="sharpe") == pytest.approx(
        2 / 3, abs=0
    )


@pytest.mark.parametrize(
    ("matrix", "kwargs", "reason"),
    [
        (np.ones((4, 1)), {}, "fewer_than_two_configs"),
        (np.ones((1, 3)), {}, "too_few_slices"),
        (np.ones((4, 3)), {"n_groups": 6}, "too_few_slices"),
        (np.zeros((0, 3)), {}, "too_few_slices"),
        (np.ones((4, 3)), {"statistic": "sharpe"}, "zero_variance"),
        (
            np.arange(6.0).reshape(2, 3),
            {"statistic": "sharpe"},
            "too_few_rows_for_sharpe",
        ),
    ],
)
def test_pbo_detail_undefined_is_none_never_zero(matrix, kwargs, reason):
    detail = pbo_mod.pbo_detail(matrix, **kwargs)
    assert detail.pbo is None
    assert detail.undefined_reason == reason
    assert detail.partitions == ()


def test_pbo_detail_rejects_malformed_input():
    with pytest.raises(ValueError, match="2-D"):
        pbo_mod.pbo_detail(np.ones(4))
    with pytest.raises(ValueError, match="even"):
        pbo_mod.pbo_detail(np.ones((4, 3)), n_groups=3)
    with pytest.raises(ValueError, match="statistic"):
        pbo_mod.pbo_detail(np.ones((4, 3)), statistic="mean")
    with pytest.raises(ValueError, match="finite"):
        pbo_mod.pbo_detail(np.array([[1.0, np.nan], [0.0, 1.0]]))


def test_legacy_pbo_default_statistic_unchanged():
    """D6: ``pbo(m)`` equals the explicit ``statistic='sum'`` call and legacy errors stay."""
    rng = np.random.default_rng(42)
    for _ in range(5):
        m = rng.standard_normal((32, 5))
        assert pbo_mod.pbo(m) == pbo_mod.pbo(m, statistic="sum")
        assert pbo_mod.pbo(m) == pbo_mod.pbo_detail(m, n_groups=16).pbo
    with pytest.raises(ValueError):
        pbo_mod.pbo(np.ones((4, 1)), n_groups=4)
    # Legacy ``pbo`` never rejected non-finite values; it still returns a number.
    legacy_nan = pbo_mod.pbo(np.array([[1.0, np.nan], [0.0, 1.0]]), n_groups=2)
    assert 0.0 <= legacy_nan <= 1.0


# ---- CPCV -------------------------------------------------------------------


def test_cpcv_literal_index_sets_with_purge_and_embargo():
    case = _case("cpcv_t12_n4_k2_purge1_embargo1of12")
    inp = case["inputs"]
    folds = cpcv_mod.cpcv(
        np.arange(inp["n_sessions"]),
        n_groups=inp["n_groups"],
        n_test_groups=inp["n_test_groups"],
        embargo=inp["embargo"],
        label_span=inp["label_span"],
    )
    assert len(folds) == len(case["expected"])
    for fold, want in zip(folds, case["expected"]):
        assert fold.test_idx.tolist() == want["test_idx"]
        assert fold.train_idx.tolist() == want["train_idx"]
        windows = cpcv_mod.atomic_test_windows(fold.test_idx)
        assert [w.tolist() for w in windows] == want["test_windows"]


def test_atomic_windows_never_span_a_train_group():
    """F2: a non-adjacent test split is two windows, not one span over group 1."""
    case = _case("cpcv_t12_n4_k2_purge1_embargo1of12")
    folds = cpcv_mod.cpcv(
        np.arange(12), n_groups=4, n_test_groups=2, embargo=1 / 12, label_span=1
    )
    split = folds[1]  # groups (0, 2)
    assert case["expected"][1]["test_groups"] == [0, 2]
    span = set(range(int(split.test_idx[0]), int(split.test_idx[-1]) + 1))
    assert span & {3, 4, 5}, "legacy start/end span covers train group 1"
    for window in cpcv_mod.atomic_test_windows(split.test_idx):
        assert set(window.tolist()) <= set(split.test_idx.tolist())
        assert window.tolist() == list(range(int(window[0]), int(window[-1]) + 1))
    assert cpcv_mod.atomic_test_windows(np.array([], dtype=int)) == []


def test_cpcv_paths_table():
    case = _case("cpcv_paths_n4_k2")
    got = cpcv_mod.cpcv_paths(**case["inputs"])
    assert [[list(cell) for cell in path] for path in got] == case["expected"]
    assert len(got) == cpcv_mod.n_backtest_paths(**case["inputs"])


@pytest.mark.parametrize(("n", "k"), [(4, 2), (6, 2), (5, 3), (6, 1), (3, 2)])
def test_cpcv_paths_cover_every_group_once_per_path(n, k):
    paths = cpcv_mod.cpcv_paths(n, k)
    splits = list(itertools.combinations(range(n), k))
    assert len(paths) == cpcv_mod.n_backtest_paths(n, k)
    used = set()
    for path in paths:
        assert [g for _, g in path] == list(range(n))
        for split, group in path:
            assert group in splits[split]
            assert (split, group) not in used
            used.add((split, group))
    assert len(used) == math.comb(n, k) * k


def test_n_backtest_paths_literal():
    case = _case("cpcv_n_paths_6_2")
    assert cpcv_mod.n_backtest_paths(**case["inputs"]) == case["expected"]


# ---- qualify-stats CLI (real path) -----------------------------------------


def test_qualify_all_cases_pass_on_committed_references():
    results = qualify.qualify(FIXTURE)
    assert results, "no cases evaluated"
    failed = [r.case_id for r in results if not r.passed]
    assert not failed
    ids = {r.case_id for r in results}
    assert set(CASES) <= ids
    assert "dsr_bl2014_example_n46#paper" in ids


def test_qualify_cli_mutated_fixture_exits_2_naming_case(tmp_path, capsys):
    from openbb_backtest.validation import experiment

    bad = copy.deepcopy(REFS)
    for case in bad["cases"]:
        if case["id"] == "pbo_tie_sum":
            case["expected"] = "1/3"
    path = tmp_path / "refs.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    assert (
        experiment.main(
            ["qualify-stats", "--references", str(path), "--format", "json"]
        )
        == 2
    )
    out = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in out["cases"] if not c["passed"]] == ["pbo_tie_sum"]
    assert out["passed"] is False


def test_qualify_cli_json_success(capsys):
    from openbb_backtest.validation import experiment

    assert experiment.main(["qualify-stats", "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is True
    for case in out["cases"]:
        assert {"id", "expected", "got", "tolerance", "source", "passed"} <= set(case)


def test_qualify_paper_digits_are_checked(tmp_path):
    bad = copy.deepcopy(REFS)
    for case in bad["cases"]:
        if case["id"] == "dsr_bl2014_example_n46":
            case["paper_check"]["published"] = 0.9515
    path = tmp_path / "refs.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    failed = [r.case_id for r in qualify.qualify(path) if not r.passed]
    assert failed == ["dsr_bl2014_example_n46#paper"]
