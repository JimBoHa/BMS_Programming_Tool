"""Authored configuration records; no site captures, network or SQL access."""

import copy
import json
import os
import stat
import sys

import pytest
from bms_tool.__main__ import main
from bms_tool.metasys_source_preservation import (
    load_capture,
    review_sources,
    write_review,
)


@pytest.fixture
def captures():
    items = [
        dict(
            itemID=1,
            GUID="11111111-1111-4111-8111-111111111111",
            ObjectId="0.501",
            PartialReference="Bus.Meter.Current",
            UserName="Channel current",
            parentItemID=99,
        ),
        dict(
            itemID=2,
            GUID="22222222-2222-4222-8222-222222222222",
            ObjectId="5.502",
            PartialReference="Bus.Meter.Polarity",
            UserName="Polarity",
            parentItemID=99,
        ),
        dict(
            itemID=3,
            GUID="33333333-3333-4333-8333-333333333333",
            ObjectId="0.503",
            PartialReference="Bus.Meter.Energy",
            UserName="Total energy",
            parentItemID=99,
        ),
    ]
    properties = []
    for item, source in [(1, 41), (2, 2), (3, 140)]:
        properties.extend(
            [
                dict(
                    ItemID=item,
                    AttribID=32589,
                    DataTypeID=2,
                    Value=str(source),
                    ValueItemID=None,
                    ValueOrder=1,
                    ParentValueOrder=None,
                    EventTimeStamp="2026-01-01",
                    ValueState=2,
                ),
                dict(
                    ItemID=item,
                    AttribID=117,
                    DataTypeID=9,
                    Value="Units",
                    ValueItemID=None,
                    ValueOrder=1,
                    ParentValueOrder=None,
                ),
            ]
        )
    before = dict(
        captured_utc="2026-01-01T00:00:00+00:00",
        items=items,
        properties=properties,
        incoming_item_references=[dict(ItemID=99, ValueItemID=1, AttribID=7008)],
        incoming_text_references=[dict(ItemID=98, Value="Bus.Meter.Current")],
        historians=[dict(PointID=17, PointGUID=items[2]["GUID"], PointName="Energy")],
        historian_slices=[dict(PointID=17, PointSliceID=17, IsRawData=True)],
        reporting=[dict(PointID=17, SourceID=17, ItemFullyQualifiedReference="Energy")],
    )
    manifest = [
        dict(
            item_id=item["itemID"],
            guid=item["GUID"],
            metasys_object=item["ObjectId"],
            path=item["PartialReference"],
            name=item["UserName"],
            source_type=kind,
            old_source_instance=old,
            proposed_source_instance=new,
        )
        for item, kind, old, new in [(items[0], 0, 41, 81), (items[1], 5, 2, 1)]
    ]
    after = copy.deepcopy(before)
    after["captured_utc"] = "2026-01-01T00:01:00+00:00"
    after["properties"][0]["Value"] = "81"
    after["properties"][2]["Value"] = "1"
    return manifest, before, after


def test_review_and_comparison_are_local_supplemental_evidence_without_apply_authority(captures):
    manifest, before, after = captures
    originals = copy.deepcopy(captures)
    proposal = review_sources(manifest, before)
    assert proposal["point_count"] == 2 and proposal["original_source_preconditions_match"]
    assert proposal["after_checked"] is False and proposal["captured_records_match"] is None
    result = review_sources(manifest, before, after)
    assert result["captured_records_match"]
    assert result["all_expected_sources_observed_in_after_capture"]
    assert result["captured_record_differences"] == []
    assert not result["apply_available"] and not result["network_access"]
    assert not result["native_backup_verified"] and result["configuration_writes"] == 0
    assert "not" in result["boundary"].lower()
    assert result["manifest_sha256"] == proposal["manifest_sha256"]
    assert result["before_sha256"] != result["after_sha256"]
    assert captures == originals  # local identifiers, names and polarity values never rewritten


@pytest.mark.parametrize(
    "field,value",
    [
        ("old_source_instance", 42),
        ("old_source_instance", True),
        ("proposed_source_instance", True),
        ("proposed_source_instance", 4194303),
        ("proposed_source_instance", 41),
        ("source_type", False),
        ("source_type", 1),
        ("item_id", True),
        ("item_id", 42),
        ("guid", "00000000-0000-0000-0000-000000000000"),
        ("guid", "22222222-2222-4222-8222-222222222222"),
        ("metasys_object", "0.81"),
        ("path", "Bus.Meter.NewPath"),
        ("name", "Other point"),
    ],
)
def test_stale_or_wrong_manifest_identity_never_passes(captures, field, value):
    manifest, before, _ = captures
    manifest[0][field] = value
    with pytest.raises(ValueError):
        review_sources(manifest, before)


@pytest.mark.parametrize(
    "case",
    [
        "missing_section",
        "duplicate_item",
        "duplicate_manifest",
        "duplicate_source",
        "duplicate_guid",
        "duplicate_oid",
        "duplicate_path",
        "nested_source",
        "boolean_order",
        "missing_parent_order",
        "boolean_source",
        "missing_source",
        "empty_manifest",
        "too_many",
        "no_capture_zone",
        "inapplicable_type",
    ],
)
def test_missing_ambiguous_and_out_of_scope_input_is_rejected(captures, case):
    manifest, before, _ = captures
    if case == "missing_section":
        del before["incoming_item_references"]
    elif case == "duplicate_item":
        before["items"].append(copy.deepcopy(before["items"][0]))
    elif case == "duplicate_manifest":
        manifest.append(copy.deepcopy(manifest[0]))
    elif case == "duplicate_source":
        before["properties"].append(copy.deepcopy(before["properties"][0]))
    elif case in ["duplicate_guid", "duplicate_oid", "duplicate_path"]:
        key = {
            "duplicate_guid": "GUID",
            "duplicate_oid": "ObjectId",
            "duplicate_path": "PartialReference",
        }[case]
        before["items"][2][key] = before["items"][0][key]
        if case == "duplicate_guid":
            before["items"][2][key] = "{" + before["items"][2][key].upper() + "}"
        if case == "duplicate_oid":
            before["items"][2][key] = "000.000501"
    elif case == "nested_source":
        before["properties"][0]["ParentValueOrder"] = 1
    elif case == "boolean_order":
        before["properties"][0]["ValueOrder"] = True
    elif case == "missing_parent_order":
        del before["properties"][0]["ParentValueOrder"]
    elif case == "boolean_source":
        before["properties"][0]["Value"] = True
    elif case == "missing_source":
        before["properties"].pop(0)
    elif case == "empty_manifest":
        manifest.clear()
    elif case == "too_many":
        manifest *= 65
    elif case == "no_capture_zone":
        before["captured_utc"] = "2026-01-01T00:00:00"
    elif case == "inapplicable_type":
        before["items"][0]["ObjectId"] = manifest[0]["metasys_object"] = "1.501"
    with pytest.raises(ValueError):
        review_sources(manifest, before)


@pytest.mark.parametrize(
    "section",
    [
        "items",
        "properties",
        "incoming_item_references",
        "incoming_text_references",
        "historians",
        "historian_slices",
        "reporting",
    ],
)
def test_any_other_captured_record_change_is_visible_and_not_counted_as_preserved(
    captures, section
):
    manifest, before, after = captures
    after[section][0]["unexpected"] = "Changed"
    result = review_sources(manifest, before, after)
    assert result["all_expected_sources_observed_in_after_capture"]
    assert not result["captured_records_match"]
    assert result["captured_record_differences"][0]["section"] == section


@pytest.mark.parametrize(
    "field", ["GUID", "ObjectId", "PartialReference", "UserName", "parentItemID"]
)
def test_expected_source_changes_do_not_hide_point_identity_or_name_changes(captures, field):
    manifest, before, after = captures
    after["items"][0][field] = "Changed"
    result = review_sources(manifest, before, after)
    assert not result["captured_records_match"] and not result["apply_available"]


def test_partial_or_unapplied_batch_and_unrelated_energy_change_remain_failures(captures):
    manifest, before, after = captures
    not_applied = review_sources(manifest, before, before)
    assert not not_applied["all_expected_sources_observed_in_after_capture"]
    after["properties"][2]["Value"] = "2"
    partial = review_sources(manifest, before, after)
    assert [row["matches_expected"] for row in partial["after_sources"]] == [True, False]
    assert not partial["captured_records_match"]
    after["properties"][2]["Value"] = "1"
    after["properties"][4]["Value"] = "141"
    assert not review_sources(manifest, before, after)["captured_records_match"]


def test_order_independence_preserves_multiplicity_and_reports_source_bookkeeping(captures):
    manifest, before, after = captures
    after["properties"][0].update(EventTimeStamp="2026-01-02", ValueState=3)
    for value in after.values():
        if isinstance(value, list):
            value.reverse()
    result = review_sources(manifest, before, after)
    assert result["captured_records_match"] and len(result["source_bookkeeping_differences"]) == 2
    after["incoming_item_references"].append(after["incoming_item_references"][0])
    result = review_sources(manifest, before, after)
    assert not result["captured_records_match"]


def test_capture_order_and_private_non_overwriting_output(captures, tmp_path):
    manifest, before, after = captures
    after["captured_utc"] = "2025-12-31T23:59:59+00:00"
    with pytest.raises(ValueError, match="predates"):
        review_sources(manifest, before, after)
    report = review_sources(manifest, before)
    path = tmp_path / "report.json"
    write_review(path, report)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == report
    with pytest.raises(FileExistsError):
        write_review(path, {"replacement": True})
    assert json.loads(path.read_text()) == report


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'])
def test_ambiguous_and_non_finite_json_files_are_rejected(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        load_capture(path)


def test_cli_writes_a_report_and_returns_failure_for_uncorrected_sources(
    captures, tmp_path, monkeypatch, capsys
):
    manifest, before, _ = captures
    for name, value in [("manifest", manifest), ("before", before), ("after", before)]:
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    output = tmp_path / "review.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bms-tool",
            "metasys-source-review",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--before",
            str(tmp_path / "before.json"),
            "--after",
            str(tmp_path / "after.json"),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["configuration_writes"] == 0 and not summary["apply_available"]
    assert not summary["all_expected_sources_observed_in_after_capture"]
    assert "11111111-1111-4111-8111-111111111111" not in json.dumps(summary)
    assert not json.loads(output.read_text())["captured_records_match"]


def test_bounded_input_file_read(tmp_path, monkeypatch):
    from bms_tool import metasys_source_preservation as module

    monkeypatch.setattr(module, "MAX_BYTES", 7)
    path = tmp_path / "input.json"
    path.write_bytes(b'{"a":1}')
    assert load_capture(path) == {"a": 1}
    path.write_bytes(b'{"a":12}')
    with pytest.raises(ValueError, match="budget"):
        load_capture(path)


def test_successful_cli_comparison_and_existing_output_refusal(
    captures, tmp_path, monkeypatch, capsys
):
    proposed, before, after = captures
    for name, value in [("manifest", proposed), ("before", before), ("after", after)]:
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    output = tmp_path / "review.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bms-tool",
            "metasys-source-review",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--before",
            str(tmp_path / "before.json"),
            "--after",
            str(tmp_path / "after.json"),
            "--output",
            str(output),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out)["captured_records_match"]
    original = output.read_bytes()
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2 and output.read_bytes() == original
