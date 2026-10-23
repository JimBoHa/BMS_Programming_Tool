"""Small independent sum/port/hierarchy contracts, using existing macro APIs."""

import copy
import math

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.macros import import_macro_library, instantiate_macro, macro_catalog
from bms_tool.models import Edge, Node, Program
from bms_tool.sum8_macro_template import (
    PROFILE,
    PROFILE_SHA,
    UNITS,
    TemplateRequest,
    digest,
    preview,
)
from pydantic import ValidationError


def caller(unit="", *, report=None):
    report = report or preview(TemplateRequest(unit=unit))
    root = Program(
        id="sum8-caller",
        nodes=[
            Node(id=f"v{i}", kind="Input", unit=unit, params={"default": float(i)})
            for i in range(1, 9)
        ],
    )
    root = import_macro_library(root, report["bundle"])
    root = instantiate_macro(root, report["definition_id"])
    instance = root.nodes[-1].id
    root.nodes.append(Node(id="total", kind="Output", unit=unit))
    root.edges.extend(
        Edge(id=f"wire_{i}", source=f"v{i}", target=instance, target_port=f"i{i}")
        for i in range(1, 9)
    )
    root.edges.append(Edge(id="publish", source=instance, target="total"))
    return root


def fold(values):
    # No sum(...,0) identity: that would erase all-negative-zero semantics.
    value = values[0]
    for item in values[1:]:
        value = value + item
    return value


@pytest.mark.parametrize("unit", list(UNITS))
def test_exact16_node_left_fold_and_profile_definition_bundle_source(unit):
    report = preview(TemplateRequest(unit=unit))
    assert report["profile_sha256"] == PROFILE_SHA == digest(PROFILE)
    assert report["choices_sha256"] == digest({"unit": unit})
    program = Program.model_validate(report["program"])
    assert len(program.nodes) == 16 and len(program.edges) == 15
    assert [n.kind for n in program.nodes].count("Add") == 7
    assert program.digest() == report["program_sha256"]
    assert report["bundle"]["library"]["definitions"][0]["program"] == report["program"]
    assert report["definition_sha256"] == digest(report["bundle"]["library"]["definitions"][0])
    assert report["bundle_sha256"] == digest(report["bundle"])
    assert all(n.unit == unit for n in program.nodes)
    assert all(row["required"] for row in report["inputs"]) and len(report["inputs"]) == 8
    assert report["can_import"] and not report["native_compile"] and not report["controller_writes"]
    assert not [x for x in validate(program) if x.level == "error"]
    root = caller(unit, report=report)
    assert Engine(root).step()["outputs"] == {"total": 36}
    assert macro_catalog(root)[0]["input_contracts"][0]["required"]


@pytest.mark.parametrize(
    "values",
    [
        [1, -2, 3, -4, 5, -6, 7, -8],
        [1e-6, 2e-6, -1e-6, 0, 0, 0, 0, 0],
        [1e20, 1, -1e20, 3, 0, 0, 0, 0],
        [-0.0] * 8,
        [17, 0, 0, 0, 0, 0, 0, 0],
    ],
)
def test_independent_ordered_vectors_and_explicit_zero_contributions(values):
    actual = Engine(caller()).step({f"v{i}": value for i, value in enumerate(values, 1)})[
        "outputs"
    ]["total"]
    expected = fold(values)
    assert actual == expected
    if expected == 0:
        assert math.copysign(1, actual) == math.copysign(1, expected)


@pytest.mark.parametrize("index", range(1, 9))
def test_each_bad_input_retains_previous_complete_scan(index):
    engine = Engine(caller())
    engine.step()
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError, match="stale input quality"):
        engine.step({f"v{index}": {"value": 0, "quality": "stale"}})
    assert engine.snapshot() == previous


def test_overflow_retains_previous_complete_scan():
    engine = Engine(caller())
    engine.step()
    previous = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError):
        engine.step({f"v{i}": 1e308 for i in range(1, 9)})
    assert engine.snapshot() == previous


def test_required_writers_units_types_and_conflicting_definitions_are_not_hidden():
    root = caller()
    missing = root.model_copy(deep=True)
    missing.edges.pop(0)
    with pytest.raises(ValueError, match="required inputs i1"):
        Engine(missing)
    wrong_unit = caller("cfm")
    wrong_unit.nodes[0].unit = "L/s"
    with pytest.raises(ValueError, match="Unit mismatch"):
        Engine(wrong_unit)
    wrong_type = root.model_copy(deep=True)
    wrong_type.nodes[0].value_type = "boolean"
    wrong_type.nodes[0].params["default"] = False
    with pytest.raises(ValueError, match="requires number, received boolean"):
        Engine(wrong_type)
    report = preview(TemplateRequest(unit=""))
    bad = copy.deepcopy(report["bundle"])
    bad["library"]["definitions"][0]["program"]["nodes"][0]["label"] = "Conflicting definition"
    old = root.digest()
    with pytest.raises(ValueError, match="identifier conflict"):
        import_macro_library(root, bad)
    assert root.digest() == old


@pytest.mark.parametrize(
    "body", [{}, {"unit": "degF"}, {"unit": True}, {"unit": "", "capacity": 4}]
)
def test_exact_small_unit_schema_does_not_infer_other_calculations(body):
    with pytest.raises(ValidationError):
        TemplateRequest.model_validate(body)
