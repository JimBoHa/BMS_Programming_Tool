"""Retained File3 sizes and an explicit single-attempt capacity observation."""

import copy
from collections import Counter

from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.primitivedata import TagClass, TagList
from fastapi import APIRouter
from pydantic import Field

from .application_store import utc
from .device_details import DeviceDetailsRequest
from .moi_identity import MoiIdentity, seal, sha
from .native_backup_records import BackupInspectionSource
from .property_evidence import PropertyEvidence

SOURCE_PROFILE = "native-file3-size-evidence/1"
PROFILE = "native-file3-capacity-evidence/1"
SCOPE = (
    "Historical retained archive bytes compared with one controller-reported File3 "
    "capacity observation. This is not current-program, merged-payload, free-memory, "
    "RAM/flash/scan/resource allocation, release/runtime/CCT or physical acceptance. "
    "No backup-state, restore, write, credentials change, review or transfer is prepared."
)


class CapacityRead(BackupInspectionSource, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


def capacity_value(reply, request):
    if (
        reply.objectIdentifier != request.objectIdentifier
        or reply.propertyIdentifier != request.propertyIdentifier
        or reply.propertyArrayIndex is not None
    ):
        raise ValueError("Capacity response does not match the selected File3 property.")
    tags = list(reply.propertyValue.tagList)
    if (
        len(tags) >= 2
        and tags[0].tag_class == TagClass.opening
        and tags[0].tag_number == 3
        and tags[-1].tag_class == TagClass.closing
        and tags[-1].tag_number == 3
    ):
        tags = tags[1:-1]
    if (
        len(tags) != 1
        or tags[0].tag_class != TagClass.application
        or tags[0].tag_number != 2
        or not 1 <= len(tags[0].tag_data) <= 4
    ):
        raise ValueError("File3 capacity requires one bounded native Unsigned value.")
    value = int.from_bytes(tags[0].tag_data, "big")
    if not 1 <= value <= 0xFFFFFFFF:
        raise ValueError("The controller did not report a positive File3 capacity.")
    return value, bytes(TagList(tags).encode().pduData).hex()


class NativeCapacityEvidence:
    def __init__(self, native, records):
        self.native, self.records = native, records

    def source(self, request):
        options = BackupInspectionSource.model_validate(request)
        snapshot, files, _ = self.records.load(options.model_dump())
        app = MoiIdentity(files[3])
        counts = Counter(r["class_id"] for r in app.records)
        body = {
            **self.records.envelope(snapshot, files),
            "profile": SOURCE_PROFILE,
            "scope": SCOPE,
            "archive_bytes": len(files[3]),
            "expanded_bytes": len(app.data),
            "compression": "gzip" if app.compressed else "raw",
            "native_record_count": len(app.records),
            "record_classes": [
                {"class_id": key, "count": value} for key, value in sorted(counts.items())
            ],
            "diagram_count": sum(counts[key] for key in (536, 575)),
            "source_immutable": True,
            "saved_settings_merged": False,
            "current_application_verified": False,
            "current_identity_verified": False,
            "controller_write": False,
            "restore_payload_prepared": False,
            "can_apply": False,
        }
        return {**body, "source_report_sha256": seal(body)}

    async def read(self, request):
        options = CapacityRead.model_validate(request)
        native = self.native
        async with native.operation(options.operation_id, "read-file3-capacity"):
            native.available(options)
            captured, files = native.check_capture(options)
            if captured["evidence_sha256"] != options.snapshot_sha256:
                raise ValueError("The retained snapshot changed; inspect it again.")
            if (
                captured.get("source_identity_matches") is not True
                or type(captured.get("identity", {}).get("vendor-identifier")) is not int
                or captured["identity"]["vendor-identifier"] != 5
            ):
                raise ValueError("Select a recorded identity-qualified vendor5 source.")
            source = self.source(
                options.model_dump(include=set(BackupInspectionSource.model_fields))
            )
            if source["sha256"] != sha(files[3]):
                raise ValueError("The native source changed during resource inspection.")
            config, app = copy.deepcopy(native.bacnet.config), native.bacnet.require()
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                native.phase("reading capacity identity")
                actual, _ = await native.identity(session, options.device)
                if (
                    type(actual.get("vendor-identifier")) is not int
                    or actual != captured["identity"]
                ):
                    raise ValueError("Responding identity changed after this historical backup.")
                native.phase("reading controller File3 capacity")
                request = ReadPropertyRequest(objectIdentifier=(10, 3), propertyIdentifier=3380)
                reply = await native.files.exchange(session, request, ReadPropertyACK)
                capacity, encoded = capacity_value(reply, request)
                PropertyEvidence(native.path).guard(session)
                if native.bacnet.require() is not app or native.bacnet.config != config:
                    raise ValueError("The native interface changed during capacity inspection.")
                wire = copy.deepcopy(session["last_application_wire"])
            size = source["archive_bytes"]
            body = {
                "profile": PROFILE,
                "scope": SCOPE,
                "source": source,
                "target": {**native.target(options), "device": options.device},
                "identity": actual,
                "connector_config": config,
                "operation_id": options.operation_id,
                "observed_at": utc(),
                "capacity": {
                    "object": "file,3",
                    "property": 3380,
                    "datatype": "Unsigned",
                    "bytes": capacity,
                    "encoded_hex": encoded,
                    "wire": wire,
                },
                "comparison": {
                    "archive_bytes": size,
                    "capacity_bytes": capacity,
                    "archive_fits": size <= capacity,
                    "headroom_for_retained_archive_bytes": capacity - size,
                    "basis": "Original retained File3 bytes; saved values are not merged and the current application is not read.",
                },
                "read_only": True,
                "controller_queries": True,
                "current_identity_verified": True,
                "current_application_verified": False,
                "controller_write": False,
                "field_actions": False,
                "backup_state_commands": False,
                "restore_payload_prepared": False,
                "can_apply": False,
            }
            return {**body, "observation_sha256": seal(body)}


def capacity_evidence_router(native, records):
    service = NativeCapacityEvidence(native, records)
    router = APIRouter(prefix="/api/bacnet/controller/native-application/resources")

    @router.post("/source")
    def source(body: BackupInspectionSource):
        return service.source(body.model_dump())

    @router.post("/read")
    async def read(body: CapacityRead):
        return await service.read(body.model_dump())

    return router
