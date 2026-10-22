"""Hand-calculated acceptance criteria; expectations never come from the engine."""

import copy
import hashlib
import json

import pytest
from bms_tool import conformance as c
from bms_tool.models import Edge, Node, Program
from bms_tool.storage import Conflict, Store


def program(kind="Delay", *, default=2.0, unit="degF", boolean=False):
    typ = "boolean" if boolean else "number"
    params = {"initial": -1.0} if kind == "Delay" else {"seconds": 2.0}
    return Program(
        id="conformance-example",
        revision=3,
        nodes=[
            Node(
                id="sensor",
                kind="Input",
                label="Sensor",
                value_type=typ,
                unit=unit,
                params={"default": default},
            ),
            Node(id="state", kind=kind, value_type=typ, unit=unit, params=params),
            Node(id="result", kind="Output", value_type=typ, unit=unit),
            Node(id="unused", kind="Input", value_type="number", unit="%", params={"default": 7.0}),
        ],
        edges=[
            Edge(id="a", source="sensor", target="state"),
            Edge(id="b", source="state", target="result"),
        ],
    )


def check(identity, time, expected, signal="result", unit="degF", **kwargs):
    return {
        "id": identity,
        "time": time,
        "signal": signal,
        "unit": unit,
        "expected": expected,
        "abs_tol": 0.0,
        "rel_tol": 0.0,
        **kwargs,
    }


def suite(p=None):
    p = p or program()
    value = c.template(p)
    value["name"] = "Delay startup and held sample"
    value["cases"][0].update(
        duration=3.0,
        dt=1.0,
        events=[
            {"time": 0.0, "inputs": {"sensor": {"value": 5.0, "quality": "good"}}},
            {"time": 1.0, "inputs": {"sensor": {"value": -3.0, "quality": "good"}}},
        ],
        checks=[check("startup", 1.0, -1.0), check("previous", 2.0, 5.0), check("held", 3.0, -3.0)],
    )
    return value


def verify_report(report):
    document = copy.deepcopy(report)
    seal = document.pop("content_sha256")
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == seal


def test_delay_exact_times_fresh_cases_coverage_and_seal():
    p = program()
    value = suite(p)
    fresh = copy.deepcopy(value["cases"][0])
    fresh.update(
        id="fresh",
        name="Fresh defaults",
        duration=1.0,
        events=[],
        checks=[check("initial", 1.0, -1.0)],
    )
    value["cases"].append(fresh)
    first, second = (report := c.run_suite(p, value))["cases"]
    assert report["status"] == "passed"
    assert [row["actual"] for row in first["comparisons"]] == [-1.0, 5.0, -3.0]
    assert second["comparisons"][0]["actual"] == -1.0  # New retained state for each case.
    assert first["successful_scans"] == first["attempted_scans"] == 3
    assert first["coverage"]["asserted_outputs"] == ["result"]
    assert first["coverage"]["inputs_using_only_defaults"] == ["unused"]
    assert second["coverage"]["inputs_using_only_defaults"] == ["sensor", "unused"]
    assert first["coverage"]["initial_input_defaults"]["sensor"] == {
        "value": 2.0,
        "quality": "good",
        "unit": "degF",
    }
    assert report["program_sha256"] == p.digest()
    assert report["program_revision"] == 3
    assert (
        not report["native_execution"]
        and not report["controller_writes"]
        and not report["certification"]
    )
    verify_report(report)


def test_timer_boolean_timing_and_utc_clock():
    p = program("TimerOn", default=False, unit="", boolean=True)
    value = c.template(p)
    value["cases"][0].update(
        duration=4.0,
        dt=1.0,
        start_clock="2026-01-05T02:00:00+02:00",
        events=[
            {"time": 0.0, "inputs": {"sensor": {"value": True}}},
            {"time": 2.0, "inputs": {"sensor": {"value": False}}},
            {"time": 3.0, "inputs": {"sensor": {"value": True}}},
        ],
        checks=[
            check("first", 1.0, False, unit=""),
            check("second", 2.0, True, unit=""),
            check("reset", 3.0, False, unit=""),
            check("restart", 4.0, False, unit=""),
        ],
    )
    report = c.run_suite(p, value)
    assert report["status"] == "passed"
    assert [row["actual"] for row in report["cases"][0]["comparisons"]] == [
        False,
        True,
        False,
        False,
    ]
    assert report["cases"][0]["comparisons"][-1]["clock"] == "2026-01-05T00:00:04+00:00"


def test_decimal_grid_final_partial_step_and_tolerances():
    p = program()
    value = suite(p)
    value["cases"][0].update(
        duration=0.25,
        dt=0.1,
        events=[{"time": 0.1, "inputs": {"sensor": {"value": 12.0}}}],
        checks=[
            check("initial", 0.1, -1.0),
            check("default", 0.2, 2.01, abs_tol=0.011),
            check("relative", 0.25, 12.1, rel_tol=0.01),
        ],
    )
    report = c.run_suite(p, value)
    assert report["status"] == "passed"
    assert [row["actual"] for row in report["cases"][0]["comparisons"]] == [-1.0, 2.0, 12.0]
    value["cases"][0]["checks"][-1]["rel_tol"] = 0.001
    assert c.run_suite(p, value)["status"] == "failed"


@pytest.mark.parametrize(
    "quality", ["open-circuit", "short-circuit", "unreliable", "out-of-service"]
)
def test_quality_fault_transaction_and_unrun_checks(quality):
    p = program()
    value = suite(p)
    case = value["cases"][0]
    case.update(
        duration=2.0,
        events=[{"time": 1.0, "inputs": {"sensor": {"value": 4.0, "quality": quality}}}],
        checks=[check("initial", 1.0, -1.0)],
        expected_fault={"time": 2.0, "contains": quality},
    )
    report = c.run_suite(p, value)
    assert report["status"] == "passed"
    fault = report["cases"][0]["fault"]
    assert fault["snapshot_unchanged"] and fault["passed"]
    assert report["cases"][0]["attempted_scans"] == 2
    case["expected_fault"]["contains"] = "not the expected fault"
    assert c.run_suite(p, value)["status"] == "failed"
    case.pop("expected_fault")
    case["checks"].append(check("notreached", 2.0, 2.0))
    failed = c.run_suite(p, value)["cases"][0]
    assert failed["not_run"][0]["id"] == "notreached"
    assert not failed["fault"]["passed"]


def test_expected_fault_missing_and_no_checks_is_not_vacuous_pass():
    p = program()
    value = suite(p)
    value["cases"][0].update(
        events=[], checks=[], expected_fault={"time": 3.0, "contains": "literal"}
    )
    result = c.run_suite(p, value)
    assert result["status"] == "failed" and result["cases"][0]["expected_fault_missing"]
    value["cases"][0]["expected_fault"] = None
    with pytest.raises(ValueError, match="at least one"):
        c.validate_suite(p, value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(program_sha256="0" * 64),
        lambda s: s.update(program_id="different"),
        lambda s: s.update(program_revision=4),
        lambda s: s.update(execution_profile_sha256="0" * 64),
        lambda s: s["signals"][0].update(unit="degC"),
        lambda s: s["cases"][0]["checks"][0].update(unit="degC"),
        lambda s: s["cases"][0]["checks"][0].update(signal="missing"),
        lambda s: s["cases"][0]["checks"][0].update(expected=True),
        lambda s: s["cases"][0]["events"][0]["inputs"]["sensor"].update(value="5"),
        lambda s: s["cases"][0]["events"][0].update(inputs={"state": {"value": 1.0}}),
        lambda s: s["cases"][0]["events"][0].update(time=0.5),
        lambda s: s["cases"][0]["checks"][0].update(time=0.5),
        lambda s: s["cases"][0].update(start_clock="2026-01-01T00:00:00"),
        lambda s: s["cases"][0].update(expected_fault={"time": 2.0}),
        lambda s: s["cases"][0]["checks"][0].update(abs_tol=-1.0),
        lambda s: s["cases"][0]["checks"][0].update(rel_tol=1.1),
        lambda s: s["cases"][0]["checks"][0].update(expected=float("inf")),
        lambda s: s.update(version=True),
        lambda s: s.update(name="   "),
        lambda s: s["cases"].append(copy.deepcopy(s["cases"][0])),
        lambda s: s["cases"][0]["checks"].append(copy.deepcopy(s["cases"][0]["checks"][0])),
        lambda s: s["cases"][0]["events"].append(copy.deepcopy(s["cases"][0]["events"][0])),
    ],
)
def test_strict_source_units_types_clock_and_grid(mutate):
    p = program()
    value = suite(p)
    mutate(value)
    with pytest.raises(ValueError):
        c.validate_suite(p, value)


def test_boolean_types_tolerance_and_bounds():
    p = program("TimerOn", default=False, unit="", boolean=True)
    value = c.template(p)
    value["cases"][0]["checks"] = [check("boolean", 1.0, 0.0, unit="")]
    with pytest.raises(ValueError, match="Boolean"):
        c.validate_suite(p, value)
    value["cases"][0]["checks"][0].update(expected=False, abs_tol=0.01)
    with pytest.raises(ValueError, match="zero tolerances"):
        c.validate_suite(p, value)
    value = suite()
    value["cases"][0].update(duration=5001.0, dt=1.0)
    with pytest.raises(ValueError, match="scan budget"):
        c.validate_suite(program(), value)
    value["cases"][0].update(duration=1.0, dt=1e-300)
    with pytest.raises(ValueError, match="scan budget"):
        c.validate_suite(program(), value)


def test_total_work_case_check_and_json_budgets(monkeypatch):
    p = program()
    value = suite(p)
    monkeypatch.setattr(c, "MAX_WORK", 11)
    with pytest.raises(ValueError, match="block evaluations"):
        c.validate_suite(p, value)
    monkeypatch.setattr(c, "MAX_WORK", 1_000_000)
    value["cases"] *= 21
    with pytest.raises(ValueError):
        c.validate_suite(p, value)
    with pytest.raises(ValueError, match="finite JSON"):
        c.canonical({"value": float("nan")})
    with pytest.raises(ValueError, match="2MiB"):
        c.parse_document('"' + "x" * c.MAX_BYTES + '"')
    for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', "[", '"\ud800"'):
        with pytest.raises(ValueError):
            c.parse_document(text)


def test_large_numeric_errors_stay_finite_and_report_seal_survives():
    p = program()
    value = suite(p)
    value["cases"][0].update(duration=1.0, events=[], checks=[check("overflow", 1.0, 1e308)])
    p.nodes[1].params["initial"] = -1e308
    value.update(program_sha256=p.digest(), signals=c.template(p)["signals"])
    report = c.run_suite(p, value)
    row = report["cases"][0]["comparisons"][0]
    assert row["error_overflow"] and row["absolute_error"] is None and not row["passed"]
    verify_report(report)


def test_saved_suites_restart_conflicts_source_and_integrity(tmp_path):
    p = program()
    plans = c.ConformancePlans(Store(tmp_path))
    saved = plans.save(c.SaveBody(program=p, suite=suite(p), expected_revision=0))
    assert saved["revision"] == 1
    assert c.ConformancePlans(Store(tmp_path)).load(p, saved["id"]) == saved
    assert plans.list(p)[0]["name"] == "Delay startup and held sample"
    other = p.model_copy(deep=True)
    other.nodes[0].params["default"] = 3.0
    assert plans.list(other) == []
    with pytest.raises(ValueError, match="source"):
        plans.load(other, saved["id"])
    body = c.SaveBody(program=p, suite=saved["suite"], id=saved["id"], expected_revision=1)
    again = plans.save(body)
    assert again["revision"] == 2
    with pytest.raises(Conflict):
        plans.save(body)
    with pytest.raises(Conflict):
        plans.save(c.SaveBody(program=p, suite=suite(p), id="f" * 32, expected_revision=0))
    with pytest.raises(Conflict):
        plans.delete(p, saved["id"], 1)
    with plans.store.connect() as db:
        db.execute("UPDATE conformance_suites SET content=? WHERE id=?", (b"{}", saved["id"]))
    with pytest.raises(ValueError, match="integrity"):
        plans.load(p, saved["id"])


def test_capacity_never_evicts_and_delete_is_revision_guarded(tmp_path, monkeypatch):
    p = program()
    plans = c.ConformancePlans(Store(tmp_path))
    saved = plans.save(c.SaveBody(program=p, suite=suite(p), expected_revision=0))
    monkeypatch.setattr(c, "MAX_PLANS", 1)
    with pytest.raises(ValueError, match="capacity"):
        plans.save(c.SaveBody(program=p, suite=suite(p), expected_revision=0))
    assert len(plans.list(p)) == 1
    assert plans.delete(p, saved["id"], 1) == {"deleted": saved["id"]}
    assert plans.list(p) == []


def test_nested_root_macro_values_are_observable_and_source_is_unchanged():
    from tests.test_macro_integration import nested_rate_program

    p = nested_rate_program()
    original = p.model_dump_json()
    value = c.template(p)
    value["cases"][0].update(
        duration=2.0,
        checks=[
            check("positive", 1.0, 1.0, signal="first", unit=""),
            check("negative", 2.0, -2.0, signal="out_b", unit=""),
        ],
    )
    assert c.run_suite(p, value)["status"] == "passed"
    assert p.model_dump_json() == original
    p.metadata["native_sedona"] = {}
    with pytest.raises(ValueError, match="native Sedona"):
        c.template(p)


def test_clock_drives_schedule_boundary_independently_of_execution_speed():
    p = Program(
        id="clock-check",
        nodes=[
            Node(
                id="hours",
                kind="Schedule",
                value_type="boolean",
                params={"start": "08:00", "end": "17:00", "days": [0]},
            ),
            Node(id="enabled", kind="Output", value_type="boolean"),
        ],
        edges=[Edge(id="a", source="hours", target="enabled")],
    )
    value = c.template(p)
    value["cases"][0].update(
        duration=2.0,
        dt=1.0,
        start_clock="2026-01-05T07:59:58Z",
        checks=[
            check("before", 1.0, False, signal="enabled", unit=""),
            check("opening", 2.0, True, signal="enabled", unit=""),
        ],
    )
    assert c.run_suite(p, value)["status"] == "passed"


def test_global_scan_check_and_report_budgets(monkeypatch):
    p = program()
    value = suite(p)
    case = value["cases"][0]
    case.update(duration=300.0)
    value["cases"] = [copy.deepcopy(case) | {"id": f"case_{i}"} for i in range(20)]
    with pytest.raises(ValueError, match="5000 scans"):
        c.validate_suite(p, value)
    value = suite(p)
    case = value["cases"][0]
    case["checks"] = [check(f"check_{i}", 1.0, -1.0) for i in range(1000)]
    value["cases"] = [copy.deepcopy(case) | {"id": f"case_{i}"} for i in range(3)]
    with pytest.raises(ValueError, match="2000 checks"):
        c.validate_suite(p, value)
    monkeypatch.setattr(c, "MAX_REPORT", 1)
    with pytest.raises(ValueError, match="result exceeds"):
        c.run_suite(p, suite(p))


def test_optimistic_concurrent_writers_have_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    p = program()
    plans = c.ConformancePlans(Store(tmp_path))
    saved = plans.save(c.SaveBody(program=p, suite=suite(p), expected_revision=0))

    def save(name):
        changed = suite(p) | {"name": name}
        try:
            return plans.save(
                c.SaveBody(program=p, suite=changed, id=saved["id"], expected_revision=1)
            )
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, ("Independent writer A", "Independent writer B")))
    winners = [item for item in outcomes if item is not None]
    assert len(winners) == 1 and winners[0]["revision"] == 2
    assert plans.load(p, saved["id"]) == winners[0]


def test_normalized_suite_and_saved_byte_capacity_are_bounded(tmp_path, monkeypatch):
    p = program()
    value = suite(p)
    monkeypatch.setattr(c, "MAX_BYTES", len(c.canonical(value)))
    with pytest.raises(ValueError, match="Normalized"):
        c.validate_suite(p, value)  # Default labels are also included in the stored/exported bound.
    monkeypatch.setattr(c, "MAX_BYTES", 2 * 1024 * 1024)
    plans = c.ConformancePlans(Store(tmp_path))
    saved = plans.save(c.SaveBody(program=p, suite=value, expected_revision=0))
    monkeypatch.setattr(c, "MAX_STORAGE", len(c.canonical(saved["suite"])))
    value["description"] = "Authored larger description"
    with pytest.raises(ValueError, match="capacity"):
        plans.save(c.SaveBody(program=p, suite=value, id=saved["id"], expected_revision=1))
    assert plans.load(p, saved["id"]) == saved


def test_nonrepresentable_integer_cannot_false_pass_zero_tolerance():
    p = program()
    value = suite(p)
    p.nodes[1].params["initial"] = 9007199254740993
    value["cases"][0].update(
        duration=1.0, events=[], checks=[check("precision", 1.0, 9007199254740992.0)]
    )
    # Numeric source admission now refuses this value before an Engine can
    # coerce it through another block and make a zero-tolerance check pass.
    with pytest.raises(ValueError, match="binary64"):
        c.run_suite(p, value)
    p.nodes[1].params["initial"] = -1.0
    value["cases"][0]["checks"][0]["expected"] = 9007199254740993
    with pytest.raises(ValueError, match="binary64"):
        c.validate_suite(p, value)
    value["cases"][0]["checks"][0]["expected"] = 1e20
    value["cases"][0]["events"] = [{"time": 0.0, "inputs": {"sensor": {"value": 9007199254740993}}}]
    with pytest.raises(ValueError, match="binary64"):
        c.validate_suite(p, value)
