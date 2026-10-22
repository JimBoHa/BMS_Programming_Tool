"""Independent finite matrices and sealed, bounded offline table evidence."""

import copy
import hashlib
import json

import pytest
from bms_tool import truth_tables as truth


def seal(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def key(review):
    return {
        "review_id": review["id"],
        "table_sha256": review["table_sha256"],
        "profile_sha256": review["source_profile"]["sha256"],
    }


def evaluated(service, review, **values):
    return service.evaluate(truth.EvaluateBody(**key(review), values=values))


def test_handwritten_mode_matrix_distinguishes_holes_unknown_values_and_real_boolean():
    service = truth.TruthTables()
    result = service.review(truth.template())
    assert result["status"] == "incomplete"
    expected = {(0, False): False, (0, True): None, (1, False): True, (1, True): True}
    for (mode, override), output in expected.items():
        row = evaluated(service, result, mode=mode, override=override)
        assert row["resolved"] is (output is not None)
        assert (row["case"]["output"]["value"] if row["case"]["output"] else None) is output
        assert row["prior_output_used"] is False
        assert row["selection_sha256"] == seal({"mode": mode, "override": override})
    assert result["counts"]["uncovered"] == 1
    assert result["source_profile"]["sources"][0]["pdf_pages"] == [167, 168, 1690, 1691]


@pytest.mark.parametrize(
    "values",
    [
        {"mode": True, "override": False},
        {"mode": 0, "override": 0},
        {"mode": 0.0, "override": False},
        {"mode": "0", "override": False},
        {"mode": 17, "override": False},
        {"mode": 0, "override": None},
        {"mode": 0, "override": float("nan")},
        {"mode": float("inf"), "override": False},
        {"mode": 0},
        {"mode": 0, "override": False, "rogue": True},
    ],
)
def test_selection_requires_exact_complete_known_types(values):
    service = truth.TruthTables()
    review = service.review(truth.template())
    with pytest.raises(ValueError):
        service.evaluate(truth.EvaluateBody(**key(review), values=values))


def test_same_output_overlap_is_rejected_and_explicit_priority_retains_every_shadow():
    source = truth.template()
    copied = copy.deepcopy(source["rows"][0])
    copied.update(id="same-output", label="Independent repeated rule")
    source["rows"].append(copied)
    service = truth.TruthTables()
    rejected = service.review(source)
    assert rejected["status"] == "ambiguous" and rejected["counts"]["overlapping_cases"] == 2
    case = evaluated(service, rejected, mode=1, override=False)["case"]
    assert case["matched_row_ids"] == ["enabled", "same-output"]
    assert case["output"] is None and case["chosen_row_id"] is None
    source["overlap_policy"] = "first-match"
    priority = service.review(source)
    case = evaluated(service, priority, mode=1, override=False)["case"]
    assert case["output"]["value"] is True and case["chosen_row_id"] == "enabled"
    assert case["matched_row_ids"] == ["enabled", "same-output"]
    assert case["shadowed_row_ids"] == ["same-output"]
    assert {
        "row_id": "same-output",
        "code": "fully-shadowed",
        "matches": 2,
        "shadowed": 2,
    } in priority["row_diagnostics"]
    assert priority["table_sha256"] != rejected["table_sha256"]
    raw, _, _ = service.export(truth.ReviewKey(**key(priority)), "review")
    document = json.loads(raw)
    assert all(row[1] == [0, 2] for row in document["coverage"] if len(row[1]) > 1)


def test_conflicting_priority_reordering_changes_chosen_value_and_source_seal():
    source = truth.template()
    source["overlap_policy"] = "first-match"
    first = {
        "id": "inhibit",
        "label": "Explicit first priority",
        "conditions": {"mode": {"kind": "any"}, "override": {"kind": "any"}},
        "output_state_id": "false",
    }
    source["rows"].insert(0, first)
    service = truth.TruthTables()
    before = service.review(source)
    assert evaluated(service, before, mode=1, override=True)["case"]["output"]["value"] is False
    source["rows"].append(source["rows"].pop(0))
    after = service.review(source)
    assert evaluated(service, after, mode=1, override=True)["case"]["output"]["value"] is True
    assert after["table_sha256"] != before["table_sha256"]
    assert after["counts"]["overlapping_cases"] == before["counts"]["overlapping_cases"] == 3


def test_constant_fallback_only_resolves_unlisted_combinations_with_its_rationale():
    source = truth.template()
    source["fallback"] = {
        "output_state_id": "false",
        "rationale": "Explicit shutdown choice for the unlisted combination.",
    }
    service = truth.TruthTables()
    report = service.review(source)
    assert report["status"] == "complete"
    assert report["counts"]["fallback"] == report["counts"]["unlisted_cases"] == 1
    case = evaluated(service, report, mode=0, override=True)["case"]
    assert case["matched_row_ids"] == [] and case["chosen_row_id"] is None
    assert case["disposition"] == "fallback" and case["output"]["value"] is False
    assert case["fallback_rationale"] == source["fallback"]["rationale"]
    page = service.page(truth.PageBody(**key(report), filter="unlisted"))
    assert page["total"] == 1


def test_independent_three_boolean_majority_matrix_has_eight_distinct_results():
    source = truth.template()
    base = copy.deepcopy(source["inputs"][1])
    source["inputs"] = [
        dict(copy.deepcopy(base), id=id, label=id.upper()) for id in ("a", "b", "c")
    ]
    source["rows"] = []
    # Fully specified minterms with a mathematical majority oracle, not a row matcher.
    for number in range(8):
        values = [bool(number & bit) for bit in (4, 2, 1)]
        source["rows"].append(
            {
                "id": f"case{number}",
                "label": f"Case {number}",
                "conditions": {
                    name: {"kind": "state", "state_id": str(value).lower()}
                    for name, value in zip(("a", "b", "c"), values, strict=True)
                },
                "output_state_id": "true" if sum(values) >= 2 else "false",
            }
        )
    service = truth.TruthTables()
    report = service.review(source)
    assert report["status"] == "complete" and report["counts"]["cases"] == 8
    expected = [False, False, False, True, False, True, True, True]
    for number, output in enumerate(expected):
        result = evaluated(
            service, report, a=bool(number & 4), b=bool(number & 2), c=bool(number & 1)
        )
        assert result["case"]["index"] == number
        assert result["case"]["output"]["value"] is output
        assert result["case"]["chosen_row_id"] == f"case{number}"


def test_enum_output_values_and_labels_remain_distinct_from_booleans():
    source = truth.template()
    source["output"] = {
        "id": "result",
        "label": "Plant mode",
        "kind": "enum",
        "states": [
            {"id": "idle", "label": "Idle", "value": -1},
            {"id": "operate", "label": "Operate", "value": 7},
        ],
    }
    source["rows"][0]["output_state_id"] = "operate"
    source["rows"][1]["output_state_id"] = "idle"
    service = truth.TruthTables()
    report = service.review(source)
    state = evaluated(service, report, mode=1, override=False)["case"]["output"]
    assert state == {"id": "operate", "label": "Operate", "value": 7}
    assert type(state["value"]) is int


def bad_sources():
    source = truth.template()
    cases = []

    def add(change):
        candidate = copy.deepcopy(source)
        change(candidate)
        cases.append(candidate)

    add(lambda t: t.update(version=True))
    add(lambda t: t.update(version=1.0))
    add(lambda t: t.update(unknown="field"))
    add(lambda t: t["inputs"][0]["states"][0].update(value=False))
    add(lambda t: t["inputs"][0]["states"][0].update(value=0.0))
    add(lambda t: t["inputs"][0]["states"][0].update(value=2**31))
    add(lambda t: t["inputs"][0]["states"][0].update(value=float("nan")))
    add(lambda t: t["inputs"][0]["states"][0].update(value=float("inf")))
    add(lambda t: t["inputs"][0]["states"][1].update(value=0))
    add(lambda t: t["inputs"][0]["states"][1].update(id="off"))
    add(lambda t: t["inputs"][0].update(states=[]))
    add(lambda t: t["inputs"][1]["states"][0].update(value=0))
    add(lambda t: t["inputs"][1].update(states=t["inputs"][1]["states"][:1]))
    add(lambda t: t["inputs"][1].update(id="mode"))
    add(lambda t: t["output"].update(id="mode"))
    add(lambda t: t["rows"][0]["conditions"].pop("override"))
    add(lambda t: t["rows"][0]["conditions"].update(unknown={"kind": "any"}))
    add(lambda t: t["rows"][0]["conditions"]["mode"].update(state_id="missing"))
    add(lambda t: t["rows"][0]["conditions"]["override"].update(state_id="false"))
    add(lambda t: t["rows"][0].update(output_state_id="missing"))
    add(lambda t: t["rows"][1].update(id="enabled"))
    add(lambda t: t.update(fallback={"output_state_id": "false", "rationale": "   "}))
    add(lambda t: t.update(fallback={"output_state_id": "false", "rationale": "line\nbreak"}))
    add(lambda t: t.update(fallback={"output_state_id": "false", "rationale": "one\x7ftwo"}))
    add(lambda t: t.update(fallback={"output_state_id": "missing", "rationale": "Explicit reason"}))
    add(lambda t: t.update(overlap_policy="implicit"))
    add(lambda t: t.update(label="bad\nlabel"))
    add(lambda t: t.update(id="../../unsafe"))
    add(lambda t: t.update(label="\ud800"))
    return cases


@pytest.mark.parametrize("source", bad_sources())
def test_invalid_structures_types_states_and_reasons_fail_before_review(source):
    service = truth.TruthTables()
    with pytest.raises(ValueError):
        service.review(source)
    assert not service._reports


def test_maximum_product_and_every_overlap_are_preserved_in_bounded_download():
    source = truth.template()
    base = source["inputs"][1]
    source["inputs"] = [
        dict(copy.deepcopy(base), id=f"i{i}", label=f"Input {i}") for i in range(12)
    ]
    source["overlap_policy"] = "first-match"
    source["rows"] = [
        {
            "id": f"r{i}",
            "label": f"Rule {i}",
            "conditions": {item["id"]: {"kind": "any"} for item in source["inputs"]},
            "output_state_id": "true",
        }
        for i in range(128)
    ]
    service = truth.TruthTables()
    report = service.review(source)
    assert report["counts"]["cases"] == report["counts"]["overlapping_cases"] == 4096
    raw, _, _ = service.export(truth.ReviewKey(**key(report)), "review")
    assert len(raw) <= truth.MAX_REPORT_BYTES
    document = json.loads(raw)
    assert len(document["coverage"]) == 4096
    assert all(row[1] == list(range(128)) for row in document["coverage"])
    assert len(report["row_diagnostics"]) == 127
    page = service.page(truth.PageBody(**key(report), offset=4032, limit=64, filter="overlap"))
    assert page["next_offset"] is None and len(page["cases"]) == 64
    assert page["cases"][-1]["shadowed_row_ids"] == [f"r{i}" for i in range(1, 128)]
    source["inputs"][0]["kind"] = "enum"
    source["inputs"][0]["states"] = [
        {"id": f"s{i}", "label": f"State {i}", "value": i} for i in range(3)
    ]
    with pytest.raises(ValueError, match="combination"):
        service.review(source)


def test_unlisted_empty_table_can_only_use_explicit_constant_not_previous_output():
    source = truth.template()
    source["rows"] = []
    service = truth.TruthTables()
    report = service.review(source)
    assert report["counts"]["uncovered"] == 4 and not report["row_usage"]
    assert not evaluated(service, report, mode=1, override=False)["resolved"]


def test_authoritative_source_and_review_downloads_seal_actual_bytes_and_import_exact_source():
    service = truth.TruthTables()
    source = truth.template()
    report = service.review(source)
    source["rows"][0]["output_state_id"] = "false"
    report["counts"]["cases"] = 999
    for kind in ("table", "review"):
        raw, filename, supplied = service.export(truth.ReviewKey(**key(report)), kind)
        document = json.loads(raw)
        assert document.pop("content_sha256") == supplied == seal(document)
        assert filename.endswith(".json")
        assert document["table_sha256"] == seal(document["table"])
        assert document["table"]["rows"][0]["output_state_id"] == "true"
        if kind == "table":
            imported = truth.import_document(raw)
            assert imported["source_file_sha256"] == hashlib.sha256(raw).hexdigest()
            assert imported["table_sha256"] == report["table_sha256"]
        else:
            assert document["counts"]["cases"] == 4


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda d: d["table"].update(label="Tampered"), "content seal"),
        (lambda d: d.update(table_sha256="0" * 64), "source seal"),
        (lambda d: d["source_profile"]["limits"].update(inputs=12.0), "source profile"),
    ],
)
def test_import_seals_and_exact_profile_types_are_not_implicitly_migrated(mutation, error):
    service = truth.TruthTables()
    report = service.review(truth.template())
    raw, _, _ = service.export(truth.ReviewKey(**key(report)), "table")
    document = json.loads(raw)
    mutation(document)
    if error != "content seal":
        document.pop("content_sha256")
        document["content_sha256"] = seal(document)
    with pytest.raises(ValueError, match=error):
        truth.import_document(json.dumps(document).encode())


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e309}',
        b"\xff",
        b"[" * 10000 + b"0" + b"]" * 10000,
        b" " * (truth.MAX_SOURCE_BYTES + 1),
    ],
    ids=[
        "duplicate-key",
        "nonfinite-literal",
        "overflow-number",
        "invalid-utf8",
        "deep-nesting",
        "oversize-source",
    ],
)
def test_strict_raw_parser_refuses_ambiguous_nonfinite_invalid_deep_and_large_json(raw):
    with pytest.raises(ValueError):
        truth.strict_json(raw)


def test_stale_source_profile_and_evicted_session_review_refuse_export_or_evaluation():
    service = truth.TruthTables()
    first = service.review(truth.template())
    bad = key(first) | {"table_sha256": "0" * 64}
    with pytest.raises(ValueError, match="source differs"):
        service.export(truth.ReviewKey(**bad), "review")
    bad = key(first) | {"profile_sha256": "0" * 64}
    with pytest.raises(ValueError, match="profile changed"):
        service.page(truth.PageBody(**bad))
    for _ in range(8):
        service.review(truth.template())
    assert (
        len(service._reports) == 8
        and sum(map(len, service._reports.values())) <= truth.MAX_CACHE_BYTES
    )
    with pytest.raises(ValueError, match="expired"):
        evaluated(service, first, mode=0, override=False)


def test_otherwise_valid_sealed_documents_still_require_utf8_unique_keys_and_size_bound():
    service = truth.TruthTables()
    report = service.review(truth.template())
    raw, _, _ = service.export(truth.ReviewKey(**key(report)), "table")
    with pytest.raises(ValueError, match="Malformed"):
        truth.import_document(raw.decode("utf-8").encode("utf-16"))
    duplicate = raw.replace(
        b'"format":"bms.truth-table-document"',
        b'"format":"bms.truth-table-document","format":"bms.truth-table-document"',
        1,
    )
    with pytest.raises(ValueError, match="Duplicate JSON keys"):
        truth.import_document(duplicate)
    oversized = raw + b" " * (truth.MAX_SOURCE_BYTES + 1 - len(raw))
    with pytest.raises(ValueError, match="exceeds1MiB"):
        truth.import_document(oversized)
