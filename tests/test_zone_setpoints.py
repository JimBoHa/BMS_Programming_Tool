"""Independent finite-state target composition and source/quantity contracts."""

import copy
import itertools

import pytest
from bms_tool.engine import Engine, ScanError, validate
from bms_tool.zone_setpoints import (
    Choices,
    Population,
    Window,
    catalog_document,
    convert_units,
    generate,
)
from pydantic import ValidationError

COMPOSITIONS = list(itertools.product((False, True), (False, True), ("degF", "degC"), (1, 2)))


def choices(*, population=True, window=True, unit="degF", scan=1, **changes):
    data = {
        "project_id": "zone-targets",
        "name": "Explicit zone effective targets",
        "population": "timed-offset" if population else "off",
        "population_control": Population(
            entry_seconds=3 * scan, release_seconds=2 * scan
        ).model_dump()
        if population
        else None,
        "window": "absolute-pair" if window else "off",
        "window_control": Window().model_dump() if window else None,
        "scan_seconds": scan,
    }
    data.update(changes)
    return convert_units(Choices.model_validate(data), unit)


class Oracle:
    """Independent elapsed-duration state; no graph/node/internal-state access."""

    def __init__(self, value):
        self.value = value
        self.enter = self.leave = 0
        self.active = False

    def step(self, inputs):
        value = self.value
        occupied = inputs.get("scheduled_occupied", value.scheduled_occupied_default)
        p, w = value.population_control, value.window_control
        window = inputs.get("window_open", w.open_default) if w else False
        if p:
            populated = inputs.get("populated", p.populated_default)
            self.enter = self.enter + value.scan_seconds if occupied and not populated else 0
            self.leave = (
                self.leave + value.scan_seconds if occupied and populated and self.active else 0
            )
            self.active = occupied and (
                self.enter >= p.entry_seconds or self.active and self.leave < p.release_seconds
            )
        heat, cool = (
            (value.occupied_heating_setpoint, value.occupied_cooling_setpoint)
            if occupied
            else (value.unoccupied_heating_setpoint, value.unoccupied_cooling_setpoint)
        )
        applied = self.active and not window
        delta = p.offset if applied else 0
        if applied:
            heat, cool = heat - delta, cool + delta
        if window:
            heat, cool = w.heating_setpoint, w.cooling_setpoint
        return {
            "effective_heating_setpoint": heat,
            "effective_cooling_setpoint": cool,
            "occupied_base_selected": occupied and not window,
            "population_setback_ready": self.active,
            "population_offset_applied": applied,
            "window_override_active": window,
            "applied_population_offset": delta,
            "setpoint_profile": 3 if window else 2 if self.active else 1 if occupied else 0,
        }


def frames(population, window):
    # Entry chatter, full entry, release chatter, override across both transitions,
    # unoccupied reset, first-read defaults and re-entry all have independent rows.
    rows = (
        [(False, False, False)]
        + [(True, False, False)] * 3
        + [(True, True, True), (True, False, True), (True, True, True), (True, True, False)]
        + [
            (False, False, True),
            (True, False, True),
            (True, False, True),
            (True, False, False),
            (False, True, False),
        ]
    )
    for occupied, populated, opened in rows:
        yield {
            "scheduled_occupied": occupied,
            **({"populated": populated} if population else {}),
            **({"window_open": opened} if window else {}),
        }


@pytest.mark.parametrize("population,window,unit,scan", COMPOSITIONS)
def test_all_flat_graph_compositions_match_independent_elapsed_state_oracle(
    population, window, unit, scan
):
    value = choices(population=population, window=window, unit=unit, scan=scan)
    program = generate(value)
    assert not [d for d in validate(program) if d.level == "error"]
    assert len(program.nodes) == len({n.id for n in program.nodes}) <= 80
    assert not any(n.kind == "Macro" for n in program.nodes)
    assert {n.id for n in program.nodes if n.kind == "Input"} == {"scheduled_occupied"} | (
        {"populated"} if population else set()
    ) | ({"window_open"} if window else set())
    engine, oracle = Engine(program), Oracle(value)
    for supplied in frames(population, window):
        output = engine.step(supplied)["outputs"]
        assert output == pytest.approx(oracle.step(supplied))
        assert output["effective_heating_setpoint"] < output["effective_cooling_setpoint"]
    meta = program.metadata["zone_setpoint_wizard"]
    assert meta["inputs"] == [
        {
            "id": n.id,
            "label": n.label,
            "value_type": n.value_type,
            "unit": n.unit,
            "default": n.params["default"],
        }
        for n in program.nodes
        if n.kind == "Input"
    ]
    assert len(meta["outputs"]) == 8 and not program.metadata["native_deployment_verified"]


def test_reference_three_hundred_and_sixty_second_population_contract_not_one_scan_short():
    value = choices(population_control=Population().model_dump())
    engine = Engine(generate(value))
    rows = [
        engine.step({"scheduled_occupied": True, "populated": False})["outputs"] for _ in range(300)
    ]
    assert not any(r["population_setback_ready"] for r in rows[:-1])
    assert (
        rows[-1]["effective_heating_setpoint"] == 69
        and rows[-1]["effective_cooling_setpoint"] == 75
    )
    released = [
        engine.step({"scheduled_occupied": True, "populated": True})["outputs"] for _ in range(60)
    ]
    assert all(r["population_setback_ready"] for r in released[:-1])
    assert (
        not released[-1]["population_setback_ready"]
        and released[-1]["effective_heating_setpoint"] == 70
    )


def test_window_hides_offset_without_stopping_entry_or_release_timers_and_unoccupied_resets():
    engine = Engine(generate(choices()))
    for _ in range(3):
        out = engine.step({"scheduled_occupied": True, "populated": False, "window_open": True})[
            "outputs"
        ]
    assert out["population_setback_ready"] and not out["population_offset_applied"]
    assert out["applied_population_offset"] == 0 and out["setpoint_profile"] == 3
    closed = engine.step({"scheduled_occupied": True, "populated": False})["outputs"]
    assert closed["effective_heating_setpoint"] == 69 and closed["population_offset_applied"]
    for _ in range(2):
        out = engine.step({"scheduled_occupied": True, "populated": True, "window_open": True})[
            "outputs"
        ]
    assert not out["population_setback_ready"] and out["window_override_active"]
    assert engine.step({"scheduled_occupied": True})["outputs"]["effective_heating_setpoint"] == 70
    for _ in range(3):
        engine.step({"scheduled_occupied": True, "populated": False})
    out = engine.step({"scheduled_occupied": False, "window_open": True})["outputs"]
    assert not out["population_setback_ready"] and out["setpoint_profile"] == 3
    restart = engine.step({"scheduled_occupied": True, "populated": False})["outputs"]
    assert not restart["population_setback_ready"]


@pytest.mark.parametrize("sensor", ["scheduled_occupied", "populated", "window_open"])
def test_required_bad_quality_rolls_back_targets_latent_state_and_timers_even_window_override(
    sensor,
):
    engine = Engine(generate(choices()))
    engine.step({"scheduled_occupied": True, "populated": False})
    before, history = copy.deepcopy(engine.snapshot()), len(engine.history)
    with pytest.raises(ScanError):
        engine.step(
            {"scheduled_occupied": False, "window_open": True, sensor: {"quality": "unreliable"}}
        )
    assert engine.snapshot() == before and len(engine.history) == history


def test_bad_quality_before_first_good_scan_does_not_seed_targets_or_advance_state():
    value = choices(window_control=Window(open_default=True).model_dump())
    engine = Engine(generate(value))
    before = copy.deepcopy(engine.snapshot())
    with pytest.raises(ScanError):
        engine.step({"populated": {"quality": "unreliable"}})
    assert engine.snapshot() == before and engine.outputs == {} and not engine.history
    out = engine.step()["outputs"]
    assert (
        out["window_override_active"]
        and out["effective_heating_setpoint"] == 40
        and out["effective_cooling_setpoint"] == 120
    )


@pytest.mark.parametrize("population,window", list(itertools.product((False, True), repeat=2)))
def test_coupled_unit_conversion_of_declared_pairs_and_delta_matches_off_boundary_trace(
    population, window
):
    f = choices(population=population, window=window)
    c = convert_units(f, "degC")
    for field in (
        "occupied_heating_setpoint",
        "occupied_cooling_setpoint",
        "unoccupied_heating_setpoint",
        "unoccupied_cooling_setpoint",
    ):
        assert getattr(c, field) == pytest.approx((getattr(f, field) - 32) * 5 / 9)
    if population:
        assert c.population_control.offset == pytest.approx(f.population_control.offset * 5 / 9)
        assert c.population_control.entry_seconds == f.population_control.entry_seconds
    engines = [Engine(generate(f)), Engine(generate(c))]
    for supplied in frames(population, window):
        a, b = [e.step(supplied)["outputs"] for e in engines]
        for key in a:
            expected = (
                (a[key] - 32) * 5 / 9
                if key in ("effective_heating_setpoint", "effective_cooling_setpoint")
                else a[key] * 5 / 9
                if key == "applied_population_offset"
                else a[key]
            )
            assert b[key] == pytest.approx(expected)


@pytest.mark.parametrize(
    "change",
    [
        {"population_control": None},
        {"population": "off"},
        {"window_control": None},
        {"window": "off"},
        {"occupied_heating_setpoint": 74},
        {"unoccupied_heating_setpoint": 82},
        {"occupied_cooling_setpoint": 211.5, "population_control": {"offset": 1}},
        {"occupied_heating_setpoint": -57.5, "population_control": {"offset": 1}},
        {"window_control": {"heating_setpoint": 120, "cooling_setpoint": 120}},
        {"window_control": {"cooling_setpoint": 213}},
        {"population_control": {"offset": 0}},
        {"population_control": {"entry_seconds": True}},
        {"scan_seconds": 1.0},
        {"scan_seconds": 7},
        {"scheduled_occupied_default": 1},
        {"demand_limit": 1},
        {"unit_enable": True},
    ],
)
def test_all_reachable_range_order_branch_and_strict_contracts_refused(change):
    data = choices().model_dump() | change
    with pytest.raises(ValidationError):
        Choices.model_validate(data)


@pytest.mark.parametrize("offset", [0.1, 1, 1.5])
def test_accepted_reachable_boundary_values_convert_both_directions(offset):
    value = choices(
        occupied_heating_setpoint=-58 + offset,
        occupied_cooling_setpoint=212 - offset,
        population_control=Population(
            offset=offset, entry_seconds=3, release_seconds=2
        ).model_dump(),
    )
    metric = convert_units(value, "degC")
    restored = convert_units(metric, "degF")
    assert restored.occupied_heating_setpoint == pytest.approx(value.occupied_heating_setpoint)
    assert restored.occupied_cooling_setpoint == pytest.approx(value.occupied_cooling_setpoint)


def test_smallest_positive_population_difference_roundtrip_has_explicit_finite_precision_limit():
    data = choices().model_dump()
    data["population_control"]["offset"] = 5e-324
    value = Choices.model_validate(data)
    metric = convert_units(value, "degC")
    restored = convert_units(metric, "degF")
    assert metric.population_control.offset == 5e-324
    assert restored.population_control.offset == 1e-323
    assert restored.population_control.offset != value.population_control.offset


@pytest.mark.parametrize("unit,offset", [("degF", 1e-323), ("degC", 5e-324)])
def test_smallest_cross_unit_positive_population_differences_convert_without_becoming_zero(
    unit, offset
):
    data = choices(unit=unit).model_dump()
    data["population_control"]["offset"] = offset
    value = Choices.model_validate(data)
    converted = convert_units(value, "degC" if unit == "degF" else "degF")
    assert converted.population_control.offset > 0
    assert convert_units(converted, unit).population_control.offset > 0


def test_catalog_reference_branches_require_explicit_choices_and_default_to_unoccupied():
    catalog = catalog_document()
    assert catalog["defaults"]["population"] == catalog["defaults"]["window"] == ""
    off = choices(population=False, window=False)
    out = Engine(generate(off)).step()["outputs"]
    assert (
        out["effective_heating_setpoint"] == 61
        and out["effective_cooling_setpoint"] == 82
        and out["setpoint_profile"] == 0
    )
    c = convert_units(
        Choices.model_validate(
            catalog["defaults"]
            | {
                "population": "timed-offset",
                "population_control": catalog["branch_defaults"]["degF"]["population"][
                    "timed-offset"
                ],
                "window": "absolute-pair",
                "window_control": catalog["branch_defaults"]["degF"]["window"]["absolute-pair"],
            }
        ),
        "degC",
    )
    assert (
        catalog["branch_defaults"]["degC"]["population"]["timed-offset"]
        == c.model_dump()["population_control"]
    )
    assert (
        catalog["branch_defaults"]["degC"]["window"]["absolute-pair"]
        == c.model_dump()["window_control"]
    )


@pytest.mark.parametrize(
    "format,extension", [("json", "json"), ("st", "st"), ("plcopen", "xml"), ("graphml", "graphml")]
)
def test_genuine_graph_roundtrips_supported_sources(format, extension):
    from bms_tool.formats import export_program, import_program

    program = generate(choices())
    raw, _, _ = export_program(program, format)
    assert import_program(raw, "targets." + extension) == program
