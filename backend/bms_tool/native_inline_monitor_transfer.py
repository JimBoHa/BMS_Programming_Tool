"""Review a source-built, observation-only graph through the existing native writer."""

import copy
import math
import time
from datetime import UTC, datetime, timedelta

from bacpypes3.object import Object
from bacpypes3.primitivedata import Boolean, Enumerated, ObjectIdentifier, Real, Unsigned
from pydantic import Field, StrictBool

from .application_preservation import runtime_parameter_changes
from .application_store import PROFILE as APPLICATION_PROFILE
from .application_store import utc
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_inline_monitor import FIRMWARE, MODELS, PROFILE, compile_monitor
from .native_snapshot_restore import Hash, Identifier, fresh_current, qualify_restore_counters
from .property_evidence import PropertyEvidence, ReadBudget


class MonitorReview(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    capture_id: Identifier
    snapshot_sha256: Hash
    first_instance: int = Field(strict=True, ge=1, le=4194302)


class MonitorApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: Hash
    monitor_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


def allocation_scope():
    return {
        "scope": "Internal monitor objects at the selected station",
        "devices": [],
        "checked_at": utc(),
        "allocation_required": True,
    }


async def operating_state(native, session, identity, compilation):
    device = identity["device"]
    if identity["model-name"] not in MODELS or identity["firmware-revision"] != FIRMWARE:
        raise ValueError("This controller model and firmware have no matching monitor profile.")
    if int(await native.path._read(session, device, "system-status")) != 0:
        raise ValueError("The selected controller must be operational.")
    points = compilation["points"]
    expect = {
        "pressure": ("DA-VP", 58),
        "duct": ("DA-T", 64),
        "flow": ("SA-F", 84),
        "valve": ("HTG-O", 98),
        "damper": ("DPR-O", 98),
    }
    readings = {}
    for key, (name, unit) in expect.items():
        obj = points[key]
        if (
            str(await native.path._read(session, obj, "object-name")) != name
            or int(await native.input_atomic(session, obj, 117, Enumerated)) != unit
            or bool(await native.input_atomic(session, obj, 81, Boolean))
            or int(await native.input_atomic(session, obj, 103, Enumerated)) != 0
        ):
            raise ValueError(f"The selected {key} has a different identity, units or quality.")
        value = float(await native.input_atomic(session, obj, 85, Real))
        if not math.isfinite(value):
            raise ValueError(f"The selected {key} returned a nonfinite reading.")
        readings[key] = value
    if bool(await native.input_atomic(session, points["flow"], 3368, Boolean)):
        raise ValueError("Airflow must be out of test mode.")
    for key, terminal in (("valve", "CO OUT4"), ("damper", "BO1-Int,BO2-Int")):
        obj = points[key]
        slots = list(await native.path._read(session, obj, "priority-array"))
        if (
            str(await native.path._read(session, obj, "device-type")) != terminal
            or len(slots) != 16
            or any(getattr(s, "_choice", None) != "null" for s in slots[:15])
        ):
            raise ValueError(f"The {key} terminal has changed or a command is active.")
    return readings


async def confirm_individual_absence(native, session, points):
    reader = PropertyEvidence(native.path)
    for point in points:
        # Recheck a lost read of this exact slot. Only the final attributed
        # unknown-object reply can establish its absence.
        budget = ReadBudget(max_requests=2, max_bytes=128 * 1024)
        _, row = await reader.read(session, budget, point, 75, Object, timeout=native.files.timeout)
        if row["status"] == "timeout":
            _, row = await reader.read(
                session, budget, point, 75, Object, timeout=native.files.timeout
            )
        error = row.get("native_error") or {}
        if (
            row["status"] != "native_error"
            or not row.get("transport_evidence")
            or error.get("errorClass", {}).get("value") != 1
            or error.get("errorCode", {}).get("value") != 31
        ):
            detail = row.get("error") or row["status"]
            raise ValueError(f"The controller did not confirm that {point} is unused ({detail}).")


async def check_allocations(native, session, identity, compilation):
    readings = await operating_state(native, session, identity, compilation)
    floor = int(await native.input_atomic(session, identity["device"], 787, Unsigned))
    points = compilation["added_objects"]
    if len(set(points)) != len(points) or min(int(ObjectIdentifier(p)[1]) for p in points) < floor:
        raise ValueError("The proposed monitor overlaps the live allocation range.")
    await confirm_individual_absence(native, session, points)
    return {"allocator": floor, "confirmed_absent": len(points), "values": readings}


async def review(native, options, *, shadow=False, activation=False):
    from . import native_inline_activation as valve
    from . import native_inline_shadow
    from .native_applications import PLAN_SECONDS, backup_effects

    operation = valve if activation else native_inline_shadow if shadow else None
    kind = operation.KIND if operation else KIND
    async with native.operation(options.operation_id, f"review-{kind}"):
        native.available(options)
        capture, files = native.check_capture(options)
        if capture["evidence_sha256"] != options.snapshot_sha256:
            raise ValueError("The retained physical backup changed. Review the current capture.")
        request = {
            "restore_capture_id": options.capture_id,
            "restore_snapshot_sha256": options.snapshot_sha256,
        }
        _, recovery = native.restore_source(request)
        from .native_snapshot_restore import require_restore_source

        require_restore_source(recovery)
        if activation:
            observation = native.storage.receipt(
                options.observation_receipt_id, include_events=False
            )
            if (observation.get("intent") or {}).get("sequence_selection", {}).get(
                "sampling_mode"
            ) != "elapsed-phase":
                raise ValueError(
                    "Install and verify the elapsed-phase observation before activating the valve."
                )
            out, compilation = valve.prepare(
                native,
                capture["identity"],
                files,
                options.observation_receipt_id,
                native.target(options),
            )
        elif shadow:
            out, compilation = native_inline_shadow.compile_shadow(
                native, capture["identity"], native_inline_shadow.selection(options), files
            )
        else:
            out, compilation = compile_monitor(files, options.first_instance)
        config, app = copy.deepcopy(native.bacnet.config), native.bacnet.require()
        async with native.path._path(options) as session:
            PropertyEvidence.pin(session, options.router)
            identity, _ = await native.identity(session, options.device)
            if identity != capture["identity"]:
                raise ValueError(
                    "The current controller differs from the selected original backup."
                )
            guard_started = time.monotonic()
            guard = await (operation.guard if operation else check_allocations)(
                native, session, identity, compilation
            )
            guard_seconds = time.monotonic() - guard_started
        # A slow trunk must repeat the entire allocation walk at apply. Allow
        # time for that measured walk and the separate fresh backup.
        lifetime = (
            min(45 * 60, max(PLAN_SECONDS, math.ceil(1.5 * guard_seconds + 4 * 60)))
            if shadow
            else PLAN_SECONDS
        )
        instance = int(ObjectIdentifier(options.device)[1])
        body = dict(
            profile=APPLICATION_PROFILE,
            operation_profile=operation.PROFILE if operation else PROFILE,
            change_kind=operation.KIND if operation else KIND,
            target=native.target(options),
            identity=identity,
            old_instance=instance,
            new_instance=instance,
            old_name=identity["object-name"],
            new_name=identity["object-name"],
            capture_id=options.capture_id,
            snapshot_sha256=options.snapshot_sha256,
            application_sha256=sha(files[3]),
            static_parameters_sha256=sha(files[11]),
            compilation=compilation,
            live_review=guard,
            payload_sha256=sha(out),
            collision_check=operation.scope() if operation else allocation_scope(),
            recovery_source_sha256=recovery["evidence_sha256"],
            backup_effects=backup_effects(),
            can_apply=True,
            scope=(
                "Connect the observed airflow permissive and discharge limit to the inline valve. Application transfer temporarily interrupts control."
                if activation
                else "Install the complete airflow and discharge-limit logic with its two tuning points for observation. The existing valve connection remains active."
                if shadow
                else "Install internal sensor and timer observations. Existing control connections are preserved. Application transfer temporarily interrupts control."
            ),
            connector_config=config,
            created_at=utc(),
            expires_at=(datetime.now(UTC) + timedelta(seconds=lifetime)).isoformat(),
        )
        body.update(operation.receipt_fields(options) if operation else receipt_fields(options))
        return native.retain_plan(body, options, app, config, lifetime=lifetime)


def validate_review(plan):
    body = plan["body"]
    if (
        body.get("operation_profile") != PROFILE
        or seal(body) != plan["digest"]
        or body.get("first_instance") != plan["options"].first_instance
    ):
        raise ValueError("The exact monitor review has changed. Review again.")


def fresh_compile(native, body, files):
    reviewed, before = native.storage.load(body["capture_id"])
    if reviewed["evidence_sha256"] != body["snapshot_sha256"]:
        raise ValueError("The reviewed original backup has changed.")
    fresh_current(before, files)
    return compile_monitor(files, body["first_instance"])


def reconstruct(native, intent):
    if intent.get("operation_profile") != PROFILE or intent.get("monitor_confirmed") is not True:
        raise ValueError("The monitor receipt has no matching confirmed operation.")
    _, files = native.storage.load(intent["backup_id"])
    out, report = compile_monitor(files, intent["first_instance"])
    if (
        report != intent["compilation"]
        or sha(out) != intent["payload_sha256"]
        or sha(MoiIdentity(out).data) != intent["native_payload_sha256"]
    ):
        raise ValueError("The monitor receipt differs from its fresh original backup.")
    return out


def verify(native, intent, files):
    output = reconstruct(native, intent)
    actual = MoiIdentity(files[3])
    if actual.data != MoiIdentity(output).data:
        raise ValueError("The complete application differs from the reviewed monitor.")
    parameters = ParameterApplication(files[3], files[11], files[12])
    matched, counters, calculated = runtime_parameter_changes(actual, parameters)
    qualify_restore_counters(files, counters)
    return {
        "native_graph_verified": True,
        "saved_parameters_verified": matched["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "runtime_sampling_verified": False,
    }


KIND = "inline-monitor"
CONFIRMATION = "monitor_confirmed"
guard = check_allocations
scope = allocation_scope


def receipt_fields(options):
    return {"first_instance": options.first_instance}
