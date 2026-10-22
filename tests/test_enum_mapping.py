"""Offline declaration review: no native/portable code or label equivalence assumed."""

import copy
import hashlib
import json

import pytest
from bms_tool.enum_mapping import (
    EnumMappingExport,
    EnumMappingRequest,
    canonical,
    export_review,
    import_plan,
    review_enum_mapping,
)


def plan():
    return {
        "source": {
            "namespace": "declared/source",
            "id": "mode",
            "datatype": "bacnet-binarypv",
            "states": [
                {"id": "stopped", "code": 0, "label": "Off"},
                {"id": "running", "code": 1, "label": "On"},
            ],
        },
        "target": {
            "namespace": "declared/target",
            "id": "output-mode",
            "datatype": "bacnet-multistate",
            "number_of_states": 3,
            "states": [
                {"id": "stop", "code": 1, "label": "Stop"},
                {"id": "run", "code": 2, "label": "Run"},
                {"id": "hold", "code": 3, "label": "Hold"},
            ],
        },
        "mappings": [{"source_code": 0, "target_code": 1}, {"source_code": 1, "target_code": 2}],
        "probes": [0, 1, 99, None],
    }


def codes(report):
    return {r["code"] for r in report["findings"]}


def test_complete_source_map_with_extra_target_does_not_claim_bijection_or_binding():
    document = plan()
    report = review_enum_mapping(document)
    assert report["status"] == "valid_declared_mapping"
    assert report["properties"] == {
        "source_function_complete": True,
        "lossless": True,
        "target_coverage": False,
        "semantic_equivalence": "not established",
        "native_or_portable_binding": "not established",
    }
    assert report["unreachable_target_codes"] == [3]
    assert (
        report["mapping_evidence"][0]["source_state_id"] == "stopped"
        and report["mapping_evidence"][0]["target_state_id"] == "stop"
    )
    assert (
        report["mapping_evidence"][0]["source_label"] == "Off"
        and report["mapping_evidence"][0]["target_label"] == "Stop"
        and not report["mapping_evidence"][0]["labels_equal"]
    )
    assert [p["status"] for p in report["probes"]] == [
        "mapped_by_declared_table",
        "mapped_by_declared_table",
        "unknown_source_code",
        "unknown_value",
    ]
    assert not report["field_operations"] and not report["executable_lowering"]
    seal = report.pop("review_sha256")
    assert hashlib.sha256(canonical(report)).hexdigest() == seal
    assert (
        hashlib.sha256(canonical(report["source_plan"])).hexdigest() == report["source_plan_sha256"]
    )
    assert document == plan()


@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing", "source_states_not_deterministically_mapped"),
        ("null", "unmapped_source_code"),
        ("source", "unknown_source_code"),
        ("target", "unknown_target_code"),
        ("duplicate", "duplicate_source_mapping"),
        ("collapse", "many_to_one_loss_not_allowed"),
        ("coverage", "target_states_unreachable_from_declared_source"),
    ],
)
def test_invalid_mapping_conditions_remain_explicit(change, expected):
    p = plan()
    if change == "missing":
        p["mappings"].pop()
    elif change == "null":
        p["mappings"][1]["target_code"] = None
    elif change == "source":
        p["mappings"][1]["source_code"] = 9
    elif change == "target":
        p["mappings"][1]["target_code"] = 9
    elif change == "duplicate":
        p["mappings"].append(copy.deepcopy(p["mappings"][0]))
    elif change == "collapse":
        p["mappings"][1]["target_code"] = 1
    elif change == "coverage":
        p["policy"] = {"require_target_coverage": True}
    r = review_enum_mapping(p)
    assert r["status"] == "invalid" and expected in codes(r)
    if change in ("missing", "null", "source", "target", "duplicate"):
        assert r["properties"]["lossless"] is None


def test_lossy_choice_requires_explicit_policy_and_nonblank_rationale():
    p = plan()
    p["mappings"][1]["target_code"] = 1
    p["policy"] = {"allow_many_to_one": True, "loss_rationale": " "}
    r = review_enum_mapping(p)
    assert r["status"] == "invalid" and "loss_rationale_required" in codes(r)
    p["policy"]["loss_rationale"] = "Operator intentionally combines these two modes."
    r = review_enum_mapping(p)
    assert r["status"] == "valid_with_declared_loss"
    assert r["properties"]["source_function_complete"] and r["properties"]["lossless"] is False
    assert r["collapsing_targets"] == [{"target_code": 1, "source_codes": [0, 1]}]
    assert r["policy"]["loss_rationale"] == p["policy"]["loss_rationale"]


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize(
    "change,expected",
    [
        ("duplicate_code", "duplicate_domain_code"),
        ("duplicate_id", "duplicate_state_id"),
        ("incomplete", "domain_declared_incomplete"),
    ],
)
def test_domain_identity_and_completeness_are_reviewed(side, change, expected):
    p = plan()
    domain = p[side]
    if change == "duplicate_code":
        domain["states"][1]["code"] = domain["states"][0]["code"]
    elif change == "duplicate_id":
        domain["states"][1]["id"] = domain["states"][0]["id"]
    else:
        domain["declared_complete"] = False
    r = review_enum_mapping(p)
    assert r["status"] == "invalid" and expected in codes(r)


def test_numeric_bacnet_domains_not_derived_from_names_or_portable_codes():
    p = plan()
    p["source"]["states"][1]["code"] = 2
    r = review_enum_mapping(p)
    assert "binary_domain_must_be_exact_zero_one" in codes(r)
    p = plan()
    p["target"]["states"][0]["code"] = 0
    r = review_enum_mapping(p)
    assert "multistate_domain_incomplete_or_outside_range" in codes(r)
    p = plan()
    p["target"]["number_of_states"] = 4294967295
    r = review_enum_mapping(p)
    summary = r["domains"]["target"]
    assert summary["missing_domain_codes_count"] == 4294967292
    assert summary["missing_domain_codes_sample"] == list(range(4, 36))
    assert len(canonical(r)) < 20000


def test_identical_labels_do_not_merge_codes_or_generate_mapping_rows():
    p = plan()
    p["source"]["states"][1]["label"] = "Off"
    p["target"]["states"][1]["label"] = "Stop"
    p["mappings"] = []
    r = review_enum_mapping(p)
    assert r["mapping_evidence"] == [] and r["missing_source_codes"] == [0, 1]
    assert "duplicate_labels_do_not_merge_codes" in codes(r)


def test_same_namespace_and_domain_id_cannot_mean_different_state_sets():
    p = plan()
    p["target"]["namespace"] = p["source"]["namespace"]
    p["target"]["id"] = p["source"]["id"]
    r = review_enum_mapping(p)
    assert r["status"] == "invalid" and "same_domain_identity_has_conflicting_definition" in codes(
        r
    )


@pytest.mark.parametrize(
    "location,value",
    [
        ("source", True),
        ("source", 0.0),
        ("source", "0"),
        ("target", False),
        ("probe", True),
        ("probe", 1.0),
        ("probe", "1"),
    ],
)
def test_strict_codes_never_use_bool_truthiness_numeric_strings_or_float_coercion(location, value):
    p = plan()
    if location == "source":
        p["source"]["states"][0]["code"] = value
    elif location == "target":
        p["mappings"][0]["target_code"] = value
    else:
        p["probes"] = [value]
    with pytest.raises(ValueError):
        EnumMappingRequest(**p)


def test_native_provenance_cannot_be_claimed_by_an_offline_declaration():
    p = plan()
    p["source"]["origin"] = "native-bacnet-readproperty"
    with pytest.raises(ValueError):
        review_enum_mapping(p)


def test_bounded_findings_keep_late_errors_visible_after_label_warning_flood():
    p = plan()
    p["source"] = {
        "namespace": "operator",
        "id": "wide",
        "states": [{"id": f"state-{n}", "code": n, "label": None} for n in range(256)],
    }
    p["mappings"] = []
    r = review_enum_mapping(p)
    assert r["status"] == "invalid" and r["omitted_findings"] > 0
    assert any(
        f["severity"] == "error" for f in r["findings"]
    ) and "source_states_not_deterministically_mapped" in codes(r)
    assert r["finding_code_counts"]["unknown_or_blank_label"] == 256 and len(r["findings"]) <= 128


def test_review_and_source_plan_reopen_require_exact_current_plan_and_rules():
    p = plan()
    r = review_enum_mapping(p)
    request = EnumMappingExport(plan=p, expected_review_sha256=r["review_sha256"])
    assert export_review(request) == r
    r["profile_rules"]["binarypv_codes"].append(9)
    assert review_enum_mapping(p)["profile_rules"]["binarypv_codes"] == [0, 1]
    p["target"]["states"][0]["label"] = "Changed operator label"
    with pytest.raises(ValueError, match="changed"):
        export_review(EnumMappingExport(plan=p, expected_review_sha256=r["review_sha256"]))
    raw = json.dumps(request.plan.model_dump(mode="json"), indent=2).encode()
    imported = import_plan(raw)
    assert imported["review_required"] and imported["origin"] == "operator-declared"
    assert imported["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert imported["source_plan"] == request.plan.model_dump(mode="json")
    assert (
        imported["source_plan_sha256"]
        == hashlib.sha256(canonical(imported["source_plan"])).hexdigest()
    )


@pytest.mark.parametrize(
    "raw",
    [
        b'{"source":{},"source":{}}',
        b'{"source":NaN}',
        b"\xff",
        b"[" * 1500,
        b"x" * (2 * 1024 * 1024 + 1),
    ],
    ids=["duplicate-key", "nonfinite", "invalid-utf8", "deep-nesting", "oversize"],
)
def test_import_rejects_ambiguous_or_unbounded_source(raw):
    with pytest.raises(ValueError):
        import_plan(raw)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_schema_version_does_not_accept_coercible_noninteger_identity(value):
    p = plan() | {"schema_version": value}
    with pytest.raises(ValueError):
        review_enum_mapping(p)


def test_domain_ids_are_nonblank_without_silent_normalization():
    p = plan()
    p["source"]["id"] = "  "
    with pytest.raises(ValueError, match="nonblank"):
        review_enum_mapping(p)


def test_unicode_import_obeys_canonical_source_budget_before_returning_a_plan():
    states = [
        {"id": f"{n:03d}" + "\U0001f4a1" * 97, "code": n, "label": "\U0001f4a1" * 256}
        for n in range(256)
    ]
    p = plan()
    p["source"] = {"namespace": "operator", "id": "source", "states": states}
    p["target"] = {"namespace": "operator", "id": "target", "states": states}
    raw = json.dumps(p, ensure_ascii=False).encode()
    assert len(raw) < 2 * 1024 * 1024
    for operation, value in ((import_plan, raw), (review_enum_mapping, p)):
        with pytest.raises(ValueError, match="canonical source profile"):
            operation(value)


def test_invalid_domain_never_resolves_a_probe_or_selects_an_ambiguous_state_id():
    p = plan()
    p["source"]["states"][1]["code"] = 0
    report = review_enum_mapping(p)
    assert report["status"] == "invalid" and report["mapping_evidence"] == []
    assert [item["status"] for item in report["probes"]] == [
        "invalid_domain_declaration",
        "invalid_domain_declaration",
        "invalid_domain_declaration",
        "unknown_value",
    ]
    assert report["properties"]["lossless"] is None
