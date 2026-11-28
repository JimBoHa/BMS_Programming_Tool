"""Review a source-built, observation-only graph through the existing native writer."""

import asyncio
import copy
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

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


class ClockMonitorReview(MonitorReview):
    sample_register: StrictBool = False
    activity_input: StrictBool = False
    register_source: Literal["countdown", "supply-airflow"] = "countdown"


def reviewed_register_source(compilation):
    return (
        "supply-airflow"
        if "airflow_source" in compilation.get("sampling_register", {})
        else "countdown"
    )


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
    valve_terminal = "CO OUT4"
    floating = compilation.get("floating_valve")
    if floating is not None:
        valve = points["valve"]
        first = int(await native.input_atomic(session, valve, 990, Unsigned))
        second = int(await native.input_atomic(session, valve, 991, Unsigned))
        stroke = float(await native.input_atomic(session, valve, 3478, Real))
        if [first, second] != floating["terminals"] or stroke != floating["stroke_seconds"]:
            raise ValueError(
                "The live floating valve terminals or stroke time differ from the capture."
            )
        valve_terminal = f"BO OUT{first},BO OUT{second}"
    for key, terminal in (("valve", valve_terminal), ("damper", "BO1-Int,BO2-Int")):
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
    if len(set(points)) != len(points):
        raise ValueError("The monitor includes a repeated object identifier.")
    if min(int(ObjectIdentifier(p)[1]) for p in points) < floor:
        raise ValueError(
            f"The selected controller reserves lower instances. Choose a first instance of {floor} or higher."
        )
    await confirm_individual_absence(native, session, points)
    return {"allocator": floor, "confirmed_absent": len(points), "values": readings}


async def review(native, options):
    from .native_applications import PLAN_SECONDS, backup_effects

    async with native.operation(options.operation_id, "review-inline-monitor"):
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
        with_register = isinstance(options, ClockMonitorReview) and options.sample_register
        activity_input = isinstance(options, ClockMonitorReview) and options.activity_input
        register_source = getattr(options, "register_source", "countdown")
        out, compilation = compile_monitor(
            files,
            options.first_instance,
            allow_floating=True,
            sample_register=with_register,
            activity_input=activity_input,
            register_source=register_source,
        )
        config, app = copy.deepcopy(native.bacnet.config), native.bacnet.require()
        async with native.path._path(options) as session:
            PropertyEvidence.pin(session, options.router)
            identity, _ = await native.identity(session, options.device)
            if identity != capture["identity"]:
                raise ValueError(
                    "The current controller differs from the selected original backup."
                )
            guard = await check_allocations(native, session, identity, compilation)
        instance = int(ObjectIdentifier(options.device)[1])
        body = dict(
            profile=APPLICATION_PROFILE,
            operation_profile=PROFILE,
            change_kind=KIND,
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
            collision_check=allocation_scope(),
            recovery_source_sha256=recovery["evidence_sha256"],
            backup_effects=backup_effects(),
            can_apply=True,
            scope=(
                "Install internal sensor and timer observations"
                + (" and a gated timing register" if with_register else "")
                + (" with a Float activity input" if activity_input else "")
                + (
                    " sampling the captured supply airflow in CFM"
                    if register_source == "supply-airflow"
                    else ""
                )
                + ". Existing control connections are preserved. Application transfer temporarily interrupts control."
            ),
            connector_config=config,
            created_at=utc(),
            expires_at=(datetime.now(UTC) + timedelta(seconds=PLAN_SECONDS)).isoformat(),
        )
        body.update(receipt_fields(options))
        return native.retain_plan(body, options, app, config)


def validate_review(plan):
    body = plan["body"]
    if (
        body.get("operation_profile") != PROFILE
        or seal(body) != plan["digest"]
        or body.get("first_instance") != plan["options"].first_instance
        or not isinstance(body.get("compilation"), dict)
        or ("sampling_register" in body["compilation"])
        != getattr(plan["options"], "sample_register", False)
        or ("register_input_activity" in body["compilation"])
        != getattr(plan["options"], "activity_input", False)
        or reviewed_register_source(body["compilation"])
        != getattr(plan["options"], "register_source", "countdown")
    ):
        raise ValueError("The exact monitor review has changed. Review again.")


def fresh_compile(native, body, files):
    reviewed, before = native.storage.load(body["capture_id"])
    if reviewed["evidence_sha256"] != body["snapshot_sha256"]:
        raise ValueError("The reviewed original backup has changed.")
    fresh_current(before, files)
    return compile_monitor(
        files,
        body["first_instance"],
        allow_floating="floating_valve" in body["compilation"],
        sample_register="sampling_register" in body["compilation"],
        activity_input="register_input_activity" in body["compilation"],
        register_source=reviewed_register_source(body["compilation"]),
    )


def reconstruct(native, intent):
    if intent.get("operation_profile") != PROFILE or intent.get("monitor_confirmed") is not True:
        raise ValueError("The monitor receipt has no matching confirmed operation.")
    _, files = native.storage.load(intent["backup_id"])
    out, report = compile_monitor(
        files,
        intent["first_instance"],
        preserve_root_layout=intent["compilation"].get("root_layout_version") == 2,
        allow_floating="floating_valve" in intent["compilation"],
        sample_register="sampling_register" in intent["compilation"],
        activity_input="register_input_activity" in intent["compilation"],
        register_source=reviewed_register_source(intent["compilation"]),
    )
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


async def observe_execution(native, session, intent):
    """Read the installed timer's downstream value without polling the timer itself."""
    witness = intent["compilation"]["clock_witness"]
    evidence = {"object": witness, "status": "unconfirmed", "samples": [], "read_only": True}
    try:
        if int(await native.input_atomic(session, witness, 103, Enumerated)) != 0:
            raise ValueError("The installed clock witness reports unreliable data.")
        start = time.monotonic()
        for index in range(6):
            await asyncio.sleep(max(0, start + index - time.monotonic()))
            before = time.monotonic() - start
            value = float(await native.input_atomic(session, witness, 85, Real))
            after = time.monotonic() - start
            if not value.is_integer() or not 0 <= value <= 60 or after >= 30:
                raise ValueError("The clock value or read window is outside the diagnostic range.")
            evidence["samples"].append(
                {"requested": before, "received": after, "seconds": int(value)}
            )
        if int(await native.input_atomic(session, witness, 103, Enumerated)) != 0:
            raise ValueError("The clock witness became unreliable during observation.")
        if (
            await native.instances._identity(session, intent["identity"]["device"])
            != intent["identity"]
        ):
            raise ValueError("The controller identity changed during clock observation.")
        samples = evidence["samples"]
        if len({r["seconds"] % 60 for r in samples}) == 1:
            evidence["status"] = "stationary"
            return evidence
        advance = 0
        for previous, current in zip(samples, samples[1:], strict=False):
            step = (previous["seconds"] - current["seconds"]) % 60
            low = current["requested"] - previous["received"] - 1
            high = current["received"] - previous["requested"] + 1
            if not low <= step <= high:
                raise ValueError("The downstream countdown differs from elapsed observation time.")
            advance += step
        first, last = samples[0], samples[-1]
        if (
            advance < 3
            or not last["requested"] - first["received"] - 1
            <= advance
            <= last["received"] - first["requested"] + 1
        ):
            raise ValueError("Insufficient elapsed countdown progression.")
        evidence.update(status="advancing", countdown_seconds=advance)
    except (ValueError, TimeoutError, OSError) as exc:
        evidence["error"] = (str(exc) or type(exc).__name__)[:256]
    return evidence


KIND = "inline-monitor"
CONFIRMATION = "monitor_confirmed"
guard = check_allocations
scope = allocation_scope


def receipt_fields(options):
    return {"first_instance": options.first_instance}
