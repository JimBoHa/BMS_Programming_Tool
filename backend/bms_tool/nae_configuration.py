"""Direct NAE BACnet configuration capture; no JCT/SCT service or runtime.

Only the backup half of the standard lifecycle is admitted here. File identifiers
come from the active session's Configuration_Files array, never field-controller
File3/11/12 assumptions. Native editing/restore require a separate proven codec.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import secrets
import shutil
import time
from pathlib import Path

from bacpypes3.apdu import AtomicReadFileACK, AtomicReadFileRequest, ErrorRejectAbortNack
from bacpypes3.basetypes import (
    AtomicReadFileRequestAccessMethodChoice,
    AtomicReadFileRequestAccessMethodChoiceStreamAccess,
)
from bacpypes3.primitivedata import ObjectIdentifier

from .application_files import BacnetFileTransport
from .application_store import encoded, private_write, read_private, retained_directory, utc
from .bacnet_values import json_value
from .device_details import DeviceDetails, DeviceDetailsRequest
from .file_access import file_lock
from .moi_identity import seal
from .property_evidence import PropertyEvidence

PROFILE = "nae-bacnet-configuration-capture/1"
MAX_FILES = 32
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
UNRESOLVED = {"start_intent", "start_sent", "backup_active", "end_intent", "end_sent"}
IDENTITY = (
    "object-identifier",
    "object-name",
    "vendor-identifier",
    "model-name",
    "firmware-revision",
    "database-revision",
    "max-apdu-length-accepted",
    "protocol-services-supported",
)


class NaeBackupTransport(BacnetFileTransport):
    async def state(self, session, state, **arguments):
        if state not in ("start-backup", "end-backup"):
            raise ValueError("The NAE capture transport does not admit restore or restart states.")
        return await super().state(session, state, **arguments)


class NaeConfigurationCapture:
    def __init__(
        self, bacnet, store, directory, *, timeout=4, poll_seconds=1, operation_seconds=900
    ):
        if (
            not 0.05 <= timeout <= 6
            or not 0.01 <= poll_seconds <= 2
            or not 1 <= operation_seconds <= 900
        ):
            raise ValueError("NAE capture timing exceeds its bounded profile.")
        self.bacnet = bacnet
        self.path = DeviceDetails(bacnet, store, request_gap=0.02)
        self.wire = NaeBackupTransport(self.path, timeout=timeout, gap=0.02)
        self.poll_seconds, self.operation_seconds = poll_seconds, operation_seconds
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        retained_directory(self.directory)
        self.directory.chmod(0o700)
        self.reviews = {}

    def _write(self, record):
        private_write(self.directory / (record["operation_id"] + ".json"), encoded(record))

    def _available(self, target):
        if shutil.disk_usage(self.directory).free < MAX_TOTAL_BYTES + 4 * 1024 * 1024:
            raise ValueError(
                "Insufficient private storage for a bounded NAE capture; no backup started."
            )
        records = list(self.directory.glob("*.json"))
        if len(records) >= 128:
            raise ValueError(
                "NAE capture journal capacity reached; retain evidence before maintenance."
            )
        for path in records:
            row = json.loads(read_private(path, 1024 * 1024))
            if row.get("target") == target and row.get("status") in UNRESOLVED:
                raise ValueError("An earlier NAE backup outcome is unresolved; reconcile it first.")

    async def _identity(self, session, options):
        row = {}
        for prop in IDENTITY:
            value = await self.path._read(session, options.device, prop)
            row[prop] = str(value) if isinstance(value, ObjectIdentifier) else json_value(value)
        if row["object-identifier"] != options.device or row["vendor-identifier"] != 5:
            raise ValueError(
                "The responding Device does not match the selected Johnson Controls NAE."
            )
        if not str(row["model-name"]).upper().startswith(("MS-NAE", "NAE")):
            raise ValueError("This first supervisory profile admits native NAE models only.")
        services = row["protocol-services-supported"]
        if (
            not isinstance(services, list)
            or len(services) <= 20
            or not all(services[i] for i in (6, 20))
        ):
            raise ValueError("The NAE does not advertise AtomicReadFile and ReinitializeDevice.")
        if not row["firmware-revision"] or type(row["database-revision"]) is not int:
            raise ValueError("Native firmware and database revision are required.")
        return row

    async def _state(self, session, device):
        return int(await self.path._read(session, device, "backup-and-restore-state"))

    async def _file_list(self, session, device):
        count = int(await self.path._read(session, device, "configuration-files", 0))
        if not 1 <= count <= MAX_FILES:
            raise ValueError(
                "Active backup did not expose a bounded nonempty Configuration_Files array."
            )
        values = []
        for index in range(1, count + 1):
            obj = ObjectIdentifier(
                await self.path._read(session, device, "configuration-files", index)
            )
            if int(obj[0]) != 10 or not 0 <= obj[1] <= 4194302 or str(obj) in values:
                raise ValueError(
                    "Configuration_Files contains invalid or duplicate File identities."
                )
            values.append(str(obj))
        if int(await self.path._read(session, device, "configuration-files", 0)) != count:
            raise ValueError("Configuration_Files changed during acquisition.")
        return values

    async def _ready(self, session, device, expected, seconds):
        end = time.monotonic() + seconds
        while True:
            try:
                state = await self._state(session, device)
            except (ValueError, TimeoutError, OSError, ErrorRejectAbortNack):
                # The standard permits temporary unresponsiveness during the
                # reported preparation interval, never another lifecycle send.
                if time.monotonic() >= end:
                    raise
            else:
                if state == expected:
                    return
                if state not in (1, 2):
                    raise ValueError(
                        f"NAE backup state {state} differs from expected state {expected}."
                    )
                if time.monotonic() >= end:
                    raise ValueError("NAE backup preparation exceeded the reviewed time bound.")
            await asyncio.sleep(self.poll_seconds)

    async def prepare(self, **target):
        options = DeviceDetailsRequest(**target)
        target = options.model_dump()
        self._available(target)
        async with self.path._path(options) as session:
            PropertyEvidence.pin(session, options.router)
            identity = await self._identity(session, options)
            if await self._state(session, options.device) != 0:
                raise ValueError("The NAE is already in a backup/restore session.")
            preparation = int(
                await self.path._read(session, options.device, "backup-preparation-time")
            )
            failure_timeout = int(
                await self.path._read(session, options.device, "backup-failure-timeout")
            )
            system_status = int(await self.path._read(session, options.device, "system-status"))
            if (
                not 0 <= preparation <= 120
                or not 1 <= failure_timeout <= 3600
                or system_status != 0
            ):
                raise ValueError(
                    "NAE status/timing is outside this initial operational capture profile."
                )
            if await self._identity(session, options) != identity:
                raise ValueError(
                    "NAE identity or database revision changed during review preparation."
                )
            key = secrets.token_hex(24)
            review = {
                "profile": PROFILE,
                "operation_id": secrets.token_hex(16),
                "target": target,
                "identity": identity,
                "connector_config": copy.deepcopy(session["config"]),
                "backup_preparation_seconds": preparation,
                "backup_failure_timeout_seconds": failure_timeout,
                "capture_timeout_seconds": self.operation_seconds,
                "system_status": system_status,
                "effects": {
                    "state_commands": ["start-backup", "end-backup"],
                    "configuration_file_writes": False,
                    "field_point_commands": False,
                    "engine_control_may_pause": True,
                    "restart_command": False,
                },
                "editing_available": False,
                "restore_available": False,
            }
            self.reviews[key] = (copy.deepcopy(review), time.monotonic() + 180, session["app"])
            while len(self.reviews) > 16:
                self.reviews.pop(next(iter(self.reviews)))
            return {
                **review,
                "review_sha256": seal(review),
                "token": key,
                "expires_in_seconds": 180,
            }

    async def _read_file(self, session, identifier, *, chunk, destination, budget):
        metadata = {}
        for prop in (
            "object-identifier",
            "object-name",
            "file-type",
            "file-access-method",
            "file-size",
        ):
            try:
                value = await self.path._read(session, identifier, prop)
            except (ValueError, ErrorRejectAbortNack) as exc:
                if prop != "file-size" or not any(
                    code in str(exc) for code in ("unknown-file-size", "unknownFileSize")
                ):
                    raise
                metadata[prop] = None
                continue
            metadata[prop] = int(value) if prop == "file-size" else str(value)
        if (
            metadata["object-identifier"] != identifier
            or metadata["file-access-method"] != "stream-access"
        ):
            raise ValueError("Native configuration File identity/access method is unsupported.")
        size = metadata["file-size"]
        if size is not None and (type(size) is not int or not 0 <= size <= MAX_FILE_BYTES):
            raise ValueError("Native configuration File size exceeds its capture bound.")
        data = bytearray()
        for _ in range(MAX_FILE_BYTES // chunk + 2):
            request = AtomicReadFileRequest(
                fileIdentifier=ObjectIdentifier(identifier),
                accessMethod=AtomicReadFileRequestAccessMethodChoice(
                    streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                        fileStartPosition=len(data), requestedOctetCount=chunk
                    )
                ),
            )
            reply = await self.wire.exchange(session, request, AtomicReadFileACK)
            access = reply.accessMethod.streamAccess
            if access is None or int(access.fileStartPosition) != len(data):
                raise ValueError(
                    "Native configuration File response has a different stream offset."
                )
            block = bytes(access.fileData)
            if (
                len(block) > chunk
                or len(data) + len(block) > (size if size is not None else MAX_FILE_BYTES)
                or budget[0] + len(block) > MAX_TOTAL_BYTES
            ):
                raise ValueError(
                    "Native configuration File exceeded its advertised size/capture budget."
                )
            data.extend(block)
            budget[0] += len(block)
            if reply.endOfFile:
                if size is not None and len(data) != size:
                    raise ValueError(
                        "Native configuration File EOF differs from its advertised size."
                    )
                private_write(destination, bytes(data))
                return {
                    **metadata,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "saved_file": destination.name,
                }
            if not block:
                raise ValueError("Native configuration File made no progress before EOF.")
        raise ValueError("Native configuration File exceeded its sequential read budget.")

    async def capture(self, *, token, review_sha256, allow_backup_mode, password=None):
        if allow_backup_mode is not True:
            raise ValueError("Explicit acceptance of the reviewed NAE backup mode is required.")
        retained = self.reviews.pop(token, None)
        if retained is None:
            raise ValueError("NAE capture review is unavailable or already consumed.")
        review, expires, app = retained
        if expires < time.monotonic() or seal(review) != review_sha256:
            raise ValueError("NAE capture review expired or changed.")
        if self.bacnet.require() is not app or self.bacnet.config != review["connector_config"]:
            raise ValueError("NAE capture interface changed after review.")
        if password is not None and (
            type(password) is not str
            or not 1 <= len(password) <= 20
            or any(c in password for c in "\x00\r\n")
        ):
            raise ValueError("BACnet backup credentials exceed this protocol's password profile.")
        options = DeviceDetailsRequest(**review["target"])
        with file_lock(
            self.directory / "capture.lock",
            timeout=0,
            busy="Another native NAE capture owns this journal.",
        ):
            self._available(review["target"])
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                if (
                    await self._identity(session, options) != review["identity"]
                    or await self._state(session, options.device) != 0
                ):
                    raise ValueError("NAE identity, revision or backup state changed after review.")
                for prop, key in (
                    ("backup-preparation-time", "backup_preparation_seconds"),
                    ("backup-failure-timeout", "backup_failure_timeout_seconds"),
                    ("system-status", "system_status"),
                ):
                    if int(await self.path._read(session, options.device, prop)) != review[key]:
                        raise ValueError(
                            "NAE backup timing or operational status changed after review."
                        )
                record = {**review, "created_at": utc(), "status": "start_intent", "files": []}
                self._write(record)
                started, failure = False, None

                def phase(value):
                    record.update(status=value, updated_at=utc())
                    self._write(record)

                try:
                    async with asyncio.timeout(review["capture_timeout_seconds"]):
                        await self.wire.state(
                            session,
                            "start-backup",
                            password=password,
                            before_send=lambda _: phase("start_sent"),
                        )
                        started = True
                        phase("backup_active")
                        await self._ready(
                            session, options.device, 2, review["backup_preparation_seconds"] + 5
                        )
                        files = await self._file_list(session, options.device)
                        directory = self.directory / review["operation_id"]
                        directory.mkdir(mode=0o700)
                        local_max = int(session["app"].device_object.maxApduLengthAccepted)
                        chunk = min(
                            1024,
                            local_max - 64,
                            review["identity"]["max-apdu-length-accepted"] - 64,
                        )
                        if chunk < 32:
                            raise ValueError(
                                "The native APDU size cannot carry bounded File chunks."
                            )
                        budget = [0]
                        for identifier in files:
                            if await self._state(session, options.device) != 2:
                                raise ValueError(
                                    "The NAE left its owned backup session during capture."
                                )
                            dest = directory / (str(ObjectIdentifier(identifier)[1]) + ".bin")
                            record["files"].append(
                                await self._read_file(
                                    session,
                                    identifier,
                                    chunk=chunk,
                                    destination=dest,
                                    budget=budget,
                                )
                            )
                            self._write(record)
                        if (
                            await self._file_list(session, options.device) != files
                            or await self._identity(session, options) != review["identity"]
                        ):
                            raise ValueError("NAE configuration identities changed during capture.")
                except BaseException as exc:
                    failure = exc
                    if not started and isinstance(exc.__cause__, ErrorRejectAbortNack):
                        phase("start_rejected")
                # An acknowledged start owns exactly one end. An uncertain start
                # never guesses ownership, retries or terminates someone else's session.
                if started:

                    def cleanup_phase(value):
                        # Closing an acknowledged backup is still needed if
                        # local storage fails. Do not let a full disk strand
                        # the engine in backup mode before its timeout.
                        try:
                            phase(value)
                        except (OSError, ValueError) as exc:
                            record["journal_error_type"] = type(exc).__name__

                    try:
                        cleanup_phase("end_intent")
                        async with asyncio.timeout(12):
                            await self.wire.state(
                                session,
                                "end-backup",
                                password=password,
                                before_send=lambda _: cleanup_phase("end_sent"),
                            )
                            await self._ready(session, options.device, 0, 4)
                            if (
                                await self._identity(session, options) != review["identity"]
                                or int(
                                    await self.path._read(session, options.device, "system-status")
                                )
                                != review["system_status"]
                            ):
                                raise ValueError(
                                    "NAE identity/status after backup differs from the original."
                                )
                        phase(
                            "capture_failed_closed" if failure is not None else "capture_verified"
                        )
                    except BaseException as cleanup:
                        record["cleanup_error_type"] = type(cleanup).__name__
                        self._write(record)
                        raise ValueError(
                            "Ending NAE backup is unconfirmed; retained journal blocks another capture."
                        ) from None
                if failure is not None:
                    # Request bodies/passwords and arbitrary exception payloads
                    # are not copied into local recovery records.
                    record["failure_type"] = type(failure).__name__
                    self._write(record)
                    raise failure
                return copy.deepcopy(record)

    async def reconcile(self, operation_id):
        if (
            type(operation_id) is not str
            or len(operation_id) != 32
            or any(c not in "0123456789abcdef" for c in operation_id)
        ):
            raise ValueError("Use the exact retained NAE capture operation identifier.")
        with file_lock(
            self.directory / "capture.lock",
            timeout=0,
            busy="Another native NAE capture owns this journal.",
        ):
            record = json.loads(
                read_private(self.directory / (operation_id + ".json"), 1024 * 1024)
            )
            options = DeviceDetailsRequest(**record["target"])
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                current = await self._identity(session, options)
                state = await self._state(session, options.device)
                system_status = int(await self.path._read(session, options.device, "system-status"))
            if current != record["identity"] or system_status != record["system_status"]:
                raise ValueError(
                    "NAE identity/revision differs; do not infer recovery from an idle state."
                )
            result = {
                "operation_id": operation_id,
                "backup_state": state,
                "system_status": system_status,
                "read_only": True,
                "capture_verified": record["status"] == "capture_verified",
            }
            if state == 0 and record["status"] in UNRESOLVED:
                record.update(status="closed_by_readback_capture_unverified", reconciled_at=utc())
                self._write(record)
            return result
