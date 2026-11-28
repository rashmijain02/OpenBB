"""describe.py tests (#1355 T01)."""

# ruff: noqa: D103

import types

import pytest
from openbb_nautilus_worker import (
    describe,
    protocol as p,
)


class _FakeDist:
    version = "1.231.0"
    files = []

    def read_text(self, name):
        return {"WHEEL": "Wheel-Version: 1.0\nTag: cp312-cp312-win_amd64\n"}.get(name)


def _modules(high, fixed):
    nt = types.SimpleNamespace(__version__="1.231.0", __file__=__file__)
    objs = types.SimpleNamespace(HIGH_PRECISION=high, FIXED_PRECISION=fixed)
    return {"nautilus_trader": nt, describe.PRECISION_MODULE: objs}


def test_collect_facts_reports_tags_and_precision_from_installed_release():
    mods = _modules(False, 9)
    facts = describe.collect_facts(
        {}, import_module=mods.__getitem__, distribution=lambda _n: _FakeDist()
    )
    parsed = p.DescribeFacts.model_validate(facts)
    assert (
        parsed.platform_tag == "win_amd64"
        and parsed.wheel_tag == "cp312-cp312-win_amd64"
    )
    assert (parsed.high_precision, parsed.fixed_precision) == (False, 9)
    assert parsed.python_tag.startswith("cp3") and parsed.nautilus_version == "1.231.0"


def test_collect_facts_missing_nautilus_is_module_origin():
    def boom(_name):
        raise ImportError("no nautilus")

    with pytest.raises(p.ProtocolError) as exc:
        describe.collect_facts({}, import_module=boom)
    assert exc.value.code is p.ErrorCode.MODULE_ORIGIN


def test_collect_facts_missing_precision_constants_is_abi():
    mods = _modules(False, 9)
    del mods[describe.PRECISION_MODULE].FIXED_PRECISION
    with pytest.raises(p.ProtocolError) as exc:
        describe.collect_facts(
            {}, import_module=mods.__getitem__, distribution=lambda _n: _FakeDist()
        )
    assert exc.value.code is p.ErrorCode.ABI


@pytest.mark.requires_nautilus
def test_describe_contract_matches_nautilus_names():
    """Seam contract: the attribute names describe.py reads exist in the installed release."""
    import importlib

    objects = importlib.import_module(describe.PRECISION_MODULE)
    for attr in describe.PRECISION_ATTRS:
        assert hasattr(objects, attr), attr
    facts = describe.collect_facts({})
    assert p.DescribeFacts.model_validate(facts).fixed_precision > 0
