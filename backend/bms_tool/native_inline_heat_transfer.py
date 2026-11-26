"""Source-bound commissioning for a local, cold-airflow inline valve interlock."""

import copy
import math
from datetime import UTC, datetime, timedelta

from bacpypes3.object import Object
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from pydantic import Field, StrictBool

from .application_preservation import runtime_parameter_changes
from .application_store import PROFILE as APPLICATION_PROFILE
from .application_store import utc
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_inline_heat import GATE_LABEL, compile_permissive
from .native_parameter_qualification import qualify_parameter_additions
from .native_snapshot_restore import fresh_current
from .property_evidence import PropertyEvidence, ReadBudget

PROFILE = "native-inline-airflow-transfer/1"


class InlineEdit(StrictModel):
    diagram_ref: str = Field(min_length=1, max_length=512)
    pressure_ref: str = Field(min_length=1, max_length=512)
    flow_ref: str = Field(min_length=1, max_length=512)
    enable_ref: str = Field(min_length=1, max_length=512)
    passthrough_ref: str = Field(min_length=1, max_length=512)
    valve_ref: str = Field(min_length=1, max_length=512)
    threshold_cfm: float = Field(gt=0, le=100000, strict=True)
    first_instance: int = Field(ge=1, le=4194302, strict=True)


class InlineReview(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    edit: InlineEdit


class InlineApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inline_heat_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


def compile_inline(files, edit):
    options = InlineEdit.model_validate(edit)
    source, merge = ParameterApplication(files[3], files[11], files[12]).compile()
    qualification = qualify_parameter_additions(source, merge)
    payload, report = compile_permissive(source, source_sha256=sha(source), **options.model_dump())
    result = MoiIdentity(payload)
    rd = result.reader
    physical = [r for r in result.records if r["class_id"] in (239, 241, 251)]
    if len(physical) != 2 or set(rd.scalar(r, 2390) for r in physical) != {"HTG-O", "DPR-O"}:
        raise ValueError(
            "Field review requires an inline box with only a proportional heat valve and integral damper."
        )
    (damper,) = [record for record in physical if rd.scalar(record, 2390) == "DPR-O"]
    if (
        damper["class_id"] != 251
        or rd.scalar(damper, 31) != "BO1-Int,BO2-Int"
        or (rd.scalar(damper, 990), rd.scalar(damper, 991)) != (6, 7)
    ):
        raise ValueError("The other output must be the verified integral damper actuator pair.")
    head = rd.records[options.pressure_ref]
    pressure = str(ObjectIdentifier((0, ObjectIdentifier(rd.scalar(head, 75))[1])))
    (flow_alias,) = [
        rd.scalar(r, 75)
        for r in result.records
        if (rd.scalar(r, 32527) or "").rpartition(".")[0] == options.flow_ref
        and rd.scalar(r, 3365) == 3505
    ]
    added = result.records[-report["new_records"] :]
    report.update(
        added_objects=[rd.scalar(r, 75) for r in added],
        pressure=pressure,
        flow=flow_alias,
        parameter_transfer_qualification=qualification,
    )
    return payload, report


async def operating_state(native, session, device, identity, compiled):
    if identity["model-name"] != "M4-CVM03050-0" or identity["firmware-revision"] != "10.0.0.2125":
        raise ValueError(
            "This field profile requires a separately qualified controller and firmware."
        )
    root = str(await native.input_atomic(session, device, 32527, CharacterString))
    selector = "multi-state-value,1000"
    if (
        str(await native.path._read(session, selector, "object-name"))
        != root + "/Preloaded App Loader.App Selector"
        or int(await native.path._read(session, selector, "present-value")) != 1
        or str(await native.path._read(session, selector, "state-text", 1)) != "Custom Application"
        or int(await native.path._read(session, device, "system-status")) != 0
    ):
        raise ValueError("The reviewed custom application bank must be active and operational.")
    state = {}
    for key in ("valve", "pressure", "flow"):
        obj = compiled[key]
        if (
            bool(await native.input_atomic(session, obj, 81, Boolean))
            or int(await native.input_atomic(session, obj, 103, Enumerated)) != 0
        ):
            raise ValueError(f"The {key} has unreliable or out-of-service commissioning evidence.")
        state[key] = float(await native.input_atomic(session, obj, 85, Real))
        if not math.isfinite(state[key]):
            raise ValueError(f"The {key} has a non-finite field value.")
    valve = compiled["valve"]
    terminal = int(await native.input_atomic(session, valve, 990, Unsigned))
    if (
        terminal != compiled["valve_terminal"]
        or int(await native.input_atomic(session, valve, 117, Enumerated)) != 98
    ):
        raise ValueError("The actual heating output terminal or engineering units changed.")
    priorities = list(await native.path._read(session, valve, "priority-array"))
    if len(priorities) != 16 or any(
        getattr(slot, "_choice", None) != "null" for slot in priorities[:15]
    ):
        raise ValueError(
            "The heating valve has an engineering command. Resolve its ownership before commissioning."
        )
    return state


async def live_review(native, session, request, identity, compiled):
    observed = await operating_state(native, session, request.device, identity, compiled)
    if observed["flow"] >= compiled["threshold_cfm"]:
        raise ValueError(
            "This initial commissioning profile requires independently observable flow below the proof threshold."
        )
    floor = int(await native.input_atomic(session, request.device, 787, Unsigned))
    points = compiled["added_objects"]
    if len(set(points)) != len(points) or min(ObjectIdentifier(o)[1] for o in points) < floor:
        raise ValueError(
            "The new logic would overlap the live object's allocator. Review a new range."
        )
    reader = PropertyEvidence(native.path)
    budget = ReadBudget(max_requests=len(points), max_bytes=256 * 1024)
    for point in points:
        _, row = await reader.read(session, budget, point, 75, Object, timeout=native.files.timeout)
        e = row.get("native_error", {})
        if (
            row["status"] != "native_error"
            or e.get("errorClass", {}).get("value") != 1
            or e.get("errorCode", {}).get("value") != 31
            or not row.get("transport_evidence")
        ):
            raise ValueError(
                f"Cannot prove that proposed logic object {point} is absent on this station."
            )
    return {"points_absent": len(points), "allocator": floor, "operating_state": observed}


async def installed_state(native, session, intent, files):
    _, expected = compile_inline(native.storage.load(intent["backup_id"])[1], intent["inline_edit"])
    if expected != intent["compilation"]:
        raise ValueError("The native logic receipt differs from its original backup.")
    app = MoiIdentity(files[3])
    rows = app.reader.records
    readings = await operating_state(
        native, session, intent["identity"]["device"], intent["identity"], expected
    )
    permitted = app.reader.scalar(rows[expected["blocks"][GATE_LABEL]], 75)
    proof = app.reader.scalar(
        rows[expected["blocks"]["Measured airflow above proof threshold"]], 75
    )
    final = app.reader.scalar(rows[expected["blocks"]["Proven airflow valve command"]], 75)
    for key, obj, T in (
        ("permission", permitted, Boolean),
        ("air_proven", proof, Boolean),
        ("output_command", final, Real),
    ):
        if int(await native.input_atomic(session, obj, 103, Enumerated)) != 0:
            raise ValueError("A newly installed block returned unreliable runtime status.")
        v = await native.input_atomic(session, obj, 85, T)
        readings[key] = bool(v) if T is Boolean else float(v)
    if (
        readings["flow"] >= expected["threshold_cfm"]
        or readings["permission"]
        or readings["air_proven"]
        or abs(readings["valve"]) > 0.01
        or abs(readings["output_command"]) > 0.01
    ):
        raise ValueError(
            "The controller has not demonstrated the automatic valve closed below the proof threshold. Retain the receipt and inspect current values."
        )
    return readings


def verify_inline(before, after, edit):
    original, report = compile_inline(before, edit)
    actual = MoiIdentity(after[3])
    if actual.data != MoiIdentity(original).data:
        raise ValueError("The installed native application differs from the reviewed interlock.")
    params = ParameterApplication(after[3], after[11], after[12])
    matched, counters, calculated = runtime_parameter_changes(actual, params)
    return {
        "identity_unchanged": True,
        "native_graph_verified": True,
        "saved_parameters_verified": matched["matched_parameters"],
        "new_records": report["new_records"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
    }


def compile_fresh(native, body, files):
    _, reviewed = native.storage.load(body["capture_id"])
    fresh_current(reviewed, files)
    return compile_inline(files, body["inline_edit"])


async def preview(native, options):
    from .native_applications import PLAN_SECONDS, backup_effects

    async with native.operation(options.operation_id, "inline-heat-review"):
        native.available(options)
        capture, files = native.check_capture(options)
        if capture["evidence_sha256"] != options.snapshot_sha256:
            raise ValueError("Reopen the retained backup from the selected station.")
        out, compilation = compile_inline(files, options.edit)
        config, app = copy.deepcopy(native.bacnet.config), native.bacnet.require()
        async with native.path._path(options) as session:
            PropertyEvidence.pin(session, options.router)
            identity, _ = await native.identity(session, options.device)
            if identity != capture["identity"]:
                raise ValueError("The actual controller identity changed after backup.")
            guard = await live_review(native, session, options, identity, compilation)
        instance = ObjectIdentifier(options.device)[1]
        body = dict(
            profile=APPLICATION_PROFILE,
            operation_profile=PROFILE,
            target=native.target(options),
            identity=identity,
            old_instance=instance,
            new_instance=instance,
            change_kind="inline-heat",
            old_name=identity["object-name"],
            new_name=identity["object-name"],
            capture_id=capture["id"],
            snapshot_sha256=capture["evidence_sha256"],
            application_sha256=sha(files[3]),
            static_parameters_sha256=sha(files[11]),
            inline_edit=options.edit.model_dump(),
            compilation=compilation,
            live_review=guard,
            payload_sha256=sha(out),
            collision_check=native.name_scope(),
            backup_effects=backup_effects(),
            can_apply=True,
            scope="Local inline reheat airflow permissive and final valve limit. Application transfer interrupts control.",
            connector_config=config,
            created_at=utc(),
            expires_at=(datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
        )
        return native.retain_plan(body, options, app, config)


def validate_review(plan):
    body = plan["body"]
    if (
        body.get("operation_profile") != PROFILE
        or seal(body) != plan["digest"]
        or plan["options"].edit.model_dump() != body.get("inline_edit")
    ):
        raise ValueError(
            "The retained inline airflow review is stale or belongs to another operation."
        )
