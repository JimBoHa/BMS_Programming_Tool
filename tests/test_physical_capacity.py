"""Independent published count fixtures and finite resource-pool matching, no field I/O."""

import copy
import itertools

import pytest
from bms_tool.physical_capacity import (
    CATALOG,
    CapacityRequest,
    canonical,
    catalog,
    digest,
    evaluate,
)
from pydantic import ValidationError

# Authored independently from LIT-12011657 Tables 2/5/7/9/10 and
# LIT-12011042 Tables 5/13. These are physical counts, not native slot identities.
EXPANSIONS = {
    "1711-0": {"BI": 4},
    "2711-0": {"UI": 2, "UO": 2, "RO": 2},
    "2711-2": {"UI": 2, "UO": 2, "RO": 2},
    "2721-0": {"UI": 8, "AO": 2},
    "2723-0": {"UI": 8, "AO": 2},
    "3711-0": {"UI": 4, "UO": 4, "RO": 4},
    "3711-2": {"UI": 4, "UO": 4, "RO": 4},
    "3721-0": {"BI": 16},
    "3723-0": {"BI": 16},
    "3731-0": {"BI": 8, "BO": 8},
    "3733-0": {"BI": 8, "BO": 8},
    "4711-0": {"UI": 6, "BI": 2, "AO": 2, "BO": 3, "CO": 4},
}
EXPECTED = {
    **{
        ("CH-PCX" if suffix[:4] in {"2723", "3723", "3733"} else "FX-PCX") + suffix: counts
        for suffix, counts in EXPANSIONS.items()
    },
    **{"MS-IOM" + suffix: counts for suffix, counts in EXPANSIONS.items()},
    "FX-PCG1611-1": {"UI": 2, "BI": 1, "BO": 3, "CO": 4},
    "FX-PCG1621-1": {"UI": 2, "BI": 1, "BO": 3, "CO": 4},
    "FX-PCG2611-0": {"UI": 6, "BI": 2, "AO": 2, "BO": 3, "CO": 4},
    "FX-PCG2621-0": {"UI": 6, "BI": 2, "AO": 2, "BO": 3, "CO": 4},
    "FX-PCV1615-0": {"UI": 3, "BO": 2},
    "FX-PCV1630-0": {"UI": 3, "BO": 3, "CO": 2},
    "MS-VMA1615-0": {"UI": 3, "BO": 2},
    "MS-VMA1630-0": {"UI": 3, "BO": 3, "CO": 2},
}


def request(model="FX-PCX3721-0", *demands):
    return {
        "catalog_sha256": CATALOG["catalog_sha256"],
        "model": model,
        "demands": [
            {"id": f"d{i}", "label": f"Declared signal {i}", "mode": mode, "quantity": count}
            for i, (mode, count) in enumerate(demands)
        ],
    }


@pytest.mark.parametrize("model,counts", sorted(EXPECTED.items()))
def test_exact_physical_count_matrix_from_primary_manual_tables(model, counts):
    profile = next(row for row in CATALOG["models"] if row["model"] == model)
    assert {pool["id"]: pool["count"] for pool in profile["pools"]} == counts
    assert profile["external_point_count"] == sum(counts.values())
    assert profile["bus_families"] == ["FC", "SA"]
    assert all(pool["terminal_identifiers"] is None for pool in profile["pools"])
    assert not profile["terminal_numbering_verified"]
    assert not profile["native_allocation_verified"]
    assert all(len(CATALOG["sources"][key]["sha256"]) == 64 for key in profile["source_ids"])


def test_catalog_seal_copy_and_exact_scope_does_not_grow_from_prefix_suffix_or_other_brand():
    assert len(CATALOG["models"]) == len(EXPECTED) == 32
    assert (
        digest({k: v for k, v in CATALOG.items() if k != "catalog_sha256"})
        == CATALOG["catalog_sha256"]
    )
    changed = catalog()
    changed["models"][0]["pools"][0]["count"] = 500
    assert changed != catalog()
    for model in [
        "FX-PCX3721",
        "FX-PCX3721-0G",
        "FX-PCX2723-0",
        "CH-PCX2721-0",
        "MS-IOM3711-0U",
        "FX-PCG1611-0",
        "MS-VMA1630-1",
        "VMA1630",
    ]:
        report = evaluate(request(model, ("input-contact", 1)))
        assert report["status"] == "unknown-model" and report["model_profile"] is None
        assert report["matched_channels"] == 0 and report["demands"][0]["unmatched"] == 1
    assert evaluate(request("  fx-pcx3721-0  ", ("input-contact", 1)))["status"] == "count-mode-fit"


def test_dedicated_binary_does_not_become_analog_and_vav_ui_has_no_current_mode():
    binary = evaluate(request("FX-PCX3721-0", ("input-voltage", 2), ("input-contact", 2)))
    assert binary["status"] == "count-mode-shortfall"
    assert [row["matched"] for row in binary["demands"]] == [0, 2]
    assert binary["demands"][0]["unmatched_basis"] == "no-reviewed-pool-for-mode"
    for model in ["FX-PCV1615-0", "FX-PCV1630-0", "MS-VMA1615-0", "MS-VMA1630-0"]:
        report = evaluate(request(model, ("input-current", 1), ("input-voltage", 3)))
        assert report["matched_channels"] == 3
        assert report["model_profile"]["onboard_features"] == [
            "integrated differential-pressure transducer",
            "integrated actuator",
        ]
        assert report["model_profile"]["external_point_count"] in (5, 8)


def test_uo_co_and_ui_alternative_modes_consume_one_shared_physical_channel():
    report = evaluate(
        request(
            "FX-PCX2711-0",
            ("output-voltage", 2),
            ("output-current", 2),
            ("output-fet", 2),
            ("output-relay", 2),
        )
    )
    assert report["declared_channels"] == 8 and report["matched_channels"] == 4
    assert next(pool for pool in report["pools"] if pool["id"] == "UO")["used_in_witness"] == 2
    assert next(pool for pool in report["pools"] if pool["id"] == "RO")["used_in_witness"] == 2
    report = evaluate(request("FX-PCG1611-1", ("output-triac", 7), ("output-voltage", 1)))
    assert report["matched_channels"] == 7  # BO3 + CO4; voltage cannot add an eighth output.
    report = evaluate(request("MS-IOM2721-0", ("input-contact", 8), ("input-current", 1)))
    assert report["matched_channels"] == 8
    assert all(row["terminal_assignment"] is None for row in report["demands"])


def test_matching_finds_augmenting_path_instead_of_greedily_wasting_universal_inputs():
    # Contact first could consume UI6. Dedicated BI2 must free UI for voltage6.
    for demands in itertools.permutations([("input-contact", 2), ("input-voltage", 6)]):
        report = evaluate(request("FX-PCG2611-0", *demands))
        assert report["status"] == "count-mode-fit" and report["matched_channels"] == 8
        contact = next(row for row in report["demands"] if row["mode"] == "input-contact")
        assert contact["pool_count_witness"] == [{"pool": "BI", "quantity": 2}]
    # BO3+CO4: flexible triac demand must leave CO4 for voltage demand.
    report = evaluate(request("FX-PCG1611-1", ("output-triac", 3), ("output-voltage", 4)))
    assert report["status"] == "count-mode-fit"


def test_source_conflicts_and_external_power_note_remain_visible_without_choosing_rating():
    report = evaluate(request("FX-PCX3711-2", ("output-relay", 4)))
    assert report["status"] == "count-mode-fit" and report["source_conflicts_present"]
    assert {row["code"] for row in report["model_profile"]["conflicts"]} == {
        "relay-label-conflict",
        "relay-voltage-conflict",
    }
    assert "24 VAC" in canonical(report).decode() and "240 VAC" in canonical(report).decode()
    assert not report["electrical_compatibility_verified"]
    assert "pulse-frequency-conflict" in canonical(evaluate(request())).decode()
    binary_sources = evaluate(request("FX-PCX3731-0"))
    assert "binary-output-source-conflict" in canonical(binary_sources).decode()
    assert "pcx37-binary" in binary_sources["sources"]
    assert "pcx-installation" not in binary_sources["sources"]
    for model in ["CH-PCX3733-0", "MS-IOM3733-0"]:
        assert "external low-voltage" in canonical(evaluate(request(model))).decode()
    assert "text-extraction" in CATALOG["sources"]["pcx-installation"]["artifact"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"catalog_sha256": "0" * 64},
        {"extra": True},
        {"demands": [{"id": "x", "mode": "input-voltage", "quantity": True}]},
        {"demands": [{"id": "x", "mode": "input-voltage", "quantity": 1.0}]},
        {"demands": [{"id": "x", "mode": "input-voltage", "quantity": 65}]},
        {"demands": [{"id": "x", "mode": "input-bacnet", "quantity": 1}]},
        {"demands": [{"id": "x", "mode": "input-voltage", "quantity": 1}] * 2},
        {"demands": [{"id": f"d{i}", "mode": "input-voltage", "quantity": 64} for i in range(17)]},
        {"demands": [{"id": f"d{i}", "mode": "input-voltage", "quantity": 1} for i in range(33)]},
        {
            "survey_reference": {
                "id": "a" * 32,
                "content_sha256": "b" * 64,
                "host": "base",
                "sa_mac": 7,
            }
        },
    ],
)
def test_strict_finite_request_and_catalog_guard(mutation):
    with pytest.raises((ValueError, ValidationError)):
        evaluate(request() | mutation)


def test_no_demand_and_largest_bounded_request_do_not_invent_free_terminals():
    report = evaluate(request("MS-IOM3721-0"))
    assert report["status"] == "no-demand-declared" and report["matched_channels"] == 0
    assert "spare" in report["scope"]
    report = evaluate(request("MS-IOM3721-0", *[("input-contact", 64)] * 16))
    assert report["declared_channels"] == 1024 and report["matched_channels"] == 16
    original = copy.deepcopy(report)
    assert (
        digest({k: v for k, v in report.items() if k != "content_sha256"})
        == report["content_sha256"]
    )
    assert report == original


def test_survey_reference_preserves_corroboration_conflicts_without_upgrading_physical_identity():
    report = {
        "content_sha256": "b" * 64,
        "identity": {"model": "FX-PCG2611-0"},
        "target": {"device": "device,123"},
        "modules": [{"host": "sa", "sa_mac": 7, "configured_model": "FX-PCX3721-0"}],
        "archive_comparison": {
            "conflicts": [{"error": "Authored model corroboration conflict"}],
            "unresolved": [{"error": "Authored unknown assignment"}],
        },
    }

    class Hardware:
        def report(self, key):
            assert key == "a" * 32
            return report

    before = copy.deepcopy(report)
    body = request("FX-PCX3721-0", ("input-contact", 16)) | {
        "survey_reference": {"id": "a" * 32, "content_sha256": "b" * 64, "host": "sa", "sa_mac": 7}
    }
    result = evaluate(body, Hardware())
    assert result["status"] == "count-mode-fit"
    assert result["survey_binding"]["source_conflicts"] == report["archive_comparison"]["conflicts"]
    assert (
        result["survey_binding"]["source_unresolved"] == report["archive_comparison"]["unresolved"]
    )
    assert not result["survey_binding"]["physical_identity_verified"]
    assert report == before
    report["modules"].append(copy.deepcopy(report["modules"][0]))
    with pytest.raises(ValueError, match="unambiguous"):
        evaluate(body, Hardware())
    with pytest.raises(ValueError, match="unavailable"):
        evaluate(body)


@pytest.mark.parametrize("text", ["\ud800", "\u0000", "\u0080"])
def test_invalid_model_text_is_rejected_before_evidence_serialization(text):
    with pytest.raises(ValueError):
        CapacityRequest.model_validate(request(text))
