"""Documented physical VAV terminals, using authored native records only.

FX installation 24-10143-357 Rev H, pp5/6/15/27 and Metasys installation
24-10143-217 Rev K, pp2/8/19 distinguish three external UIs from integral DPT.
"""

import copy

import httpx
import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.hardware_survey import (
    analyze_archive,
    enrich_report,
    model_capacity,
    occupancy,
    relocation_plan,
    validate_report,
)
from bms_tool.hardware_workbench import canonical

from .test_hardware_survey import hardware_link as hardware_link
from .test_hardware_survey import native_record, survey_from_archive

MODELS = ["FX-PCV1615-0", "FX-PCV1630-0", "MS-VMA1615-0", "MS-VMA1630-0"]


def vav_archive(model, *, differential_pressure=False):
    records = [
        native_record(
            194,
            123,
            [
                (75, ObjectIdentifier("device,123")),
                (70, CharacterString(model)),
                (2390, CharacterString("Authored VAV controller")),
                (32527, CharacterString("8-1")),
            ],
        )
    ]
    points = [
        (240, "analog-input,51", 1, "UI IN1", "Authored temperature"),
        (242, "binary-input,52", 2, "UI IN2", "Authored contact"),
    ]
    if differential_pressure:
        # Do not infer internal sensor mapping from instance 4 or its label.
        points.append((240, "analog-input,4", 4, "AI4", "Authored internal pressure"))
    for cid, obj, slot, kind, name in points:
        records.append(
            native_record(
                cid,
                int(obj.split(",")[1]),
                [
                    (75, ObjectIdentifier(obj)),
                    (31, CharacterString(kind)),
                    (519, Unsigned(slot)),
                    (2390, CharacterString(name)),
                    (32527, CharacterString("8-1/0_" + obj.split(",")[1])),
                ],
            )
        )
    return analyze_archive(b"\0\0MOI\0" + b"".join(records), "authored-vav.moi")


def vav_report(model, *, native_only=False, differential_pressure=False):
    archive = vav_archive(model, differential_pressure=differential_pressure)
    report = survey_from_archive(archive)
    if native_only:
        report["inputs"] = [p for p in report["inputs"] if p["object"] != "binary-input,52"]
    objects = ["device,123", *[p["object"] for p in report["inputs"]]]
    report["inventory"].update(total=len(objects), read=len(objects), objects=objects)
    report["target"] = {
        "address": "127.0.0.1:47808",
        "device": "device,123",
        "router": None,
        "dnet": None,
    }
    return report, archive


@pytest.mark.parametrize("model", MODELS)
def test_documented_vav_physical_capacity_and_binary_on_ui_occupancy(model):
    archive = vav_archive(model)
    module = archive["modules"][0]
    capacity = module["capacity"]
    assert capacity["universal_inputs"] == [1, 2, 3]
    assert capacity["binary_inputs"] == []
    assert capacity["voltage_input_range"] == "0–10 VDC"
    assert module["occupied_physical_slots"] == [1, 2]
    assert module["model_evidence"] == "Native configured controller model"
    assert not module["installed_model_verified"]
    assert [p["slot"] for p in archive["candidates"]] == [3]
    assert archive["candidates"][0]["status"] == "candidate"
    source = capacity["source_document"]
    assert source["document_number"] == ("24-10143-357" if model.startswith("FX") else "24-10143-217")
    assert source["revision"] == ("H" if model.startswith("FX") else "K")
    assert len(source["sha256"]) == 64
    assert archive["candidates"][0]["capacity_source"] == source
    assert capacity["onboard_sensors"][0]["physical_terminal"] is None
    assert capacity["onboard_sensors"][0]["spare_eligible"] is False
    # There is no dedicated BI destination on the base VAV controller.
    assert relocation_plan(archive, "binary-input,52", None, 3)["status"] == "blocked"


@pytest.mark.parametrize("model", MODELS)
def test_ai4_and_ambiguous_pressure_metadata_never_create_external_spares(model):
    report, archive = vav_report(model, differential_pressure=True)
    result = validate_report(enrich_report(report, archive))
    module = result["modules"][0]
    assert module["unmapped_input_objects"] == ["analog-input,4"]
    assert module["occupied_physical_slots"] == [1, 2]
    assert [c["slot"] for c in result["candidates"]] == [3]
    assert result["candidates"][0]["status"] == "unverified"
    assert any(p["object"] == "analog-input,4" for p in result["inputs"])
    # Even an imported claim that AI4 is a universal terminal cannot add IN4.
    report["inputs"][-1].update(device_type="UI IN4", terminal_type="UI")
    result = occupancy(report)
    assert all(c["slot"] <= 3 for c in result["candidates"])
    assert all(c["status"] == "unverified" for c in result["candidates"])


def test_native_only_assignments_and_model_corroboration_keep_source_identity():
    report, archive = vav_report("FX-PCV1630-0", native_only=True)
    result = validate_report(enrich_report(report, archive))
    assert result["archive_comparison"]["archive_only_inputs"] == ["binary-input,52"]
    assert [c["slot"] for c in result["candidates"]] == [3]
    assert "Survey controller model" in result["modules"][0]["model_evidence"]
    assert result["modules"][0]["capacity"]["source_document"]["revision"] == "H"
    mismatched = copy.deepcopy(report)
    mismatched["identity"]["model"] = "MS-VMA1630-0"
    result = enrich_report(mismatched, archive)
    assert not result["archive_comparison"]["configured_models_applied"]
    assert result["archive_comparison"]["conflicts"]
    assert all(c["status"] == "unverified" for c in result["candidates"])
    # The live/supplied survey model keeps its own manual even after a conflict.
    assert result["modules"][0]["capacity"]["source_document"]["revision"] == "K"
    mismatched["modules"] = copy.deepcopy(archive["modules"])
    with pytest.raises(ValueError, match="conflicts with controller identity"):
        validate_report(mismatched)


def test_unlisted_variants_are_unknown_and_capacity_results_do_not_share_mutable_metadata():
    for name in ["FX-PCV1630", "FX-PCV1630-0G", "MS-VMA1615-0U", "MS-VMA1630-1", "MS-VMA1630-99"]:
        assert model_capacity(name) is None
        result = occupancy({"identity": {"model": name}, "inputs": []})
        assert result["modules"][0]["capacity"] is None and not result["candidates"]
    first = model_capacity("MS-VMA1630-0")
    first["universal_inputs"].append(4)
    first["source_document"]["pdf_pages"].append(999)
    next_capacity = model_capacity("MS-VMA1630-0")
    assert next_capacity["universal_inputs"] == [1, 2, 3]
    assert 999 not in next_capacity["source_document"]["pdf_pages"]


async def test_browser_api_import_recomputes_exact_capacity_provenance_and_exports(tmp_path):
    app = create_app(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            token = (await client.get("/api/session")).json()["token"]
            report, archive = vav_report("MS-VMA1615-0", native_only=True)
            report = enrich_report(report, archive)
            report["modules"][0]["capacity"] = {"universal_inputs": [1, 2, 3, 4]}
            report["modules"][0]["model_evidence"] = "Installed hardware verified"
            response = await client.post(
                "/api/bacnet/hardware/import-report",
                files={"file": ("authored-vav.json", canonical(report))},
                headers={"X-Studio-Token": token},
            )
            assert response.status_code == 200, response.text
            imported = response.json()
            assert imported["imported"] and not imported["native_apply_supported"]
            assert imported["modules"][0]["capacity"]["universal_inputs"] == [1, 2, 3]
            assert "supplied evidence" in imported["modules"][0]["model_evidence"]
            exported = await client.get(
                "/api/bacnet/hardware/reports/" + imported["id"] + "/export"
            )
            assert exported.json()["candidates"][0]["capacity_source"]["revision"] == "K"
            assert app.state.bacnet.app is None


async def test_actual_udp_model_identity_selects_current_exact_profile(hardware_link):
    server, client, survey, options = hardware_link
    server.device_object.modelName = "MS-VMA1630-0"
    server.get_object_id(ObjectIdentifier("binary-input,32")).deviceType = "UI IN2"
    result = await survey.survey(options)
    assert result["status"] == "complete"
    module = result["modules"][0]
    assert module["configured_model"] == "MS-VMA1630-0"
    assert module["capacity"]["universal_inputs"] == [1, 2, 3]
    assert module["capacity"]["source_document"]["revision"] == "K"
    # This peer does not expose JCI SA-host metadata: capacity is documented,
    # but it must not upgrade unknown assignment hosts into verified spares.
    assert all(p["status"] == "unverified" for p in result["candidates"])
    assert not client.commands
    server.device_object.modelName = "MS-VMA1630-99"
    changed = await survey.survey(options)
    assert changed["modules"][0]["capacity"] is None
    assert not changed["candidates"]
