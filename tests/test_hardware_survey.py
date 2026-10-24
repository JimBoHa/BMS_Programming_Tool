"""Hardware surveys use isolated UDP peers and authored native fragments only."""

import asyncio
import copy
import gzip
import io
import zipfile

import pytest
from bacpypes3.object import AnalogInputObject, BinaryInputObject
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.hardware_survey import (
    ARCHIVE_PROFILE,
    PROFILE,
    HardwareSurvey,
    HardwareSurveyRequest,
    analyze_archive,
    enrich_report,
    model_capacity,
    occupancy,
    relocation_plan,
    validate_report,
)
from bms_tool.storage import Store

from .test_connections import application, free_udp


def native_record(cid, instance, props):
    oid = (cid << 22) | instance
    body = bytearray()
    for pid, value in props:
        raw = pid.to_bytes(max(1, (pid.bit_length() + 7) // 8), "big")
        body.extend(bytes([8 | len(raw)]) + raw + b"\x2e")
        body.extend(value.encode().encode().pduData)
        body.extend(b"\x2f")
    return (
        cid.to_bytes(2, "little")
        + b"\x02\x00\x0e\x1c"
        + oid.to_bytes(4, "big")
        + b"\x0f\x1e"
        + bytes(body)
        + b"\x1f"
    )


def authored_archive():
    root = "8-1"
    module = root + "/307_1.598_2"
    binary = root + "/307_1.598_3"
    return b"\x00\x00MOI\x00" + b"".join(
        [
            native_record(
                194,
                123,
                [
                    (75, ObjectIdentifier(("device", 123))),
                    (70, CharacterString("FX-PCG2611-0")),
                    (2390, CharacterString("Authored controller")),
                    (32527, CharacterString(root)),
                ],
            ),
            native_record(
                598,
                2,
                [
                    (75, ObjectIdentifier((598, 2))),
                    (2858, Unsigned(4)),
                    (3676, CharacterString("FX-PCX3711-0")),
                    (2390, CharacterString("Authored UI module")),
                    (32527, CharacterString(module)),
                ],
            ),
            native_record(
                598,
                3,
                [
                    (75, ObjectIdentifier((598, 3))),
                    (2858, Unsigned(7)),
                    (3676, CharacterString("FX-PCX3721-0")),
                    (32527, CharacterString(binary)),
                ],
            ),
            native_record(
                242,
                55,
                [
                    (75, ObjectIdentifier(("binary-input", 55))),
                    (31, CharacterString("UI IN4")),
                    (519, Unsigned(4)),
                    (2390, CharacterString("Alarm")),
                    (32527, CharacterString(module + ".3_55")),
                ],
            ),
            native_record(
                240,
                56,
                [
                    (75, ObjectIdentifier(("analog-input", 56))),
                    (31, CharacterString("UI IN1")),
                    (519, Unsigned(1)),
                    (518, Enumerated(2)),
                    (32527, CharacterString(root + "/0_56")),
                ],
            ),
        ]
    )


def survey_from_archive(archive):
    return {
        "profile": PROFILE,
        "identity": copy.deepcopy(archive["identity"]),
        "inventory": {"complete": True},
        "inputs_complete": True,
        "inputs": copy.deepcopy(archive["inputs"]),
        "modules": [],
        "errors": [],
    }


def valid_report():
    archive = analyze_archive(authored_archive())
    report = enrich_report(survey_from_archive(archive), archive)
    objects = ["device,123", *[p["object"] for p in report["inputs"]]]
    report["inventory"] = {
        "complete": True,
        "total": len(objects),
        "read": len(objects),
        "objects": objects,
    }
    report["target"] = {
        "address": "127.0.0.1:47808",
        "device": "device,123",
        "router": None,
        "dnet": None,
    }
    return report


def test_report_validation_rederives_claims_and_requires_every_advertised_input():
    report = valid_report()
    report["candidates"] = [{"slot": 4, "status": "candidate"}]
    report["modules"][1]["capacity"] = {"universal_inputs": list(range(1, 100))}
    validated = validate_report(report)
    assert not any(c["sa_mac"] == 4 and c["slot"] == 4 for c in validated["candidates"])
    assert validated["modules"][1]["capacity"]["universal_inputs"] == [1, 2, 3, 4]
    report["inputs"].pop()
    with pytest.raises(ValueError, match="every advertised"):
        validate_report(report)
    report = valid_report()
    report["identity"]["object"] = "device,124"
    with pytest.raises(ValueError, match="match"):
        validate_report(report)
    report = valid_report()
    report["inputs"][0]["slot"] = 3
    with pytest.raises(ValueError, match="conflicts"):
        validate_report(report)


def test_validation_blocks_duplicate_physical_slots_and_unbacked_hidden_inputs():
    report = valid_report()
    duplicate = copy.deepcopy(report["inputs"][0])
    duplicate["object"] = "binary-input,99"
    report["inputs"].append(duplicate)
    with pytest.raises(ValueError, match="same physical terminal"):
        validate_report(report)
    report = valid_report()
    report["inventory"]["objects"].remove("binary-input,55")
    report["inventory"]["total"] -= 1
    assert validate_report(report)["inputs"]
    del report["inputs"][0]["archive_record_sha256"]
    with pytest.raises(ValueError, match="matching native"):
        validate_report(report)


def test_relocation_can_use_documented_local_binary_input():
    report = valid_report()
    plan = relocation_plan(report, "binary-input,55", None, 8)
    assert plan["status"] == "review-required"
    assert plan["destination"]["configured_model"] == "FX-PCG2611-0"


def test_unknown_source_voltage_profile_and_malformed_nested_imports_are_blocked():
    report = valid_report()
    for module in report["modules"]:
        if module.get("sa_mac") == 4:
            module["configured_model"] = "Unknown source model"
    assert relocation_plan(report, "binary-input,55", 7, 16)["status"] == "blocked"
    for field, value in [
        ("archive_comparison", []),
        ("archive_evidence", []),
        ("errors", "bad"),
        ("warnings", {}),
    ]:
        report = valid_report()
        report[field] = value
        with pytest.raises(ValueError):
            validate_report(report)
    report = valid_report()
    report["archive_comparison"]["conflicts"] = "bad"
    with pytest.raises(ValueError):
        validate_report(report)


def test_caf_hardware_uses_explicit_scalars_and_configured_references():
    from bms_tool.caf import NS

    def prop(pid, leaf):
        return f'<property id="{pid}"><data>{leaf}</data></property>'

    xml = (
        f'<objects xmlns="{NS}"><object classid="194" ref="8-1" objectid="1">'
        + prop(75, '<BACoid id="8">123</BACoid>')
        + prop(70, "<string>FX-PCG2611-0</string>")
        + prop(2390, "<string>Authored controller</string>")
        + '</object><object classid="598" ref="8-1/307_1.598_2" objectid="2">'
        + prop(2858, "<unsignedByte>4</unsignedByte>")
        + prop(3676, "<string>FX-PCX3711-0</string>")
        + '</object><object classid="242" ref="8-1/307_1.598_2.3_55" objectid="55">'
        + prop(75, '<BACoid id="3">55</BACoid>')
        + prop(31, "<string>UI IN4</string>")
        + prop(519, "<unsignedShort>4</unsignedShort>")
        + "</object></objects>"
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as container:
        container.writestr("authored.xml", xml)
    archive = analyze_archive(stream.getvalue(), "authored.caf")
    assert archive["archive_format"] == "CAF" and not archive["errors"]
    assert archive["identity"]["object"] == "device,123"
    assert archive["inputs"][0]["host"]["sa_mac"] == 4
    assert archive["inputs"][0]["terminal_type"] == "UI"
    assert not any(p["sa_mac"] == 4 and p["slot"] == 4 for p in archive["candidates"])


def test_native_explicit_sa_address_conflicts_are_not_ignored():
    conflicting = native_record(
        240,
        99,
        [
            (75, ObjectIdentifier(("analog-input", 99))),
            (31, CharacterString("UI IN2")),
            (519, Unsigned(2)),
            (3645, Unsigned(5)),
            (32527, CharacterString("8-1/307_1.598_2.0_99")),
        ],
    )
    archive = analyze_archive(authored_archive() + conflicting)
    assert any("Explicit SA address conflicts" in e["error"] for e in archive["errors"])
    assert not archive["inventory"]["complete"]
    assert all(c["status"] == "unverified" for c in archive["candidates"])


def test_native_models_bindings_capacity_and_binary_use_of_ui():
    archive = analyze_archive(gzip.compress(authored_archive()), "fixture.moi")
    assert archive["recognized"] and not archive["errors"]
    assert archive["profile"] == ARCHIVE_PROFILE
    assert archive["source"]["compression"] == "gzip"
    assert archive["identity"]["object"] == "device,123"
    assert len(archive["source"]["sha256"]) == 64
    alarm = next(p for p in archive["inputs"] if p["object"] == "binary-input,55")
    assert alarm["host"]["sa_mac"] == 4 and alarm["slot"] == 4
    assert alarm["terminal_type"] == "UI"
    assert not any(p["sa_mac"] == 4 and p["slot"] == 4 for p in archive["candidates"])
    assert next(m for m in archive["modules"] if m.get("sa_mac") == 7)["capacity"][
        "binary_inputs"
    ] == list(range(1, 17))
    assert all(
        m.get("installed_model_verified") is False for m in archive["modules"] if m["host"] == "sa"
    )


def test_archive_corroboration_and_review_only_relocation():
    archive = analyze_archive(authored_archive())
    report = enrich_report(survey_from_archive(archive), archive)
    assert report["archive_comparison"]["configured_models_applied"]
    assert len(report["archive_comparison"]["matched"]) == 2
    plan = relocation_plan(report, "binary-input,55", 7, 16)
    assert plan["status"] == "review-required"
    assert plan["freed_input"]["sa_mac"] == 4
    assert plan["freed_input"]["slot"] == 4
    assert plan["controller_writes"] is False and plan["native_program_modified"] is False
    assert "dry-contact" in " ".join(plan["required_checks"])


def test_archive_identity_or_assignment_mismatch_withholds_models():
    archive = analyze_archive(authored_archive())
    live = survey_from_archive(archive)
    live["identity"]["object"] = "device,124"
    wrong = enrich_report(live, archive)
    assert not wrong["archive_comparison"]["configured_models_applied"]
    assert wrong["archive_comparison"]["conflicts"]
    live = survey_from_archive(archive)
    live["inputs"][0]["slot"] = 3
    wrong = enrich_report(live, archive)
    assert not wrong["archive_comparison"]["configured_models_applied"]
    assert any(
        c.get("object") == "binary-input,55" for c in wrong["archive_comparison"]["conflicts"]
    )


def test_archive_only_inputs_remain_occupied_on_enrichment():
    archive = analyze_archive(authored_archive())
    live = survey_from_archive(archive)
    live["inputs"] = live["inputs"][1:]
    enriched = enrich_report(live, archive)
    assert enriched["archive_comparison"]["archive_only_inputs"] == ["binary-input,55"]
    assert len(enriched["inputs"]) == 2
    assert not any(c["sa_mac"] == 4 and c["slot"] == 4 for c in enriched["candidates"])


def test_untrusted_capacity_unknown_model_and_partial_do_not_become_spares():
    report = {
        "profile": PROFILE,
        "identity": {},
        "inventory": {"complete": True},
        "inputs_complete": True,
        "inputs": [],
        "modules": [
            {
                "host": "sa",
                "sa_mac": 8,
                "configured_model": "Unknown",
                "capacity": {"universal_inputs": [1, 2], "binary_inputs": [3]},
            }
        ],
    }
    result = occupancy(report)
    assert not result["candidates"] and result["modules"][0]["capacity"] is None
    report["modules"][0]["configured_model"] = "FX-PCX3711-0"
    report["inputs_complete"] = False
    assert all(c["status"] == "unverified" for c in occupancy(report)["candidates"])
    assert model_capacity("FX-PCX3711-99") is None


def test_relocation_rejects_occupied_nonbinary_and_incomplete_destinations():
    archive = analyze_archive(authored_archive())
    report = enrich_report(survey_from_archive(archive), archive)
    assert relocation_plan(report, "analog-input,56", 7, 16)["status"] == "blocked"
    assert relocation_plan(report, "binary-input,55", 4, 1)["status"] == "blocked"
    report["inputs"].append(
        {
            "object": "binary-input,88",
            "host": {"kind": "sa", "sa_mac": 7},
            "slot": 16,
            "terminal_type": "BI",
        }
    )
    assert "already" in " ".join(relocation_plan(report, "binary-input,55", 7, 16)["reasons"])
    report["inputs"].pop()
    report["inputs_complete"] = False
    assert relocation_plan(report, "binary-input,55", 7, 16)["status"] == "blocked"
    with pytest.raises(ValueError):
        relocation_plan(report, "binary-input,55", True, 16)


def test_archive_bounds_framing_and_compression_failures():
    with pytest.raises(ValueError):
        analyze_archive(b"")
    with pytest.raises(ValueError):
        analyze_archive(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        analyze_archive(gzip.compress(b"x" * (8 * 1024 * 1024 + 1)))
    with pytest.raises(ValueError):
        analyze_archive(gzip.compress(authored_archive()) + b"trailing")
    with pytest.raises(ValueError):
        analyze_archive(gzip.compress(authored_archive())[:-4])
    assert not analyze_archive(b"not a native file")["recognized"]
    malformed = analyze_archive(authored_archive()[:-1])
    assert malformed["errors"] and not malformed["inventory"]["complete"]
    duplicate = analyze_archive(
        authored_archive()
        + native_record(
            242, 55, [(75, ObjectIdentifier(("binary-input", 55))), (31, CharacterString("UI IN4"))]
        )
    )
    assert any("Duplicate native" in e["error"] for e in duplicate["errors"])


def test_exact_destination_and_time_limits():
    for extra in (
        {"router": "127.0.0.1"},
        {"max_objects": 4097},
        {"max_inputs": 1025},
        {"timeout_seconds": float("nan")},
        {"property_timeout": 3},
        {"device": "device,4194303"},
    ):
        with pytest.raises(ValueError):
            HardwareSurveyRequest.model_validate(
                {"address": "127.0.0.1", "device": "device,123", **extra}
            )
    with pytest.raises(ValueError):
        HardwareSurveyRequest(
            address="3001:255", device="device,123", router="127.0.0.1", dnet=3001
        )


@pytest.fixture
async def hardware_link(tmp_path):
    port = free_udp()
    server = application(port, 4190123)
    server.device_object.modelName = "Authored unknown model"
    server.add_object(
        AnalogInputObject(
            objectIdentifier=("analog-input", 31),
            objectName="Temperature",
            description="Public loopback authored AI",
            deviceType="UI IN1",
            presentValue=72.5,
            units="degrees-fahrenheit",
            reliability="no-fault-detected",
            statusFlags=[0, 0, 0, 0],
            outOfService=False,
        )
    )
    server.add_object(
        BinaryInputObject(
            objectIdentifier=("binary-input", 32),
            objectName="Alarm",
            description="Public loopback authored BI",
            deviceType="UI IN4",
            presentValue="inactive",
            reliability="no-fault-detected",
            statusFlags=[0, 0, 0, 0],
            outOfService=False,
        )
    )
    store = Store(tmp_path)
    client = Bacnet(store)
    await client.connect(f"127.0.0.1:{free_udp()}", instance=4190124)
    try:
        yield (
            server,
            client,
            HardwareSurvey(client, store),
            {
                "address": f"127.0.0.1:{port}",
                "device": "device,4190123",
                "timeout_seconds": 10,
                "property_timeout": 0.15,
            },
        )
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_actual_udp_survey_live_quality_and_retained_progress(hardware_link):
    server, client, survey, options = hardware_link
    calls, snapshots = [], []
    original_rp = server.do_ReadPropertyRequest
    original_rpm = server.do_ReadPropertyMultipleRequest

    async def tracked_rp(request):
        calls.append(type(request).__name__)
        await original_rp(request)

    async def tracked_rpm(request):
        calls.append(type(request).__name__)
        await original_rpm(request)

    server.do_ReadPropertyRequest = tracked_rp
    server.do_ReadPropertyMultipleRequest = tracked_rpm

    def progress(report):
        snapshots.append(report)
        report["identity"]["name"] = "callback cannot mutate survey"

    result = await survey.survey(options, progress=progress)
    assert result["status"] == "complete", result
    assert result["inventory"]["complete"] and len(result["inputs"]) == 2
    assert result["identity"]["name"] != "callback cannot mutate survey"
    ai = next(p for p in result["inputs"] if p["object"] == "analog-input,31")
    assert ai["present_value"] == 72.5 and ai["out_of_service"] is False
    assert ai["reliability"] == 0 and ai["slot"] == 1
    assert ai["host"]["kind"] == "unknown"  # no vendor-specific host guess
    assert not result["candidates"]
    assert calls and set(calls) <= {"ReadPropertyRequest", "ReadPropertyMultipleRequest"}
    assert not client.commands and not client.require().asap.clientTransactions
    assert len(snapshots) > 2


@pytest.mark.asyncio
async def test_partial_object_limit_and_wrong_identity_do_not_guess(hardware_link):
    _, client, survey, options = hardware_link
    partial = await survey.survey({**options, "max_objects": 1})
    assert partial["status"] == "partial" and not partial["inventory"]["complete"]
    wrong = await survey.survey({**options, "device": "device,4190122"})
    assert wrong["status"] == "error"
    assert not wrong["inputs"] and not wrong["inventory"]["objects"]
    assert not client.require().asap.clientTransactions


@pytest.mark.asyncio
async def test_timeout_and_cancellation_retire_owned_transactions(hardware_link):
    server, client, survey, options = hardware_link
    entered = asyncio.Event()

    async def hold(request):
        entered.set()
        # No response and no independent blocking task; simulate an absent peer.

    server.do_ReadPropertyMultipleRequest = hold
    result = await survey.survey({**options, "timeout_seconds": 0.1})
    assert result["status"] == "partial" and result["errors"]
    assert not client.require().asap.clientTransactions
    snapshots = []
    task = asyncio.create_task(survey.survey(options, progress=snapshots.append))
    await entered.wait()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert snapshots[-1]["status"] == "cancelled"
    assert not client.require().asap.clientTransactions
    assert not client.commands
