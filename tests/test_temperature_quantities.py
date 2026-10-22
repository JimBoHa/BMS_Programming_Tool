"""Absolute temperature versus differences, with independent arithmetic oracles."""

import copy
import hashlib

import pytest
from bms_tool.blocks import BLOCKS, catalog
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.formats import export_program, export_st, import_program
from bms_tool.models import Edge, Node, Program, canonical
from bms_tool.niagara import SOURCE, NiagaraArchive, export_bog, import_bog
from bms_tool.source_profiles import LEGACY
from bms_tool.storage import LEGACY_HASH_FORMAT, Store
from bms_tool.temco import import_source


def operation(kind, units, *, unit, params, defaults=None):
    nodes = [
        Node(id=port, kind="Input", unit=value, params={"default": (defaults or {}).get(port, 0)})
        for port, value in units.items()
    ]
    nodes += [
        Node(id="op", kind=kind, unit=unit, params=params),
        Node(id="out", kind="Output", unit=unit),
    ]
    edges = [Edge(id=port, source=port, target="op", target_port=port) for port in units]
    edges.append(Edge(id="publish", source="op", target="out"))
    return Program(id="temperature-quantity", nodes=nodes, edges=edges)


def temperature_chain():
    return Program(
        id="temperature-chain",
        nodes=[
            Node(id="a", kind="Input", unit="degF", params={"default": 86}),
            Node(id="b", kind="Input", unit="degF", params={"default": 68}),
            Node(id="base", kind="Input", unit="degC", params={"default": 20}),
            Node(
                id="difference",
                kind="TemperatureDifference",
                unit="delta-degF",
                params={"unit": "degF"},
            ),
            Node(
                id="delta",
                kind="DeltaConvert",
                unit="delta-degC",
                params={"from": "delta-degF", "to": "delta-degC"},
            ),
            Node(
                id="offset",
                kind="TemperatureOffset",
                unit="degC",
                params={"unit": "degC", "difference_unit": "delta-degC"},
            ),
            Node(id="absolute", kind="Output", unit="degC"),
            Node(id="change", kind="Output", unit="delta-degC"),
        ],
        edges=[
            Edge(id="a", source="a", target="difference", target_port="a"),
            Edge(id="b", source="b", target="difference", target_port="b"),
            Edge(id="delta", source="difference", target="delta"),
            Edge(id="base", source="base", target="offset", target_port="base"),
            Edge(id="change", source="delta", target="offset", target_port="difference"),
            Edge(id="publish_absolute", source="offset", target="absolute"),
            Edge(id="publish_change", source="delta", target="change"),
        ],
    )


@pytest.mark.parametrize("source", ["delta-degF", "delta-degC", "delta-K"])
@pytest.mark.parametrize("target", ["delta-degF", "delta-degC", "delta-K"])
@pytest.mark.parametrize("value", [-18, 0, 18])
def test_difference_conversion_uses_scale_only(source, target, value):
    p = operation(
        "DeltaConvert", {"in": source}, unit=target, params={"from": source, "to": target}
    )
    # Independent expected conversion: one Fahrenheit degree spans 5/9 kelvin.
    kelvin = value / 1.8 if source == "delta-degF" else value
    expected = kelvin * 1.8 if target == "delta-degF" else kelvin
    assert Engine(p).step({"in": value})["outputs"]["out"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "unit,a,b,expected", [("degF", 32, 212, -180), ("degC", 0, -5, 5), ("K", 273.15, 273.15, 0)]
)
def test_subtraction_produces_a_difference_without_temperature_origin(unit, a, b, expected):
    delta = {"degF": "delta-degF", "degC": "delta-degC", "K": "delta-K"}[unit]
    p = operation(
        "TemperatureDifference", {"a": unit, "b": unit}, unit=delta, params={"unit": unit}
    )
    assert Engine(p).step({"a": a, "b": b})["outputs"] == {"out": expected}


@pytest.mark.parametrize(
    "absolute,delta,base,value,expected",
    [
        ("degF", "delta-degC", 32, 10, 50),
        ("degC", "delta-degF", 20, -18, 10),
        ("K", "delta-degF", 273.15, 18, 283.15),
        ("degF", "delta-K", -40, 0, -40),
        ("degC", "delta-K", -10, 5, -5),
    ],
)
def test_offset_scales_the_difference_and_preserves_the_absolute_base(
    absolute, delta, base, value, expected
):
    p = operation(
        "TemperatureOffset",
        {"base": absolute, "difference": delta},
        unit=absolute,
        params={"unit": absolute, "difference_unit": delta},
    )
    assert Engine(p).step({"base": base, "difference": value})["outputs"]["out"] == pytest.approx(
        expected
    )


def test_new_quantity_contracts_reject_absolute_difference_and_unmatched_units():
    cases = []
    p = temperature_chain()
    changes = [
        ("difference", "unit", "degF"),
        ("delta", "unit", "degC"),
        ("a", "unit", "delta-degF"),
        ("b", "unit", "degC"),
        ("base", "unit", "delta-degC"),
        ("offset", "unit", "delta-degC"),
    ]
    for identifier, field, value in changes:
        bad = p.model_copy(deep=True)
        setattr(next(n for n in bad.nodes if n.id == identifier), field, value)
        cases.append(bad)
    for identifier, params in [
        ("difference", {"unit": "delta-degF"}),
        ("delta", {"from": "degF", "to": "delta-degC"}),
        ("delta", {"from": "delta-degF", "to": "degC"}),
        ("offset", {"unit": "degC", "difference_unit": "degC"}),
        ("offset", {"unit": [], "difference_unit": "delta-degC"}),
    ]:
        bad = p.model_copy(deep=True)
        next(n for n in bad.nodes if n.id == identifier).params = params
        cases.append(bad)
    for bad in cases:
        assert any(d.level == "error" for d in validate(bad))
        with pytest.raises(ValueError):
            Engine(bad)
        with pytest.raises(ValueError):
            export_st(bad)
    convert = operation(
        "Convert",
        {"in": "delta-degF"},
        unit="delta-degC",
        params={"from": "delta-degF", "to": "delta-degC"},
    )
    assert any(d.level == "error" for d in validate(convert))


def test_quality_and_overflow_faults_leave_all_outputs_clock_state_and_history_unchanged():
    p = temperature_chain()
    engine = Engine(p)
    assert engine.step()["outputs"] == {"absolute": 30, "change": 10}
    before = copy.deepcopy(
        (engine.state, engine.outputs, engine.time, engine.clock, engine.history)
    )
    for values in [{"a": {"value": None, "quality": "open-circuit"}}, {"a": 1e308, "b": -1e308}]:
        with pytest.raises(ScanError):
            engine.step(values)
        assert (engine.state, engine.outputs, engine.time, engine.clock, engine.history) == before
    assert engine.step({"a": 32, "b": 50, "base": -10})["outputs"] == {
        "absolute": -20,
        "change": -10,
    }


@pytest.mark.parametrize("format", ["json", "st", "plcopen", "graphml", "temco-bas", "bog"])
def test_all_source_exports_keep_explicit_quantities_and_parameters(format):
    p = temperature_chain()
    data, _, extension = export_program(p, format)
    assert import_program(data, "temperature." + extension) == p
    if format == "temco-bas":
        assert "REM BMSIR2 " in data.decode()
        # Changing executable arithmetic cannot retain trusted quantity metadata.
        edited = data.decode().replace(" / 9 * 5", " / 9 * 6")
        with pytest.raises(ValueError, match="disagrees"):
            import_source(edited)


def test_niagara_foreign_temperature_difference_and_delta_converter_remain_distinct():
    p = temperature_chain()
    foreign = import_bog(SOURCE.sub(b"", NiagaraArchive(export_bog(p)).xml))
    assert {"TemperatureDifference", "DeltaConvert", "TemperatureOffset"} <= {
        n.kind for n in foreign.nodes
    }
    assert sorted(Engine(foreign).step()["outputs"].values()) == [10, 30]


def test_legacy_temperature_serialization_export_and_stored_hashes_stay_exact(tmp_path):
    p = Program(
        id="legacy-temperature",
        nodes=[
            Node(id="sensor", kind="Input", unit="degF", params={"default": 32}),
            Node(id="convert", kind="Convert", unit="degC", params={"from": "degF", "to": "degC"}),
            Node(id="result", kind="Output", unit="degC"),
        ],
        edges=[
            Edge(id="a", source="sensor", target="convert"),
            Edge(id="b", source="convert", target="result"),
        ],
    )
    # Recorded from unchanged main before introducing quantity blocks.
    assert p.digest() == "959db788104d731f24167958bd4c4cacb1a8473455d8c0bed90654ec85d33911"
    legacy_source = export_st(p, profile=LEGACY)
    assert (
        hashlib.sha256(legacy_source).hexdigest()
        == "6a95c97276096b0bc4499a50723817dbc043c0285b45b4585736fb4a1bd49e7c"
    )
    # New generation is explicitly versioned; both formats retain the graph.
    current_source = export_st(p)
    assert b"BMS_STUDIO_IR_V1 " in legacy_source
    assert b"BMS_STUDIO_IR_V2 " in current_source
    assert current_source != legacy_source
    for source in (legacy_source, current_source):
        assert canonical(import_program(source, "temperature.st")) == canonical(p)
    original = p.model_dump_json()
    assert (
        hashlib.sha256(original.encode()).hexdigest()
        == "4f827e5b625dc175db717b5b7f974b895375f3907f2682daeadc96a90d522bd4"
    )
    store = Store(tmp_path)
    with store.connect() as db:
        db.execute(
            "INSERT INTO revisions VALUES(?,?,?,?,?,?,?)",
            (
                p.id,
                0,
                p.name,
                original,
                hashlib.sha256(original.encode()).hexdigest(),
                "2026-01-01",
                LEGACY_HASH_FORMAT,
            ),
        )
    assert canonical(store.load(p.id)) == canonical(p)
    assert store.save(p).schema_version == 1
    assert Engine(store.load(p.id)).step()["outputs"] == {"result": 0}


def test_catalog_documents_quantity_ports_and_default_output_units():
    entries = {b["kind"]: b for b in catalog()}
    assert entries["TemperatureDifference"]["unit"] == "delta-degF"
    assert entries["DeltaConvert"]["unit"] == "delta-degC"
    assert entries["TemperatureOffset"]["unit"] == "degF"
    assert "scale only" in BLOCKS["DeltaConvert"].help


def test_native_converter_rejects_mixed_quantity_categories_and_nonzero_delta_origin():
    from bms_tool.niagara import UNITS

    from .test_niagara_extended import foreign_converter

    with pytest.raises(ValueError, match="cannot mix absolute and difference"):
        import_bog(foreign_converter("units=u:" + UNITS["degF"], "units=u:" + UNITS["delta-degC"]))
    with pytest.raises(ValueError, match="scale/offset"):
        import_bog(
            foreign_converter(
                "units=u:fahrenheit degrees;Δ°F;(K);*0.5555555555555556+32;",
                "units=u:" + UNITS["delta-degC"],
            )
        )


def test_foreign_raw_add_does_not_invent_cross_unit_difference_scaling():
    p = operation(
        "TemperatureOffset",
        {"base": "degC", "difference": "delta-degC"},
        unit="degC",
        params={"unit": "degC", "difference_unit": "delta-degC"},
    )
    document = SOURCE.sub(b"", NiagaraArchive(export_bog(p)).xml)
    # Independently edited foreign input facet; native Add still adds raw numbers.
    document = document.replace(
        "celsius degrees;Δ°C;(K);;".encode(),
        "fahrenheit degrees;Δ°F;(K);*0.5555555555555556;".encode(),
    )
    with pytest.raises(ValueError, match="explicit type/unit/cycle repair"):
        import_bog(document)
