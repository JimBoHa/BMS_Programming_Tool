"""Source-bound commissioning of the complete inline sequence with existing outputs retained."""

from bacpypes3.apdu import ReadPropertyMultipleACK, ReadPropertyMultipleRequest
from bacpypes3.basetypes import PropertyReference, ReadAccessSpecification
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, StrictBool

from . import native_inline_monitor_transfer as monitor
from .application_preservation import runtime_parameter_changes
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_inline_sequence import InlineSequenceCompiler
from .native_parameter_qualification import qualify_parameter_additions
from .native_snapshot_restore import Hash, Identifier, fresh_current, qualify_restore_counters

PROFILE = "native-inline-sequence-observation/1"
KIND = "inline-sequence-observe"


class ShadowReview(monitor.MonitorReview):
    prototype_capture_id: Identifier
    prototype_sha256: Hash


class ShadowApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: Hash
    sequence_observation_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


def selection(options):
    return {
        "sampling_mode": "elapsed-phase",
        **options.model_dump(
            include={"first_instance", "prototype_capture_id", "prototype_sha256"}
        ),
    }


def compile_shadow(native, identity, options, files):
    donor, library = native.storage.load(options["prototype_capture_id"])
    if (
        donor["evidence_sha256"] != options["prototype_sha256"]
        or not donor.get("source_identity_matches")
        or any(
            donor["identity"].get(k) != identity.get(k)
            for k in ("model-name", "firmware-revision", "vendor-identifier")
        )
        or identity.get("model-name") not in monitor.MODELS
        or identity.get("firmware-revision") != monitor.FIRMWARE
    ):
        raise ValueError(
            "The primitive source needs a verified backup from the same model and firmware."
        )
    mode = options.get("sampling_mode")
    if mode not in (None, "elapsed-phase"):
        raise ValueError("Unsupported observation sampling mode.")
    compiler = InlineSequenceCompiler(
        files, library[3], options["first_instance"], phase_sampling=mode == "elapsed-phase"
    )
    qualification = qualify_parameter_additions(compiler.application.source, compiler.merge)
    compiler.body()
    out, report = compiler.export(shadow=True)
    original_count = len(compiler.application.records)
    if (
        report["old_wires_replaced"]
        or len(compiler.allocations) != len(set(compiler.allocations))
        or original_count + len(compiler.allocations) > 3000
    ):
        raise ValueError(
            "The observation graph changes an existing wire or exceeds the object budget."
        )
    report.update(
        profile=PROFILE,
        original_record_count=original_count,
        prototype_application_sha256=sha(library[3]),
        parameter_qualification=qualification,
    )
    return out, report


async def check_allocations(native, session, identity, compilation):
    from bacpypes3.primitivedata import Unsigned

    readings = await monitor.operating_state(native, session, identity, compilation)
    floor = int(await native.input_atomic(session, identity["device"], 787, Unsigned))
    points = compilation["added_objects"]
    if len(set(points)) != len(points) or min(int(ObjectIdentifier(i)[1]) for i in points) < floor:
        raise ValueError("The current allocator overlaps the proposed objects.")
    count = int(await native.path._read(session, identity["device"], "object-list", 0))
    if max(count, compilation["original_record_count"]) + len(points) > 3000:
        raise ValueError(
            "The projected application exceeds the controller family's BACnet object count."
        )
    for offset in range(0, len(points), 12):
        batch = points[offset : offset + 12]
        request = ReadPropertyMultipleRequest(
            listOfReadAccessSpecs=[
                ReadAccessSpecification(
                    objectIdentifier=ObjectIdentifier(oid),
                    listOfPropertyReferences=[PropertyReference(propertyIdentifier=75)],
                )
                for oid in batch
            ]
        )
        try:
            reply = await native.files.exchange(session, request, ReadPropertyMultipleACK)
        except ValueError as exc:
            # Some releases reject an entire RPM as soon as any object is absent.
            # That reply cannot establish which objects are missing.
            error = exc.__cause__
            if (str(getattr(error, "errorClass", "")), str(getattr(error, "errorCode", ""))) != (
                "object",
                "unknown-object",
            ):
                raise
            await monitor.confirm_individual_absence(native, session, points[offset:])
            break
        if [str(row.objectIdentifier) for row in reply.listOfReadAccessResults] != batch:
            raise ValueError("The allocation reply differs from the requested group.")
        for row in reply.listOfReadAccessResults:
            if len(row.listOfResults) != 1:
                raise ValueError("Incomplete allocation reply.")
            item = row.listOfResults[0]
            error = item.readResult.propertyAccessError
            if (
                int(item.propertyIdentifier) != 75
                or item.propertyArrayIndex is not None
                or error is None
                or int(error.errorClass) != 1
                or int(error.errorCode) != 31
            ):
                raise ValueError(
                    f"The station did not confirm that {row.objectIdentifier} is unused."
                )
    return {
        "allocator": floor,
        "confirmed_absent": len(points),
        "object_list_length": count,
        "values": readings,
    }


async def review(native, options):
    return await monitor.review(native, options, shadow=True)


def validate_review(plan):
    body = plan["body"]
    if (
        body.get("operation_profile") != PROFILE
        or seal(body) != plan["digest"]
        or body.get("sequence_selection") != selection(plan["options"])
    ):
        raise ValueError("The retained observation sequence differs from this review.")


def fresh_compile(native, body, files):
    original, before = native.storage.load(body["capture_id"])
    if original["evidence_sha256"] != body["snapshot_sha256"]:
        raise ValueError("Original source changed.")
    fresh_current(before, files)
    return compile_shadow(native, body["identity"], body["sequence_selection"], files)


def reconstruct(native, intent):
    if (
        intent.get("operation_profile") != PROFILE
        or intent.get("sequence_observation_confirmed") is not True
    ):
        raise ValueError("The receipt does not contain a confirmed observation sequence.")
    _, files = native.storage.load(intent["backup_id"])
    output, report = compile_shadow(native, intent["identity"], intent["sequence_selection"], files)
    if (
        report != intent["compilation"]
        or sha(output) != intent["payload_sha256"]
        or sha(MoiIdentity(output).data) != intent["native_payload_sha256"]
    ):
        raise ValueError(
            "The observation image differs from its recorded original and primitive sources."
        )
    return output


def verify(native, intent, files):
    original = reconstruct(native, intent)
    actual = MoiIdentity(files[3])
    if actual.data != MoiIdentity(original).data:
        raise ValueError("The installed observation graph differs from the reviewed application.")
    verified, counters, calculated = runtime_parameter_changes(
        actual, ParameterApplication(files[3], files[11], files[12])
    )
    qualify_restore_counters(files, counters)
    return {
        "native_graph_verified": True,
        "existing_control_connections_preserved": True,
        "saved_parameters_verified": verified["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "runtime_sampling_verified": False,
    }


CONFIRMATION = "sequence_observation_confirmed"
guard = check_allocations
scope = monitor.allocation_scope


def receipt_fields(options):
    return {"sequence_selection": selection(options)}
