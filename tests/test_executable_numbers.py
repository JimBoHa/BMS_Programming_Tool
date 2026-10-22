"""Executable precision boundaries preserve archival values and atomic scans."""

import copy
import threading

import pytest
from bms_tool import iec, sedona
from bms_tool.conformance import run_suite, template
from bms_tool.deployment import Runtime
from bms_tool.engine import Engine, ScanError, run_scenario, validate
from bms_tool.formats import ConversionError, export_program, import_program
from bms_tool.macros import create_definition
from bms_tool.models import Edge, Node, Program, canonical
from bms_tool.native_simulator import NativeSimulator
from bms_tool.niagara import _scalar
from bms_tool.storage import Store

UNREPRESENTABLE = 2**53 + 1


def passthrough(*, value=0.0, kind="Input"):
    key = "default" if kind == "Input" else "value"
    return Program(
        id="numeric-boundary",
        nodes=[
            Node(id="source", kind=kind, params={key: value}),
            Node(id="out", kind="Output"),
        ],
        edges=[Edge(id="wire", source="source", target="out")],
    )


def addition(a=0, b=1):
    return Program(
        id="numeric-addition",
        nodes=[
            Node(id="a", kind="Input", params={"default": a}),
            Node(id="b", kind="Input", params={"default": b}),
            Node(id="sum", kind="Add"),
            Node(id="out", kind="Output"),
        ],
        edges=[
            Edge(id="a_sum", source="a", target="sum", target_port="a"),
            Edge(id="b_sum", source="b", target="sum", target_port="b"),
            Edge(id="sum_out", source="sum", target="out"),
        ],
    )


def memory():
    p = passthrough()
    p.nodes.insert(1, Node(id="memory", kind="Delay", params={"initial": 0}))
    p.edges = [
        Edge(id="store", source="source", target="memory"),
        Edge(id="publish", source="memory", target="out"),
    ]
    return p


@pytest.mark.parametrize(
    "value",
    [2**53, -(2**53), 2**53 + 2, 2**60, -(2**60), 2**1023],
    ids=[
        "positive-boundary",
        "negative-boundary",
        "next-even",
        "large-power",
        "negative-power",
        "finite-large-power",
    ],
)
def test_exact_binary64_integers_remain_valid_without_normalizing_source(value):
    p = passthrough(value=value, kind="Constant")
    before = canonical(p)
    assert not validate(p)
    row = Engine(p).step()
    assert type(row["outputs"]["out"]) is int and row["outputs"]["out"] == value
    assert canonical(p) == before


@pytest.mark.parametrize(
    "value",
    [UNREPRESENTABLE, -UNREPRESENTABLE, 2**1024, 10**1000],
    ids=["positive-loss", "negative-loss", "float-overflow", "large-overflow"],
)
def test_unrepresentable_integer_parameters_are_archivable_but_not_executable(tmp_path, value):
    p = passthrough(value=value, kind="Constant")
    p.metadata["opaque-evidence"] = {"native-value": value}
    before = canonical(p)
    exported, _, extension = export_program(p, "json")
    assert exported == before
    restored = import_program(exported, "archive." + extension)
    assert canonical(restored) == before
    stored = Store(tmp_path).save(p)
    assert stored.nodes[0].params["value"] == value
    assert Store(tmp_path).load(p.id).digest() == stored.digest()
    assert validate(p)[0].code == "parameter"
    with pytest.raises(ValueError, match="finite numeric|binary64"):
        Engine(p)
    assert canonical(p) == before


def test_numeric_guard_does_not_interpret_opaque_metadata_or_boolean_values():
    p = passthrough(value=2**53)
    p.metadata = {"native": {"opaque": [UNREPRESENTABLE, 10**1000, True]}}
    assert Engine(p).step()["outputs"]["out"] == 2**53
    boolean = passthrough(value=True)
    for node in boolean.nodes:
        node.value_type = "boolean"
    assert Engine(boolean).step()["outputs"]["out"] is True
    with pytest.raises(ValueError, match="finite numeric"):
        Engine(passthrough(value=True))


def test_expanded_macro_parameters_are_checked_without_rewriting_archival_library():
    p = create_definition(passthrough(value=1, kind="Constant"), ["source"], "Numeric source")
    body = p.metadata["macros"]["definitions"][0]["program"]
    next(n for n in body["nodes"] if n["kind"] == "Constant")["params"]["value"] = UNREPRESENTABLE
    before = canonical(p)
    with pytest.raises(ValueError, match="binary64"):
        Engine(p)
    assert canonical(p) == before


@pytest.mark.parametrize("wrapped", [False, True])
def test_live_input_and_force_refusal_preserves_clock_state_history_and_outputs(wrapped):
    engine = Engine(memory())
    engine.step({"source": 3})
    before = copy.deepcopy((engine.snapshot(), engine.history))
    value = {"value": UNREPRESENTABLE, "quality": "good"} if wrapped else UNREPRESENTABLE
    with pytest.raises(ScanError, match="binary64"):
        engine.step({"source": value})
    assert (engine.snapshot(), engine.history) == before
    with pytest.raises(ScanError, match="binary64"):
        engine.step(forces={"source": UNREPRESENTABLE})
    assert (engine.snapshot(), engine.history) == before
    assert engine.step({"source": 4})["outputs"]["out"] == 3


def test_integer_arithmetic_result_is_guarded_before_commit_but_float_rounding_remains():
    engine = Engine(addition(2**53, 1))
    before = copy.deepcopy((engine.snapshot(), engine.history))
    with pytest.raises(ScanError, match="sum.*binary64"):
        engine.step()
    assert (engine.snapshot(), engine.history) == before
    # Ordinary IEEE floating-point arithmetic still rounds; this is not an
    # arbitrary-precision engine or a promise that every operation is exact.
    row = Engine(addition(float(2**53), 1.0)).step()
    assert row["outputs"]["out"] == float(2**53)


def test_runtime_scenario_and_conformance_cannot_bypass_executable_admission(tmp_path):
    p = addition(UNREPRESENTABLE, 0.0)
    with pytest.raises(ValueError, match="binary64"):
        run_scenario(p, [], 1.0)
    runtime = Runtime(Store(tmp_path))
    with pytest.raises(ValueError, match="binary64"):
        runtime.plan(p)
    assert runtime.engine is None and runtime.generation == 0 and runtime.plans == {}
    suite = template(addition())
    with pytest.raises(ValueError, match="binary64"):
        run_suite(p, suite)


@pytest.mark.parametrize("format", ["st", "plcopen", "bog", "temco-bas"])
def test_target_encoders_reject_lost_integer_source_instead_of_rounding_it(format):
    with pytest.raises(ValueError, match="binary64"):
        export_program(passthrough(value=UNREPRESENTABLE, kind="Constant"), format)
    # Native float32/fixed-point profile differences remain explicit. In-range
    # ordinary finite fractions are not all rejected as an imitation of exactness.
    assert export_program(passthrough(value=0.1, kind="Constant"), format)[0]


def test_scalar_conversion_and_native_builders_refuse_before_tools_or_output_files(
    tmp_path, monkeypatch
):
    p = passthrough(value=UNREPRESENTABLE, kind="Constant")

    def forbidden(*args, **kwargs):
        pytest.fail("Native tool or exchange was reached before numeric admission")

    monkeypatch.setattr(sedona, "toolchain", forbidden)
    monkeypatch.setattr(iec, "toolchain", forbidden)
    with pytest.raises(ConversionError, match="binary64"):
        sedona.compile_program(p, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()
    with pytest.raises(ValueError, match="binary64"):
        iec.NativeIEC(p)
    with pytest.raises(ConversionError, match="binary64"):
        _scalar(UNREPRESENTABLE)
    assert _scalar(2**60) == 2**60


def test_native_sedona_live_input_guard_precedes_external_exchange_and_keeps_reference(
    tmp_path, monkeypatch
):
    simulator = NativeSimulator(Store(tmp_path))
    simulator.reference = Engine(memory())
    simulator.reference.step({"source": 3})
    before = copy.deepcopy(
        (simulator.reference.snapshot(), simulator.history, simulator.generation)
    )

    def forbidden(*args, **kwargs):
        pytest.fail("SOX exchange was reached for an unrepresentable integer input")

    monkeypatch.setattr(simulator, "_request", forbidden)
    with pytest.raises(ValueError, match="binary64"):
        simulator.step({"source": UNREPRESENTABLE})
    assert (simulator.reference.snapshot(), simulator.history, simulator.generation) == before


def test_native_iec_live_input_guard_precedes_exchange_without_changing_reference(monkeypatch):
    native = object.__new__(iec.NativeIEC)
    native.program = memory()
    native.reference = Engine(native.program)
    native.reference.step({"source": 3})
    native.inputs = {"source": native.program.nodes[0]}
    native._io_lock = threading.RLock()
    before = native.reference.snapshot()

    def forbidden(*args, **kwargs):
        pytest.fail("IEC exchange was reached for an unrepresentable integer input")

    monkeypatch.setattr(native, "_exchange", forbidden)
    with pytest.raises(ValueError, match="binary64"):
        native.step({"source": UNREPRESENTABLE})
    assert native.reference.snapshot() == before
