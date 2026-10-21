"""Public authored loads and documented-profile guards; no electrical field access."""

import copy
import math

import pytest
from bms_tool.sensor_supply import (
    CATALOG,
    PlanSave,
    SupplyPlans,
    canonical,
    evaluate,
    template,
    validate_plan,
)
from bms_tool.storage import Conflict, Store


def rail(profile_id=None, **changes):
    profile = next((row for row in CATALOG["rails"] if row["id"] == profile_id), None)
    result = {
        "id": "rail-1",
        "name": "Authored supply",
        "unit_id": "Physical supply 1",
        "profile_id": profile_id,
        "profile_sha256": profile["profile_sha256"] if profile else None,
        "spec": copy.deepcopy(profile["spec"])
        if profile
        else {
            "domain": "dc",
            "nominal_v": 15.0,
            "current_limit_ma": 100.0,
            "source_output": True,
            "terminals": [{"id": "A", "current_limit_ma": None}],
        },
        "operating_min_v": 15.0,
        "operating_max_v": 15.0,
        "loads_complete": True,
        "notes": "Authored user declaration",
    }
    result.update(changes)
    return result


def load(rail_row, profile=False):
    definition = CATALOG["loads"][0] if profile else None
    return {
        "id": "load-1",
        "name": "Authored load",
        "rail_id": rail_row["id"],
        "terminal_id": rail_row["spec"]["terminals"][0]["id"],
        "quantity": 1,
        "profile_id": definition["id"] if profile else None,
        "profile_sha256": definition["profile_sha256"] if profile else None,
        "spec": copy.deepcopy(definition["spec"])
        if profile
        else {
            "dc": {
                "min_v": 13.5,
                "max_v": 26.4,
                "steady": {"amount": 40.0, "unit": "mA", "basis": "maximum"},
                "startup": {"amount": 80.0, "unit": "mA", "basis": "maximum"},
            },
            "ac": None,
        },
        "notes": "Authored maximum, not a manufacturer claim",
    }


def plan(rail_row=None, load_row=None):
    rail_row = rail_row or rail()
    return template() | {
        "name": "Authored supply budget",
        "rails": [rail_row],
        "loads": [load_row or load(rail_row)],
    }


def test_published_profiles_separate_exact_models_shared_limits_passthrough_and_unknown_tolerance():
    profiles = {row["model"]: row for row in CATALOG["rails"]}
    assert profiles["FX-PCG2611-0"]["spec"]["current_limit_ma"] == 100
    assert profiles["FX-PCX3711-0"]["spec"]["current_limit_ma"] == 100
    for model in ("FX-PCV1615-0", "FX-PCV1630-0", "MS-VMA1615-0", "MS-VMA1630-0"):
        assert profiles[model]["spec"]["current_limit_ma"] == 35
        assert profiles[model]["spec"]["terminals"] == [{"id": "+15V", "current_limit_ma": None}]
    assert not profiles["FX-PCX3721-0"]["spec"]["source_output"]
    assert profiles["FX-PCX3721-0"]["spec"]["current_limit_ma"] is None
    assert all(len(row["source"]["sha256"]) == 64 for row in profiles.values())
    assert "text extraction" in profiles["FX-PCX3711-0"]["source"]["artifact"]
    assert "FX-PCV1610-0" not in profiles and "FX-PCV1630-1" not in profiles


def test_generic_exact_maximums_have_useful_totals_without_manufacturer_or_wiring_approval():
    data = plan()
    result = evaluate(data)
    assert result["status"] == "within-declared-limits"
    row = result["rails"][0]
    assert row["budgets"][0]["phases"]["steady"]["known_total_ma"] == 40
    assert row["budgets"][0]["phases"]["startup"]["remaining_from_known_ma"] == 20
    assert (
        row["provenance"]["kind"] == "user-declared"
        and not row["provenance"]["documented_in_manufacturer_source"]
    )
    assert row["operating_range"]["basis"] == "user-declared"
    assert row["spec"] == data["rails"][0]["spec"]
    assert row["notes"] == data["rails"][0]["notes"]
    assert row["loads"][0]["notes"] == data["loads"][0]["notes"]
    assert row["loads"][0]["spec"]["dc"]["steady"] == {
        "amount": 40.0,
        "unit": "mA",
        "basis": "maximum",
    }
    assert not result["wiring_verified"] and not result["controller_writes"]


@pytest.mark.parametrize("model", ["FX-PCV1630-0:universal-15v", "MS-VMA1615-0:universal-15v"])
def test_one_combined_belimo_sensor_is_one_load_and_published_watts_do_not_become_maximum_or_inrush(
    model,
):
    supply = rail(model)
    result = evaluate(plan(supply, load(supply, profile=True)))
    row = result["rails"][0]
    assert result["status"] == "incomplete"
    assert len(row["loads"]) == 1 and row["loads"][0]["quantity"] == 1
    assert row["loads"][0]["steady"]["ma"] == pytest.approx(0.4 / 15 * 1000)
    assert row["loads"][0]["steady"]["basis"] == "published-unspecified"
    assert not row["loads"][0]["steady"]["maximum_known"]
    assert row["loads"][0]["startup"]["ma"] is None
    assert row["budgets"][0]["phases"]["startup"]["unknown_loads"] == 1
    assert (
        row["provenance"]["documented_in_manufacturer_source"]
        and not row["provenance"]["installed_verified"]
    )


def test_quantity_is_physical_devices_not_signal_channels_and_can_exceed_shared_budget():
    supply = rail("FX-PCV1630-0:universal-15v")
    sensor = load(supply, profile=True)
    sensor["quantity"] = 2
    result = evaluate(plan(supply, sensor))
    total = result["rails"][0]["budgets"][0]["phases"]["steady"]
    assert total["known_total_ma"] == pytest.approx(53.3333333333)
    assert total["status"] == "exceeded" and result["status"] == "over-budget"
    assert result["rails"][0]["budgets"][0]["phases"]["startup"]["unknown_loads"] == 2


def test_power_type_voltage_envelope_and_apparent_power_are_not_interchangeable():
    supply = rail()
    supply["spec"].update(domain="ac", nominal_v=24)
    supply.update(operating_min_v=24, operating_max_v=24)
    result = evaluate(plan(supply, load(supply, profile=True)))
    assert result["rails"][0]["loads"][0]["steady"]["ma"] == pytest.approx(0.8 / 24 * 1000)
    assert result["status"] == "incomplete"
    result = evaluate(plan(supply))
    assert result["status"] == "incompatible"  # DC-only authored sensor on AC supply.
    supply.update(operating_min_v=21.0, operating_max_v=26.4)
    assert evaluate(plan(supply, load(supply, profile=True)))["status"] == "incompatible"
    supply = rail("FX-PCV1630-0:universal-15v", operating_min_v=13.0, operating_max_v=16.0)
    assert evaluate(plan(supply, load(supply, profile=True)))["status"] == "incompatible"
    supply.update(operating_min_v=None, operating_max_v=None)
    result = evaluate(plan(supply, load(supply, profile=True)))
    assert result["rails"][0]["loads"][0]["voltage_status"] == "unknown-envelope"
    assert result["status"] == "incomplete"


def test_dc_power_uses_lowest_declared_voltage_and_ac_watts_without_power_factor_stay_unknown():
    supply = rail(operating_min_v=14.0, operating_max_v=16.0)
    sensor = load(supply)
    sensor["spec"]["dc"]["steady"].update(amount=0.4, unit="W")
    result = evaluate(plan(supply, sensor))
    assert result["rails"][0]["loads"][0]["steady"]["ma"] == pytest.approx(0.4 / 14 * 1000)
    supply["spec"].update(domain="ac", nominal_v=24)
    supply.update(operating_min_v=24, operating_max_v=24)
    sensor["spec"]["ac"] = sensor["spec"].pop("dc")
    result = evaluate(plan(supply, sensor))
    assert result["status"] == "incomplete"
    assert result["rails"][0]["loads"][0]["steady"]["ma"] is None
    assert "power factor" in result["rails"][0]["loads"][0]["steady"]["method"]


def test_shared_and_terminal_limits_both_count_all_loads_and_startup():
    supply = rail()
    supply["spec"]["terminals"] = [
        {"id": "A", "current_limit_ma": 75.0},
        {"id": "B", "current_limit_ma": 75.0},
    ]
    result = evaluate(plan(supply))
    assert result["status"] == "over-budget"  # Startup80 > terminal75 despite total100.
    assert result["rails"][0]["budgets"][1]["phases"]["startup"]["status"] == "exceeded"
    second = load(supply) | {"id": "load-2", "terminal_id": "B"}
    data = plan(supply)
    data["loads"].append(second)
    result = evaluate(data)
    assert result["rails"][0]["budgets"][0]["phases"]["steady"]["known_total_ma"] == 80
    assert result["rails"][0]["budgets"][0]["phases"]["startup"]["known_total_ma"] == 160
    assert result["status"] == "over-budget"


@pytest.mark.parametrize("change", ["coverage", "unknown-limit", "typical", "startup", "voltage"])
def test_unknowns_and_typical_values_never_acquire_full_budget_acceptance(change):
    data = plan()
    if change == "coverage":
        data["rails"][0]["loads_complete"] = False
    if change == "unknown-limit":
        data["rails"][0]["spec"]["current_limit_ma"] = None
    if change == "typical":
        data["loads"][0]["spec"]["dc"]["steady"]["basis"] = "typical"
    if change == "startup":
        data["loads"][0]["spec"]["dc"]["startup"] = {
            "amount": None,
            "unit": "mA",
            "basis": "unknown",
        }
    if change == "voltage":
        data["rails"][0].update(operating_min_v=None, operating_max_v=None)
    assert evaluate(data)["status"] == "incomplete"


def test_pass_through_and_auxiliary_rails_cannot_be_treated_as_external_24vac():
    supply = rail("FX-PCX3721-0:sa-pwr-pass-through")
    assert evaluate(plan(supply, load(supply, profile=True)))["status"] == "incompatible"
    supply = rail("FX-PCG2611-0:universal-15v")
    data = plan(supply)
    data["rails"][0]["spec"]["domain"] = "ac"
    data["rails"][0]["spec"]["nominal_v"] = 24
    with pytest.raises(ValueError):
        validate_plan(data)


@pytest.mark.parametrize(
    "change",
    [
        "catalog",
        "profile-hash",
        "profile-spec",
        "unknown-model",
        "fake-custom-hash",
        "version",
        "format",
    ],
)
def test_exact_catalog_profile_and_source_guards_reject_stale_forged_definitions(change):
    supply = rail("FX-PCG2611-0:universal-15v")
    data = plan(supply, load(supply, profile=True))
    if change == "catalog":
        data["catalog_sha256"] = "0" * 64
    if change == "profile-hash":
        data["rails"][0]["profile_sha256"] = "0" * 64
    if change == "profile-spec":
        data["loads"][0]["spec"]["dc"]["steady"]["basis"] = "maximum"
    if change == "unknown-model":
        data["rails"][0]["profile_id"] = "FX-PCG2611-999:universal-15v"
    if change == "fake-custom-hash":
        data["rails"][0]["profile_id"] = None
    if change == "version":
        data["version"] = True
    if change == "format":
        data.pop("format")
    with pytest.raises(ValueError):
        validate_plan(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["rails"][0]["spec"].update(nominal_v=0),
        lambda d: d["rails"][0]["spec"].update(nominal_v=1e-320),
        lambda d: d["rails"][0]["spec"].update(current_limit_ma=-1),
        lambda d: d["rails"][0]["spec"].update(current_limit_ma=float("nan")),
        lambda d: d["loads"][0].update(quantity=True),
        lambda d: d["loads"][0].update(quantity=101),
        lambda d: d["loads"][0].update(terminal_id="missing"),
        lambda d: d["loads"][0]["spec"]["dc"].update(min_v=30),
        lambda d: d["loads"][0]["spec"]["dc"]["steady"].update(amount=float("inf")),
        lambda d: d["loads"][0]["spec"]["dc"]["steady"].update(basis="unknown"),
        lambda d: d["rails"][0].update(operating_min_v=None),
        lambda d: d.update(name=" "),
        lambda d: d.update(extra=True),
    ],
)
def test_nonfinite_ambiguous_and_bounded_requests_fail_explicitly(mutate):
    data = plan()
    mutate(data)
    with pytest.raises(ValueError):
        validate_plan(data)


def test_duplicate_physical_supply_does_not_create_a_second_shared_budget():
    data = plan()
    data["rails"].append(
        copy.deepcopy(data["rails"][0]) | {"id": "rail-2", "unit_id": "physical SUPPLY 1"}
    )
    with pytest.raises(ValueError, match="physical supply"):
        validate_plan(data)


def test_zero_declared_load_is_explicit_and_empty_plan_does_not_pass():
    data = plan()
    for phase in ("steady", "startup"):
        data["loads"][0]["spec"]["dc"][phase]["amount"] = 0
    assert evaluate(data)["status"] == "within-declared-limits"
    assert evaluate(template())["status"] == "incomplete"


def test_saved_plan_reopens_after_restart_conflicts_and_atomic_quotas(tmp_path, monkeypatch):
    import bms_tool.sensor_supply as module

    service = SupplyPlans(Store(tmp_path), None)
    saved = service.save(PlanSave(plan=plan(), expected_revision=0))
    assert SupplyPlans(Store(tmp_path), None).load(saved["id"]) == saved
    newer = service.save(
        PlanSave(plan=plan() | {"name": "Changed"}, id=saved["id"], expected_revision=1)
    )
    assert newer["revision"] == 2
    with pytest.raises(Conflict):
        service.save(PlanSave(plan=plan(), id=saved["id"], expected_revision=1))
    with pytest.raises(Conflict):
        service.delete(saved["id"], 1)
    monkeypatch.setattr(module, "MAX_PLANS", 1)
    with pytest.raises(ValueError, match="capacity"):
        service.save(PlanSave(plan=plan(), expected_revision=0))
    monkeypatch.setattr(module, "MAX_STORAGE", len(canonical(newer["plan"])))
    assert (
        service.save(PlanSave(plan=newer["plan"], id=saved["id"], expected_revision=2))["revision"]
        == 3
    )
    with pytest.raises(ValueError, match="capacity"):
        service.save(
            PlanSave(
                plan=newer["plan"] | {"name": "Longer changed name"},
                id=saved["id"],
                expected_revision=3,
            )
        )
    assert service.load(saved["id"])["revision"] == 3
    service.delete(saved["id"], 3)
    assert service.list() == []


def test_corrupt_saved_content_is_unavailable_but_can_be_removed_without_field_actions(tmp_path):
    store = Store(tmp_path)
    service = SupplyPlans(store, None)
    saved = service.save(PlanSave(plan=plan(), expected_revision=0))
    with store.connect() as db:
        db.execute("UPDATE sensor_supply_plans SET content=? WHERE id=?", (b"{}", saved["id"]))
    with pytest.raises(ValueError, match="integrity"):
        service.load(saved["id"])
    assert service.list()[0]["available"] is False
    service.delete(saved["id"], 1)
    assert service.list() == []


def test_extreme_permitted_numbers_produce_finite_bounded_arithmetic():
    supply = rail(operating_min_v=0.01, operating_max_v=1000)
    supply["spec"]["nominal_v"] = 15
    sensor = load(supply)
    sensor["spec"]["dc"].update(min_v=0.01, max_v=1000)
    sensor["spec"]["dc"]["steady"].update(amount=1000000.0, unit="W")
    sensor["quantity"] = 100
    result = evaluate(plan(supply, sensor))
    assert result["status"] == "over-budget"
    assert math.isfinite(result["rails"][0]["budgets"][0]["phases"]["steady"]["known_total_ma"])
    canonical(result)
