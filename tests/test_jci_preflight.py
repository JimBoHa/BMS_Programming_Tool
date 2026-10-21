"""Authored CAF metadata and declared inventories; no building programs or device I/O."""

import hashlib
import json

import pytest
from bms_tool.caf import CafArchive
from bms_tool.jci_hardware import JciHardwareDefinition
from bms_tool.jci_preflight import PreflightRequest, inventory_template, preflight

from tests.test_formats_caf import make_caf
from tests.test_jci_hardware import definition


def inventory(**updates):
    result = {
        "schema_version": 1,
        "toolchain": {
            "product": "CCT",
            "version": "13.0",
            "installed": True,
            "license_status": "licensed",
            "platform": "windows",
            "sql_available": True,
            "supported_models": ["MS-VMA1630-0"],
            "supported_application_versions": ["10.2"],
            "supported_firmware_versions": ["6.2"],
            "evidence": "Authored test declaration, not a compatibility table",
        },
        "package_inventory_complete": True,
        "packages": [
            {
                "name": "Authored legacy package",
                "version": "test-1",
                "installed": True,
                "license_status": "licensed",
                "supported_models": ["MS-VMA1630-0"],
                "supported_application_versions": ["10.2"],
                "supported_firmware_versions": ["6.2"],
                "evidence": "Authored package declaration",
            }
        ],
    }
    result.update(updates)
    return result


def application(*, model="MS-VMA1630-0", firmware="6.2", app_version="10.2"):
    xml = CafArchive(make_caf()).xml
    xml = xml.replace(b"MS-VMA1630-0", model.encode()).replace(
        b">10.2<", f">{app_version}<".encode()
    )
    xml = xml.replace(
        b"</object>",
        f'<property id="44"><data><string>{firmware}</string></data></property></object>'.encode(),
    )
    return CafArchive(make_caf(xml))


def run(caf=None, manifest=None, **kwargs):
    return preflight(
        caf or application(),
        PreflightRequest(
            target_model="MS-VMA1630-0",
            target_firmware="6.2",
            inventory_text=json.dumps(manifest if manifest is not None else inventory()),
            **kwargs,
        ),
    )


def checks(report):
    return {row["id"]: row for row in report["checks"]}


def test_declared_matches_keep_independent_acceptance_unknown_and_exact_source_hashes():
    caf = application()
    text = json.dumps(inventory(), indent=3) + "\n"
    report = preflight(
        caf,
        PreflightRequest(target_model="MS-VMA1630-0", target_firmware="6.2", inventory_text=text),
    )
    by_id = checks(report)
    assert report["status"] == "needs-evidence" and report["can_deploy"] is False
    assert by_id["target.model"]["status"] == "match"
    assert by_id["target.firmware"]["status"] == "match"
    assert by_id["tool.application"]["status"] == "match"
    assert by_id["package.0.application"]["status"] == "match"
    assert by_id["native.integration"]["status"] == "unknown"
    assert by_id["native.acceptance"]["status"] == "unknown"
    assert report["source"]["caf_sha256"] == hashlib.sha256(caf.original).hexdigest()
    assert report["source"]["caf_xml_sha256"] == hashlib.sha256(caf.xml).hexdigest()
    assert report["source"]["inventory_utf8_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["source"]["inventory_text"] == text
    assert caf.patch([])[0] == caf.original


def test_release_mode_is_never_used_as_firmware_or_compared_to_tool_number():
    report = run(application(firmware=""), transport="btcvt")
    assert report["selected_application"]["application_version"] == "10.2"
    assert checks(report)["target.firmware"]["status"] == "unknown"
    # Uses declared live firmware 6.2, not CAF application 10.2.
    assert checks(report)["btcvt.firmware"]["status"] == "match"
    assert checks(report)["tool.application"]["status"] == "match"
    assert checks(report)["tool.identity"]["status"] == "match"


def test_no_unique_application_candidate_requires_selection_and_ignores_sensor_models():
    caf = application()
    first = caf.xml[caf.xml.index(b"<object ") : caf.xml.index(b"</object>") + len(b"</object>")]
    other = first.replace(b'ref="8-1"', b'ref="8-2"').replace(b"MS-VMA1630-0", b"FX-PCV1630-0")
    sensor = b'<object classid="627" ref="sensor"><property id="70"><data><string>Other</string></data></property></object>'
    multiple = CafArchive(make_caf(caf.xml.replace(b"</objects>", other + sensor + b"</objects>")))
    report = run(multiple)
    assert len(report["application_candidates"]) == 2
    assert report["selected_application"] is None
    assert checks(report)["target.model"]["status"] == "unknown"
    selected = run(multiple, application_object_ref="8-2")
    assert checks(selected)["target.model"]["status"] == "blocked"
    with pytest.raises(ValueError, match="not an inspected"):
        run(multiple, application_object_ref="sensor")


def test_identity_and_package_support_mismatches_block_without_family_inference():
    declared = inventory()
    declared["toolchain"]["supported_models"] = ["MS-VMA1630"]
    declared["packages"][0]["supported_firmware_versions"] = ["7.0"]
    report = run(application(model="FX-PCV1630-0", firmware="7.0"), declared)
    by_id = checks(report)
    assert report["status"] == "blocked"
    assert all(
        by_id[key]["status"] == "blocked"
        for key in (
            "target.model",
            "target.firmware",
            "tool.model",
            "package.0.firmware",
        )
    )


def test_missing_installation_license_and_empty_support_evidence_are_not_silently_ready():
    declared = inventory()
    declared["toolchain"].update(installed=False, license_status="missing", evidence="")
    declared["packages"][0].update(installed=None, supported_models=[], license_status="unknown")
    by_id = checks(run(manifest=declared))
    assert by_id["tool.installed"]["status"] == "blocked"
    assert by_id["tool.license"]["status"] == "blocked"
    assert by_id["tool.model"]["status"] == "unknown"
    assert by_id["package.0.installed"]["status"] == "unknown"
    assert by_id["package.0.model"]["status"] == "unknown"
    assert by_id["package.0.license"]["status"] == "unknown"
    empty = preflight(application(), PreflightRequest())
    assert checks(empty)["packages.required"]["status"] == "unknown"


@pytest.mark.parametrize(
    "tool_version,firmware,tool_result,firmware_result",
    [
        ("14.0", "6.2", "blocked", "match"),
        ("13.0", "7.0", "match", "blocked"),
        ("18.0.2.6", "7.1", "blocked", "blocked"),
        ("unverified build", "unknown", "unknown", "unknown"),
        ("13.0", "6.3", "match", "unknown"),
        ("13.0", "6.2.6", "match", "match"),
    ],
)
def test_documented_btcvt_restrictions_have_a_release_qualified_source(
    tool_version, firmware, tool_result, firmware_result
):
    declared = inventory()
    declared["toolchain"]["version"] = tool_version
    report = preflight(
        application(),
        PreflightRequest(
            target_firmware=firmware, transport="btcvt", inventory_text=json.dumps(declared)
        ),
    )
    by_id = checks(report)
    assert by_id["btcvt.tool"]["status"] == tool_result
    assert by_id["btcvt.firmware"]["status"] == firmware_result
    assert "14.1" in by_id["btcvt.tool"]["evidence"][0]["title"]
    assert "btcvt.tool" not in checks(run(transport="bacnet-ip"))


def test_hardware_definition_expected_hash_is_provenance_not_a_model_mapping():
    hardware = JciHardwareDefinition(definition())
    declared = inventory(hardware_definition_sha256=hardware.hash.upper())
    request = PreflightRequest(inventory_text=json.dumps(declared), hardware_sha256=hardware.hash)
    report = preflight(application(), request, hardware)
    assert checks(report)["hardware.definition"]["status"] == "match"
    assert report["source"]["hardware"]["revision"] == 0
    assert checks(report)["target.model"]["status"] == "unknown"
    declared["hardware_definition_sha256"] = "0" * 64
    report = preflight(
        application(), PreflightRequest(inventory_text=json.dumps(declared)), hardware
    )
    assert checks(report)["hardware.definition"]["status"] == "blocked"


def test_cct_bluetooth_tool_rule_does_not_invent_pct_version_support():
    declared = inventory()
    declared["toolchain"].update(product="PCT", version="10.3")
    report = run(manifest=declared, transport="btcvt")
    assert checks(report)["btcvt.tool"]["status"] == "unknown"
    assert "PCT compatibility is not established" in checks(report)["btcvt.tool"]["detail"]


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        "null",
        "{bad",
        '{"packages": [], "packages": []}',
        '{"toolchain":{"installed":"true"}}',
        '{"native_download_verified":true}',
        '{"toolchain":{"installed":NaN}}',
        '{"schema_version":2}',
        '{"packages":[{"name":" ","installed":true}]}',
        '{"packages":[{"name":"Same"},{"name":"same"}]}',
    ],
)
def test_ambiguous_untyped_or_unknown_inventory_inputs_are_rejected(text):
    with pytest.raises(ValueError):
        preflight(application(), PreflightRequest(inventory_text=text))


def test_template_stays_unknown_and_bom_is_retained_in_inventory_hash():
    text = "\ufeff" + json.dumps(inventory_template())
    report = preflight(application(), PreflightRequest(inventory_text=text))
    assert report["source"]["inventory_text"].startswith("\ufeff")
    assert checks(report)["tool.installed"]["status"] == "unknown"
    assert checks(report)["package.0.installed"]["status"] == "unknown"


def test_inventory_limit_applies_to_utf8_bytes_as_well_as_character_count():
    text = json.dumps({"toolchain": {"evidence": "é" * 140000}}, ensure_ascii=False)
    request = PreflightRequest(inventory_text=text)
    with pytest.raises(ValueError, match="256 KiB"):
        preflight(application(), request)


def test_attributed_or_oversized_identity_is_not_guessed_and_reports_remain_bounded():
    caf = application()
    changed = caf.xml.replace(b"<string>MS-VMA1630-0", b'<string qualified="unknown">MS-VMA1630-0')
    report = run(CafArchive(make_caf(changed)))
    assert checks(report)["target.model"]["status"] == "unknown"
    oversized = caf.xml.replace(b"MS-VMA1630-0", b"X" * 10000)
    report = run(CafArchive(make_caf(oversized)))
    assert checks(report)["target.model"]["status"] == "unknown"
    evidence = next(
        row for row in report["application_candidates"][0]["evidence"] if row["property_id"] == "70"
    )
    assert evidence["scalar"]["oversize"] is True
    assert evidence["scalar"]["text_sha256"] == hashlib.sha256(b"X" * 10000).hexdigest()
    assert len(json.dumps(report)) < 25000


def test_unbounded_target_inventory_and_reference_lengths_are_rejected():
    caf = application()
    first = caf.xml[caf.xml.index(b"<object ") : caf.xml.index(b"</object>") + len(b"</object>")]
    many = b"".join(
        first.replace(b'ref="8-1"', f'ref="8-{number}"'.encode()) for number in range(257)
    )
    with pytest.raises(ValueError, match="256 application-target"):
        run(CafArchive(make_caf(caf.xml.replace(first, many))))
    with pytest.raises(ValueError, match="references must be"):
        run(CafArchive(make_caf(caf.xml.replace(b'ref="8-1"', b'ref="' + b"R" * 257 + b'"'))))
