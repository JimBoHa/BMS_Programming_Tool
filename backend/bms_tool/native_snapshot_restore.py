"""Reconstruct retained application images and guard a separate current source."""

from datetime import datetime
from typing import Annotated, Literal

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, TypeAdapter

from .application_preservation import _property_names, runtime_parameter_changes
from .application_store import PROFILE as APPLICATION_PROFILE
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_backup_records import BackupInspectionSource, NativeBackupRecords
from .native_parameter_qualification import qualify_parameter_additions

PROFILE = "native-retained-application-restore/1"
SOURCE_PROFILE = "native-retained-application-restore-source/1"
COMPILATION_PROFILE = "native-retained-application-restore-compilation/1"
GUARD_PROFILE = "native-restore-current-configuration/1"
DIFFERENCE_SCOPE = "Complete native record-byte comparison, including opaque records; not runtime behavior or physical I/O compatibility."
SCOPE = (
    "Restore one retained native application and its supported historical saved application "
    "settings to the matching recorded route and complete Device/model/firmware identity. "
    "Read a separate current application for review and retain a fresh pre-write backup. "
    "Refuse changed current non-runtime settings; permit only qualified monotonic counters. "
    "One newly confirmed restore and complete native/effective readback are required. "
    "No automatic replay, new identity allocation, cross-controller/release migration, "
    "general logic compiler, whole-controller/runtime backup or CCT/physical acceptance."
)
SOURCE_SCOPE = (
    "Reconstruct this retained File3 application with supported saved application values "
    "from its original Files11/12. Preserve original object identities, graph and opaque "
    "configuration. Values are historical, not live. Non-application runtime slots remain "
    "original evidence and are not application defaults. No controller query, transfer "
    "review, current-device verification or field authority."
)
Hash = Annotated[str, Field(strict=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[
    str, Field(strict=True, min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
]
Count = Annotated[int, Field(strict=True, ge=0, le=131072)]


class RestoreSource(StrictModel):
    restore_capture_id: Identifier
    restore_snapshot_sha256: Hash


class RestoreExport(RestoreSource):
    source_evidence_sha256: Hash


class CurrentGuard(StrictModel):
    profile: Literal[GUARD_PROFILE]
    application_sha256: Hash
    static_parameters_sha256: Hash
    saved_configuration_sha256: Hash
    counter_values_sha256: Hash
    saved_parameter_count: Count
    counter_count: Count


def recorded_source(desired):
    """Validate the closed recorded profile without loading a source or a device."""
    if not isinstance(desired, dict) or set(desired) != {
        "profile",
        "scope",
        "request",
        "captured_at",
        "target",
        "identity",
        "compilation",
        "saved_settings_merged",
        "read_only",
        "controller_queries",
        "field_actions",
        "field_transfer_enabled",
        "current_device_verified",
        "can_apply",
        "evidence_sha256",
    }:
        raise ValueError("The recorded restore source has an unknown shape.")
    RestoreSource.model_validate(desired["request"])
    TypeAdapter(Hash).validate_python(desired["evidence_sha256"])
    datetime.fromisoformat(desired["captured_at"])
    identity = desired["identity"]
    if (
        not isinstance(identity, dict)
        or set(identity)
        != {
            "device",
            "object-name",
            "vendor-identifier",
            "model-name",
            "firmware-revision",
            "application-software-version",
        }
        or type(identity["vendor-identifier"]) is not int
        or identity["vendor-identifier"] != 5
        or any(
            not isinstance(value, str) or not 1 <= len(value) <= 512
            for key, value in identity.items()
            if key != "vendor-identifier"
        )
        or DeviceDetailsRequest.model_validate(desired["target"]).model_dump() != desired["target"]
        or identity["device"] != desired["target"]["device"]
    ):
        raise ValueError("The recorded restore source lacks its exact complete identity.")
    c = desired["compilation"]
    if not isinstance(c, dict) or set(c) != {
        "files",
        "archive_native_sha256",
        "compiled_sha256",
        "compiled_native_sha256",
        "compiled_bytes",
        "native_record_count",
        "format_versions",
        "encoding",
        "saved_application_parameters",
        "changed_saved_parameters",
        "retained_runtime_slots",
        "omitted_field_qualification",
        "non_application_runtime_restored",
    }:
        raise ValueError("The recorded restore compilation has an unknown shape.")
    if not isinstance(c["files"], dict) or set(c["files"]) != {"3", "11", "12"}:
        raise ValueError("Recorded restoration requires all three original native files.")
    for item in c["files"].values():
        if (
            not isinstance(item, dict)
            or set(item) != {"bytes", "sha256"}
            or type(item["bytes"]) is not int
            or not 1 <= item["bytes"] <= 2097152
        ):
            raise ValueError("Invalid recorded native file size.")
        TypeAdapter(Hash).validate_python(item["sha256"])
    for key in ("archive_native_sha256", "compiled_sha256", "compiled_native_sha256"):
        TypeAdapter(Hash).validate_python(c[key])
    q = c["omitted_field_qualification"]
    versions = c["format_versions"]
    if (
        any(
            type(c[k]) is not int or not 1 <= c[k] <= 2097152
            for k in ("compiled_bytes", "native_record_count")
        )
        or not isinstance(versions, dict)
        or set(versions) != {"acs", "dmcs"}
        or any(type(v) is not int or not 1 <= v <= 65535 for v in versions.values())
        or c["encoding"] not in ("moi-v2", "gzip-moi-v2")
        or any(
            type(c[k]) is not int or not 0 <= c[k] <= 131072
            for k in (
                "saved_application_parameters",
                "changed_saved_parameters",
                "retained_runtime_slots",
            )
        )
        or c["changed_saved_parameters"] > c["saved_application_parameters"]
        or c["non_application_runtime_restored"] is not False
        or not isinstance(q, dict)
        or set(q) != {"profile", "qualified_fields", "model_inventory_used"}
        or q["profile"] != "native-omitted-application-field-types/1"
        or type(q["qualified_fields"]) is not int
        or not 0 <= q["qualified_fields"] <= 131072
        or q["model_inventory_used"] is not False
    ):
        raise ValueError("Invalid recorded source compilation or datatype qualification.")


def records(app):
    rows = {}
    for record in app.records:
        oid = int.from_bytes(app.data[record["offset"] + 6 : record["offset"] + 10], "big")
        if oid in rows:
            raise ValueError("Ambiguous native object identities prevent application restoration.")
        rows[oid] = record
    return rows


def value_bytes(app, record, pid):
    prop = record["properties"].get(pid)
    if prop is None:
        raise ValueError("A saved application property is missing after reconstruction.")
    return app.data[prop["value_start_offset"] : prop["value_end_offset"]]


def merged(files):
    if set(files) != {3, 11, 12}:
        raise ValueError("Restoration requires one complete original File3/11/12 snapshot.")
    parameters = ParameterApplication(files[3], files[11], files[12])
    output, report = parameters.compile()
    if not 1 <= len(output) <= 2 * 1024 * 1024:
        raise ValueError("The reconstructed application exceeds the native snapshot file limit.")
    app, original = MoiIdentity(output), MoiIdentity(files[3])
    qualification = qualify_parameter_additions(output, report)
    before, after = original.summary(), app.summary()
    if any(
        before[key] != after[key]
        for key in ("instance", "name", "model", "root_class", "root_ref", "format_versions")
    ) or list(records(original)) != list(records(app)):
        raise ValueError("Saved values changed original identity, format or record membership.")
    versions = after["format_versions"]
    if any(type(versions[k]) is not int or not 0 < versions[k] <= 65535 for k in ("acs", "dmcs")):
        raise ValueError("Restoration requires explicit native application/data-model versions.")
    return output, app, parameters, report, qualification


def _source(storage, request):
    options = RestoreSource.model_validate(request)
    snapshot, files = NativeBackupRecords(storage).load_files(
        {
            "capture_id": options.restore_capture_id,
            "snapshot_sha256": options.restore_snapshot_sha256,
        }
    )
    output, app, _, merge, qualification = merged(files)
    identity, summary = snapshot["identity"], app.summary()
    target = DeviceDetailsRequest(**snapshot["target"], device=snapshot["device"]).model_dump()
    if (
        snapshot.get("source_identity_matches") is not True
        or set(identity)
        != {
            "device",
            "object-name",
            "vendor-identifier",
            "model-name",
            "firmware-revision",
            "application-software-version",
        }
        or type(identity.get("vendor-identifier")) is not int
        or identity["vendor-identifier"] != 5
        or snapshot["device"] != f"device,{summary['instance']}"
        or identity.get("device") != snapshot["device"]
        or identity.get("object-name") != summary["name"]
        or identity.get("model-name") != summary["model"]
        or any(
            type(identity.get(key)) is not str or not identity[key]
            for key in (
                "object-name",
                "model-name",
                "firmware-revision",
                "application-software-version",
            )
        )
    ):
        raise ValueError("Restore source lacks matching native and complete recorded identity.")
    compilation = {
        "files": {str(k): {"bytes": len(v), "sha256": sha(v)} for k, v in files.items()},
        "archive_native_sha256": sha(MoiIdentity(files[3]).data),
        "compiled_sha256": sha(output),
        "compiled_native_sha256": sha(app.data),
        "compiled_bytes": len(output),
        "native_record_count": len(app.records),
        "format_versions": summary["format_versions"],
        "encoding": summary["encoding"],
        "saved_application_parameters": merge["matched_parameters"],
        "changed_saved_parameters": len(merge["changed_parameters"]),
        "retained_runtime_slots": len(merge["retained_runtime_parameters"]),
        "omitted_field_qualification": qualification,
        "non_application_runtime_restored": False,
    }
    body = {
        "profile": SOURCE_PROFILE,
        "scope": SOURCE_SCOPE,
        "request": options.model_dump(),
        "captured_at": snapshot["captured_at"],
        "target": target,
        "identity": identity,
        "compilation": compilation,
        "saved_settings_merged": True,
        "read_only": True,
        "controller_queries": False,
        "field_actions": False,
        "field_transfer_enabled": False,
        "current_device_verified": False,
        "can_apply": False,
    }
    return output, {**body, "evidence_sha256": seal(body)}


def source(storage, request):
    try:
        return _source(storage, request)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(
            "Retained application source metadata is incomplete or inconsistent."
        ) from exc


def current_guard(files):
    """Bind all current saved configuration; name only existing runtime policies."""
    _, app, parameters, _, _ = merged(files)
    objects = records(app)
    by_class, names = _property_names()
    settings, counters = [], []
    for parameter in parameters.parameters:
        cid, instance, pid = (parameter[key] for key in ("class", "instance", "property"))
        record = objects.get(cid << 22 | instance)
        if record is None:
            raise ValueError("A current saved selector has no unambiguous application record.")
        raw = value_bytes(app, record, pid)
        label = by_class.get(str(cid), {}).get(str(pid), names.get(str(pid), "Unknown"))
        legacy = (cid, pid) == (251, 978) and app.summary()["format_versions"] == {
            "acs": 60,
            "dmcs": 60,
        }
        declared = app.reader.scalar(record, 75)
        object_property = record["properties"].get(75)
        object_bytes = value_bytes(app, record, 75) if object_property else b""
        binary = (
            isinstance(declared, str)
            and len(object_bytes) == 6
            and object_bytes[:1] == b"\xc4"
            and int(ObjectIdentifier(declared)[0]) in (3, 4, 5)
        )
        counter = legacy or (
            binary and (pid, label) in ((15, "COS Count"), (33, "Elapsed Active Time"))
        )
        entry = {"class": cid, "instance": instance, "property": pid}
        if counter:
            value = app.reader.scalar(record, pid)
            if (
                not raw
                or raw[0] >> 4 != 2
                or type(value) is not int
                or not 0 <= value <= 4294967295
            ):
                raise ValueError("A qualified current runtime counter lacks its Unsigned value.")
            counters.append({**entry, "value": value})
        else:
            settings.append({**entry, "value_sha256": sha(raw)})
    body = CurrentGuard(
        profile=GUARD_PROFILE,
        application_sha256=sha(files[3]),
        static_parameters_sha256=sha(files[11]),
        saved_configuration_sha256=seal(settings),
        counter_values_sha256=seal(counters),
        saved_parameter_count=len(parameters.parameters),
        counter_count=len(counters),
    ).model_dump()
    return body, counters


def fresh_current(reviewed, fresh):
    before, old_counters = current_guard(reviewed)
    after, new_counters = current_guard(fresh)
    if (
        {k: v for k, v in before.items() if k != "counter_values_sha256"}
        != {k: v for k, v in after.items() if k != "counter_values_sha256"}
        or len(old_counters) != len(new_counters)
        or any(
            {k: v for k, v in old.items() if k != "value"}
            != {k: v for k, v in new.items() if k != "value"}
            or new["value"] < old["value"]
            for old, new in zip(old_counters, new_counters, strict=True)
        )
    ):
        raise ValueError(
            "Current application, directory or saved configuration changed; review again."
        )
    return before, after


def difference(before, after):
    left, right = records(before), records(after)
    added, removed = sorted(right.keys() - left.keys()), sorted(left.keys() - right.keys())
    changed = [
        oid
        for oid in sorted(left.keys() & right.keys())
        if before.data[left[oid]["offset"] : left[oid]["end_offset"]]
        != after.data[right[oid]["offset"] : right[oid]["end_offset"]]
    ]
    return {
        "before_records": len(left),
        "restored_records": len(right),
        "added_records": len(added),
        "removed_records": len(removed),
        "changed_existing_records": len(changed),
        "before_native_sha256": sha(before.data),
        "restored_native_sha256": sha(after.data),
        "scope": DIFFERENCE_SCOPE,
    }


def compile_restore(storage, desired_request, current_request, fresh_files):
    """Reconstruct desired bytes and independently guard the reviewed current state."""
    output, desired = source(storage, desired_request)
    current_output, current = source(
        storage,
        {
            "restore_capture_id": current_request["capture_id"],
            "restore_snapshot_sha256": current_request["snapshot_sha256"],
        },
    )
    _, reviewed_files = NativeBackupRecords(storage).load_files(current_request)
    if (
        desired["identity"] != current["identity"]
        or desired["target"] != current["target"]
        or desired["compilation"]["format_versions"] != current["compilation"]["format_versions"]
    ):
        raise ValueError(
            "Retained and current route, identity, firmware or native format disagree."
        )
    if (
        desired["compilation"]["compiled_native_sha256"]
        == current["compilation"]["compiled_native_sha256"]
    ):
        raise ValueError("The reviewed current application already matches this retained image.")
    reviewed_guard, prewrite_guard = fresh_current(reviewed_files, fresh_files)
    report = {
        "profile": COMPILATION_PROFILE,
        "scope": SCOPE,
        "restore_source_evidence_sha256": desired["evidence_sha256"],
        "reviewed_current": current_request,
        "reviewed_current_guard": reviewed_guard,
        "prewrite_guard": prewrite_guard,
        "difference": difference(MoiIdentity(current_output), MoiIdentity(output)),
        "compiled_sha256": sha(output),
        "compiled_native_sha256": sha(MoiIdentity(output).data),
        "historical_saved_settings_restored": True,
        "non_application_runtime_restored": False,
    }
    return output, desired, {**report, "compilation_sha256": seal(report)}


def _validate_evidence(body):
    """Recorded bindings only; reconstruction is separate and grants no new plan."""
    desired = body["restore_source"]
    recorded_source(desired)
    c = body["compilation"]
    if not isinstance(c, dict) or set(c) != {
        "profile",
        "scope",
        "restore_source_evidence_sha256",
        "reviewed_current",
        "reviewed_current_guard",
        "prewrite_guard",
        "difference",
        "compiled_sha256",
        "compiled_native_sha256",
        "historical_saved_settings_restored",
        "non_application_runtime_restored",
        "compilation_sha256",
    }:
        raise ValueError("The recorded restore review compilation has an unknown shape.")
    BackupInspectionSource.model_validate(c["reviewed_current"])
    for value in (
        c["compiled_sha256"],
        c["compiled_native_sha256"],
        c["restore_source_evidence_sha256"],
        c["difference"]["before_native_sha256"],
        c["difference"]["restored_native_sha256"],
    ):
        TypeAdapter(Hash).validate_python(value)
    for key in ("reviewed_current_guard", "prewrite_guard"):
        guard = CurrentGuard.model_validate(c[key])
        if guard.counter_count > guard.saved_parameter_count:
            raise ValueError("Recorded runtime counters exceed all saved parameters.")
    d = c["difference"]
    if (
        not isinstance(d, dict)
        or set(d)
        != {
            "before_records",
            "restored_records",
            "added_records",
            "removed_records",
            "changed_existing_records",
            "before_native_sha256",
            "restored_native_sha256",
            "scope",
        }
        or d["scope"] != DIFFERENCE_SCOPE
    ):
        raise ValueError("Unknown recorded native record comparison.")
    if (
        body.get("profile") != APPLICATION_PROFILE
        or body.get("change_kind") != "application-restore"
        or body.get("operation_profile") != PROFILE
        or c.get("profile") != COMPILATION_PROFILE
        or c.get("scope") != SCOPE
        or desired.get("profile") != SOURCE_PROFILE
        or desired.get("scope") != SOURCE_SCOPE
        or desired.get("read_only") is not True
        or desired.get("saved_settings_merged") is not True
        or any(
            desired.get(k) is not False
            for k in (
                "controller_queries",
                "field_actions",
                "field_transfer_enabled",
                "current_device_verified",
                "can_apply",
            )
        )
        or desired.get("evidence_sha256")
        != seal({k: v for k, v in desired.items() if k != "evidence_sha256"})
        or c.get("compilation_sha256")
        != seal({k: v for k, v in c.items() if k != "compilation_sha256"})
        or c["restore_source_evidence_sha256"] != desired["evidence_sha256"]
        or c["compiled_sha256"] != desired["compilation"]["compiled_sha256"]
        or c["compiled_native_sha256"] != desired["compilation"]["compiled_native_sha256"]
        or body.get("payload_sha256") != c["compiled_sha256"]
        or body.get("native_payload_sha256", c["compiled_native_sha256"])
        != c["compiled_native_sha256"]
        or body.get("identity") != desired["identity"]
        or type(body.get("old_instance")) is not int
        or type(body.get("new_instance")) is not int
        or body["old_instance"] != body.get("new_instance")
        or desired["identity"]["device"] != f"device,{body['old_instance']}"
        or body.get("old_name") != body.get("new_name")
        or body["old_name"] != desired["identity"]["object-name"]
        or DeviceDetailsRequest(**body["target"], device=body["identity"]["device"]).model_dump()
        != desired["target"]
        or body.get("capture_id", body.get("review_capture_id"))
        != c["reviewed_current"]["capture_id"]
        or c["reviewed_current"]["capture_id"] == desired["request"]["restore_capture_id"]
        or body.get("snapshot_sha256", body.get("review_snapshot_sha256"))
        != c["reviewed_current"]["snapshot_sha256"]
        or c.get("historical_saved_settings_restored") is not True
        or c.get("non_application_runtime_restored") is not False
        or any(k.startswith("recovery_") for k in body)
        or any(
            k in body
            for k in (
                "order_edit",
                "default_edit",
                "wire_edit",
                "input_edit",
                "batch_edit",
                "combined_edit",
                "connection_edit",
                "point_name_edit",
            )
        )
    ):
        raise ValueError("Retained application restore evidence lost its exact source binding.")


def validate_evidence(body):
    try:
        _validate_evidence(body)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(
            "Retained application restore evidence is incomplete or inconsistent."
        ) from exc


def reconstruct(storage, body, fresh_files):
    validate_evidence(body)
    output, desired, compilation = compile_restore(
        storage,
        body["restore_source"]["request"],
        body["compilation"]["reviewed_current"],
        fresh_files,
    )
    if (
        desired != body["restore_source"]
        or compilation["reviewed_current_guard"] != body["compilation"]["reviewed_current_guard"]
        or compilation["difference"] != body["compilation"]["difference"]
        or compilation["compiled_sha256"] != body["payload_sha256"]
    ):
        raise ValueError("Retained restore source or reviewed current evidence changed.")
    return output, compilation


def reconstruct_intent(storage, intent):
    _, before = storage.load(intent["backup_id"])
    output, compilation = reconstruct(storage, intent, before)
    if (
        compilation != intent["compilation"]
        or sha(MoiIdentity(output).data) != intent["native_payload_sha256"]
    ):
        raise ValueError("Recorded restore payload, pre-write backup and compilation disagree.")
    return output


def verify_restore(storage, intent, after):
    expected = MoiIdentity(reconstruct_intent(storage, intent))
    if set(after) != {3, 11, 12}:
        raise ValueError("Restoration readback requires complete application and saved files.")
    observed = MoiIdentity(after[3])
    if expected.data != observed.data:
        raise ValueError("The readback application differs from the exact retained restore image.")
    current, counters, calculated = runtime_parameter_changes(
        observed, ParameterApplication(after[3], after[11], after[12])
    )
    return {
        "profile": "native-retained-application-restore-preservation/1",
        "restored_application_matches_retained_source": True,
        "effective_saved_application_values_verified": True,
        "identity_unchanged": True,
        "restore_source_capture_id": intent["restore_source"]["request"]["restore_capture_id"],
        "prewrite_backup_id": intent["backup_id"],
        "saved_application_parameters_verified": intent["restore_source"]["compilation"][
            "saved_application_parameters"
        ],
        "post_saved_parameters": current["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "verified_application_sha256": sha(after[3]),
        "preserved_native_sha256": sha(expected.data),
        "non_application_runtime_restored": False,
        "controller_writes": False,
    }
