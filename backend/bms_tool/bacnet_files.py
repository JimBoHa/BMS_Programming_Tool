"""Read existing BACnet File objects without starting a device backup session.

The saved bytes are opaque device-file evidence, not a generated native CAF or
a verified coherent backup. No private transfer, reinitialization or write
service is issued. Record-access captures preserve every record boundary.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import math
import os
import secrets
import threading
import time
import zipfile
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from bacpypes3.apdu import (
    AtomicReadFileACK,
    AtomicReadFileRequest,
    ErrorRejectAbortNack,
    ReadPropertyACK,
    ReadPropertyRequest,
)
from bacpypes3.basetypes import (
    AtomicReadFileRequestAccessMethodChoice,
    AtomicReadFileRequestAccessMethodChoiceRecordAccess,
    AtomicReadFileRequestAccessMethodChoiceStreamAccess,
    DateTime,
    FileAccessMethod,
)
from bacpypes3.constructeddata import ArrayOf
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier, Unsigned

from .bacnet_exchange import confirmed_exchange
from .file_access import file_lock, open_regular, regular_file, storage_profile, sync_directory

PROFILE = "bacnet-opaque-file/1"
SCOPE = "Existing BACnet File object bytes only; not CAF conversion or a coherent native application backup."
MAX_BYTES = 2 * 1024 * 1024
MAX_FILES = 16
MAX_OBJECTS = 512
MAX_RECORDS = 4096
MAX_PAGES = 8192
MAX_CAPTURES = 32
MAX_STORAGE = 32 * 1024 * 1024


def _json(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _oid(value, kind):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("An explicit BACnet object identifier is required.")
    try:
        result = ObjectIdentifier(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid BACnet object identifier.") from exc
    if int(result[0]) != kind or not 0 <= result[1] <= 4194302:
        raise ValueError("Select an existing Device or File object of the requested type.")
    return str(result)


def _identifier(value):
    if (
        not isinstance(value, str)
        or len(value) != 32
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("Invalid BACnet file inspection/capture identifier.")
    return value


def _bounded_receipt(value):
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 16 or count > 50000:
            raise ValueError("Saved File receipt exceeds its nesting/element profile.")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Saved File receipt contains nonfinite numeric metadata.")


class BacnetFiles:
    def __init__(self, bacnet, store, *, timeout=3.0, operation_timeout=120.0, request_gap=0.05):
        for value, low, high in (
            (timeout, 0.05, 6),
            (operation_timeout, timeout, 120),
            (request_gap, 0.01, 1),
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError("File request/deadline/throttle exceeds its bounded profile.")
        self.bacnet, self.store = bacnet, store
        self.timeout, self.operation_timeout, self.request_gap = (
            timeout,
            operation_timeout,
            request_gap,
        )
        self.directory = Path(store.directory) / "bacnet-files"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self._inspections = OrderedDict()
        self._memory_lock = threading.RLock()

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "read_only": True,
            "auto_poll": False,
            "storage": storage_profile(),
            "native_caf": False,
            "limits": {
                "file_bytes": MAX_BYTES,
                "configuration_files": MAX_FILES,
                "object_list": MAX_OBJECTS,
                "records": MAX_RECORDS,
                "pages": MAX_PAGES,
                "operation_seconds": self.operation_timeout,
                "request_seconds": self.timeout,
                "request_gap_seconds": self.request_gap,
                "captures": MAX_CAPTURES,
                "saved_bytes": MAX_STORAGE,
            },
        }

    def _guard(self, session):
        if self.bacnet.require() is not session["app"] or self.bacnet.config != session["config"]:
            raise ValueError(
                "BACnet application or connection configuration changed; inspect again."
            )
        if self.bacnet.target_address(session["address"]) != session["target"]:
            raise ValueError("BACnet file target address changed; inspect again.")

    async def _exchange(self, session, request, expected):
        self._guard(session)
        delay = self.request_gap - (time.monotonic() - session.get("last_request", 0))
        if delay > 0:
            await asyncio.sleep(delay)
        self._guard(session)
        session["last_request"] = time.monotonic()
        request.pduDestination = session["target"]
        app = session["app"]
        try:
            reply = await asyncio.wait_for(confirmed_exchange(app, request), self.timeout)
            self._guard(session)
            if isinstance(reply, ErrorRejectAbortNack):
                raise ValueError("BACnet file service rejected: " + str(reply))
            if not isinstance(reply, expected) or reply.pduSource != session["target"]:
                raise ValueError("BACnet file response source/service does not match its request.")
            return reply
        except ErrorRejectAbortNack as exc:
            raise ValueError("BACnet file service rejected: " + str(exc)) from exc

    async def _property(self, session, obj, prop, datatype, index=None):
        request = ReadPropertyRequest(
            objectIdentifier=obj,
            propertyIdentifier=prop,
            **({"propertyArrayIndex": index} if index is not None else {}),
        )
        reply = await self._exchange(session, request, ReadPropertyACK)
        if (
            reply.objectIdentifier != ObjectIdentifier(obj)
            or reply.propertyIdentifier != request.propertyIdentifier
            or reply.propertyArrayIndex != index
        ):
            raise ValueError("BACnet file metadata object/property/index mismatch.")
        if len(reply.propertyValue.tagList.encode().pduData) > 4096:
            raise ValueError("BACnet file metadata exceeds its bounded profile.")
        return reply.propertyValue.cast_out(datatype)

    async def _identity(self, session, device):
        identity = {}
        for prop, datatype in (
            ("object-identifier", ObjectIdentifier),
            ("object-name", CharacterString),
            ("vendor-identifier", Unsigned),
            ("model-name", CharacterString),
            ("firmware-revision", CharacterString),
            ("max-apdu-length-accepted", Unsigned),
        ):
            value = await self._property(session, device, prop, datatype)
            identity[prop] = int(value) if datatype is Unsigned else str(value)
        if (
            identity["object-identifier"] != device
            or not 50 <= identity["max-apdu-length-accepted"] <= 1476
            or not 0 <= identity["vendor-identifier"] <= 65535
        ):
            raise ValueError(
                "Device identity or maximum APDU length is outside the file-read profile."
            )
        return identity

    async def _file_list(self, session, device):
        count = int(await self._property(session, device, "configuration-files", Unsigned, 0))
        if count > MAX_FILES:
            raise ValueError(
                "Device configuration-files exceeds the16-file profile; no guessed selection is made."
            )
        files = []
        for index in range(1, count + 1):
            identifier = str(
                await self._property(
                    session, device, "configuration-files", ObjectIdentifier, index
                )
            )
            identifier = _oid(identifier, 10)
            if identifier in files:
                raise ValueError(
                    "Device configuration-files contains duplicate File object identifiers."
                )
            files.append(identifier)
        return files

    async def _advertised_files(self, session, device, configuration_files, maximum):
        if configuration_files:
            return list(configuration_files), None, None
        count = int(await self._property(session, device, "object-list", Unsigned, 0))
        if count > MAX_OBJECTS:
            raise ValueError(
                "Empty configuration-files and object-list exceeds the 512-object fallback "
                "profile. Use object inventory to identify File objects; no guessed selection is made."
            )
        local_maximum = int(session["app"].device_object.maxApduLengthAccepted)
        array_limit = min(85, max(0, (min(local_maximum, maximum) - 32) // 5))
        if count <= array_limit:
            values = list(
                await self._property(session, device, "object-list", ArrayOf(ObjectIdentifier))
            )
            if len(values) != count:
                raise ValueError("Device object-list array length differs from its original count.")
        else:
            values = [
                await self._property(session, device, "object-list", ObjectIdentifier, index)
                for index in range(1, count + 1)
            ]
        files = []
        seen = set()
        for value in values:
            identifier = str(value)
            if not 0 <= value[1] <= 4194302 or identifier in seen:
                raise ValueError(
                    "Device object-list contains invalid or duplicate object identifiers."
                )
            seen.add(identifier)
            if int(value[0]) != 10:
                continue
            identifier = _oid(identifier, 10)
            if len(files) == MAX_FILES:
                raise ValueError("Device object-list exceeds the 16-File fallback profile.")
            files.append(identifier)
        if int(await self._property(session, device, "object-list", Unsigned, 0)) != count:
            raise ValueError("Device object-list length changed during File discovery.")
        return (
            sorted(files, key=lambda identifier: int(ObjectIdentifier(identifier)[1])),
            count,
            _hash([str(value) for value in values]),
        )

    async def _metadata(self, session, identifier):
        result = {"object_id": identifier}
        for prop, datatype in (
            ("object-identifier", ObjectIdentifier),
            ("object-name", CharacterString),
            ("file-type", CharacterString),
            ("file-size", Unsigned),
            ("read-only", Boolean),
            ("file-access-method", FileAccessMethod),
            ("modification-date", DateTime),
        ):
            value = await self._property(session, identifier, prop, datatype)
            result[prop.replace("-", "_")] = (
                {"date": list(value.date), "time": list(value.time)}
                if datatype is DateTime
                else bool(value)
                if datatype is Boolean
                else int(value)
                if datatype is Unsigned
                else str(value)
            )
        if result["object_identifier"] != identifier:
            raise ValueError("File object identity differs from its requested identifier.")
        if not 0 <= result["file_size"] <= 4294967295:
            raise ValueError("File size exceeds its standard Unsigned32 range.")
        try:
            result["description"] = str(
                await self._property(session, identifier, "description", CharacterString)
            )
        except (ValueError, ErrorRejectAbortNack) as exc:
            if "unknown-property" not in str(exc) and "unknownProperty" not in str(exc):
                raise
            result["description"] = None
        result["record_count"] = None
        if result["file_access_method"] == "record-access":
            result["record_count"] = int(
                await self._property(session, identifier, "record-count", Unsigned)
            )
        result["read_supported"] = (
            result["file_access_method"] in {"stream-access", "record-access"}
            and result["file_size"] <= MAX_BYTES
            and (result["record_count"] or 0) <= MAX_RECORDS
        )
        result["read_reason"] = (
            "Existing file metadata is within the opaque read profile."
            if result["read_supported"]
            else "File type/size/record count exceeds the supported opaque read profile."
        )
        result["metadata_sha256"] = _hash(result)
        return result

    def _session(self, address):
        if not isinstance(address, str) or not 1 <= len(address) <= 256:
            raise ValueError("An explicit unicast BACnet address is required.")
        return {
            "app": self.bacnet.require(),
            "config": copy.deepcopy(self.bacnet.config),
            "address": address,
            "target": self.bacnet.target_address(address),
        }

    async def inspect_config(self, address, device):
        device = _oid(device, 8)
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.bacnet.lock:
                    session = self._session(address)
                    identity = await self._identity(session, device)
                    configuration_files = await self._file_list(session, device)
                    discovered = await self._advertised_files(
                        session, device, configuration_files, identity["max-apdu-length-accepted"]
                    )
                    identifiers, object_list_count, object_list_sha256 = discovered
                    files = [
                        await self._metadata(session, identifier) for identifier in identifiers
                    ]
                    if (
                        await self._identity(session, device) != identity
                        or await self._file_list(session, device) != configuration_files
                        or await self._advertised_files(
                            session,
                            device,
                            configuration_files,
                            identity["max-apdu-length-accepted"],
                        )
                        != discovered
                    ):
                        raise ValueError(
                            "Device identity/configuration-files/advertised File objects changed during inspection."
                        )
                    report = {
                        "id": secrets.token_hex(16),
                        "profile": PROFILE,
                        "scope": SCOPE,
                        "target": {"address": str(session["target"]), "device": device},
                        "connector_config": session["config"],
                        "device_identity": identity,
                        "configuration_files": configuration_files,
                        "discovery_source": (
                            "configuration-files" if configuration_files else "object-list"
                        ),
                        "advertised_files": identifiers,
                        "object_list_count": object_list_count,
                        "object_list_sha256": object_list_sha256,
                        "files": files,
                        "inspected_at": datetime.now(UTC).isoformat(),
                        "native_caf": False,
                    }
                    with self._memory_lock:
                        self._inspections[report["id"]] = (copy.deepcopy(report), session["app"])
                        while len(self._inspections) > 8:
                            self._inspections.popitem(last=False)
                    return report
        except TimeoutError as exc:
            raise ValueError(
                "BACnet configuration-file inspection timed out; no file was read."
            ) from exc
        except (DecodingError, InvalidTag, TypeError, AttributeError) as exc:
            raise ValueError("Malformed BACnet configuration-file metadata.") from exc

    async def read_raw_file(self, inspection_id, object_id, metadata_sha256):
        inspection_id, object_id = _identifier(inspection_id), _oid(object_id, 10)
        with self._memory_lock:
            original = self._inspections.get(inspection_id)
            if original is None:
                raise ValueError("File inspection expired; inspect the connected device again.")
            inspected, inspected_app = copy.deepcopy(original[0]), original[1]
        expected = next((row for row in inspected["files"] if row["object_id"] == object_id), None)
        if (
            expected is None
            or expected["metadata_sha256"] != metadata_sha256
            or not expected["read_supported"]
        ):
            raise ValueError("File metadata guard does not match a readable inspected File object.")
        data, boundaries, pages = bytearray(), [], 0
        started = datetime.now(UTC).isoformat()
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.bacnet.lock:
                    session = self._session(inspected["target"]["address"])
                    if (
                        session["app"] is not inspected_app
                        or session["config"] != inspected["connector_config"]
                    ):
                        raise ValueError(
                            "BACnet interface changed since inspection; inspect again."
                        )

                    async def verify():
                        if (
                            await self._identity(session, inspected["target"]["device"])
                            != inspected["device_identity"]
                            or await self._file_list(session, inspected["target"]["device"])
                            != inspected["configuration_files"]
                            or (
                                await self._advertised_files(
                                    session,
                                    inspected["target"]["device"],
                                    inspected["configuration_files"],
                                    inspected["device_identity"]["max-apdu-length-accepted"],
                                )
                            )
                            != (
                                inspected["advertised_files"],
                                inspected["object_list_count"],
                                inspected["object_list_sha256"],
                            )
                            or await self._metadata(session, object_id) != expected
                        ):
                            raise ValueError(
                                "Device identity, File metadata or original size changed (including advertised File objects); no capture accepted."
                            )

                    await verify()
                    local_max = int(session["app"].device_object.maxApduLengthAccepted)
                    chunk = min(
                        1024,
                        inspected["device_identity"]["max-apdu-length-accepted"] - 32,
                        local_max - 32,
                    )
                    if chunk < 1:
                        raise ValueError(
                            "Known APDU capacities cannot fit a bounded file response."
                        )
                    while pages < MAX_PAGES:
                        stream = expected["file_access_method"] == "stream-access"
                        start = len(data) if stream else len(boundaries)
                        selection = (
                            AtomicReadFileRequestAccessMethodChoice(
                                streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                                    fileStartPosition=start, requestedOctetCount=chunk
                                )
                            )
                            if stream
                            else AtomicReadFileRequestAccessMethodChoice(
                                recordAccess=AtomicReadFileRequestAccessMethodChoiceRecordAccess(
                                    fileStartRecord=start, requestedRecordCount=1
                                )
                            )
                        )
                        reply = await self._exchange(
                            session,
                            AtomicReadFileRequest(fileIdentifier=object_id, accessMethod=selection),
                            AtomicReadFileACK,
                        )
                        pages += 1
                        access = reply.accessMethod
                        if stream:
                            if (
                                access.streamAccess is None
                                or access.recordAccess is not None
                                or access.streamAccess.fileStartPosition != start
                            ):
                                raise ValueError(
                                    "AtomicReadFile stream response mode/start position mismatch."
                                )
                            block = bytes(access.streamAccess.fileData)
                            if len(block) > chunk or (not block and not reply.endOfFile):
                                raise ValueError(
                                    "AtomicReadFile stream response exceeded its request or made no progress."
                                )
                            data.extend(block)
                        else:
                            value = access.recordAccess
                            if (
                                value is None
                                or access.streamAccess is not None
                                or value.fileStartRecord != start
                            ):
                                raise ValueError(
                                    "AtomicReadFile record response mode/start record mismatch."
                                )
                            records = list(value.fileRecordData)
                            if (
                                value.returnedRecordCount != len(records)
                                or len(records) > 1
                                or (not records and not reply.endOfFile)
                            ):
                                raise ValueError(
                                    "AtomicReadFile returned record count/progress differs from request."
                                )
                            for record in records:
                                raw = bytes(record)
                                if len(raw) > chunk:
                                    raise ValueError(
                                        "A File record exceeds the conservative unsegmented response profile."
                                    )
                                boundaries.append(
                                    {
                                        "record": len(boundaries),
                                        "offset": len(data),
                                        "length": len(raw),
                                    }
                                )
                                data.extend(raw)
                        if (
                            len(data) > MAX_BYTES
                            or len(data) > expected["file_size"]
                            or len(boundaries) > MAX_RECORDS
                        ):
                            raise ValueError(
                                "AtomicReadFile data exceeds the inspected size/resource profile."
                            )
                        if reply.endOfFile:
                            if len(data) != expected["file_size"] or (
                                not stream and len(boundaries) != expected["record_count"]
                            ):
                                raise ValueError(
                                    "AtomicReadFile EOF disagrees with the inspected file size/record count."
                                )
                            break
                    else:
                        raise ValueError(
                            "AtomicReadFile page limit reached; incomplete bytes were not saved."
                        )
                    await verify()
                    self._guard(session)
                    report = {
                        "id": secrets.token_hex(16),
                        "profile": PROFILE,
                        "scope": SCOPE,
                        "source_kind": "device-file",
                        "target": inspected["target"] | {"object_id": object_id},
                        "connector_config": inspected["connector_config"],
                        "device_identity": inspected["device_identity"],
                        "configuration_files": inspected["configuration_files"],
                        "discovery_source": inspected["discovery_source"],
                        "advertised_files": inspected["advertised_files"],
                        "object_list_count": inspected["object_list_count"],
                        "object_list_sha256": inspected["object_list_sha256"],
                        "metadata": expected,
                        "inspection_id": inspection_id,
                        "read_at": started,
                        "received_at": datetime.now(UTC).isoformat(),
                        "complete": True,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "access_method": expected["file_access_method"],
                        "record_boundaries": boundaries,
                        "pages": pages,
                        "native_caf": False,
                        "consistency": "Metadata stable before/after; no backup session started, not an atomic snapshot.",
                    }
        except TimeoutError as exc:
            raise ValueError(
                f"BACnet file read timed out after {len(data)} bytes; no complete capture was saved."
            ) from exc
        except (DecodingError, InvalidTag, TypeError, AttributeError) as exc:
            raise ValueError(
                "Malformed AtomicReadFile metadata/response; no complete capture was saved."
            ) from exc
        await asyncio.to_thread(self._save, report, bytes(data))
        return report

    @contextmanager
    def _capture_lock(self):
        with file_lock(
            self.directory / ".capture.lock", timeout=2,
            busy="File capture storage is busy; no existing capture was changed.",
            unavailable="File capture storage lock is unavailable.",
        ):
            yield

    def _save(self, report, data):
        # Reserve a unique capture name with O_EXCL. Nothing can overwrite an
        # earlier capture. No payload/capture is added to a source CAF or Git.
        receipt = _json(report).encode()
        wrapper = io.BytesIO()
        with zipfile.ZipFile(wrapper, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.comment = hashlib.sha256(receipt).hexdigest().encode()
            archive.writestr("receipt.json", receipt)
            archive.writestr("data.bin", data)
        content = wrapper.getvalue()
        with self._capture_lock():
            existing = list(self.directory.glob("*.capture"))
            if any(not regular_file(path.lstat()) for path in existing):
                raise ValueError("Saved file captures must be regular files.")
            if (
                len(existing) >= MAX_CAPTURES
                or sum(path.stat().st_size for path in existing) + len(content) > MAX_STORAGE
            ):
                raise ValueError(
                    "BACnet file capture capacity reached; no existing capture was removed."
                )
            path = self.directory / (report["id"] + ".capture")
            temporary = self.directory / ("." + report["id"] + "." + secrets.token_hex(6) + ".tmp")
            fd = open_regular(temporary, writable=True, create=True, exclusive=True)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, path)
                sync_directory(self.directory)
            finally:
                temporary.unlink(missing_ok=True)
        self.store.record(
            "bacnet.file.capture",
            {
                "id": report["id"],
                "bytes": report["bytes"],
                "sha256": report["sha256"],
                "native_caf": False,
            },
        )

    def _load(self, identifier):
        identifier = _identifier(identifier)
        path = self.directory / (identifier + ".capture")
        try:
            fd = open_regular(path)
        except OSError as exc:
            raise ValueError("BACnet file capture is unavailable or not a regular file.") from exc
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not regular_file(info) or info.st_size > MAX_BYTES + 512 * 1024:
                raise ValueError("BACnet file capture exceeds its regular-file size profile.")
            raw = stream.read(MAX_BYTES + 512 * 1024 + 1)
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                if [item.filename for item in infos] != ["receipt.json", "data.bin"] or any(
                    item.file_size > MAX_BYTES or item.compress_type != zipfile.ZIP_STORED
                    for item in infos
                ):
                    raise ValueError("Unexpected BACnet capture container members/size.")
                raw_receipt, data = archive.read("receipt.json"), archive.read("data.bin")
                if hashlib.sha256(raw_receipt).hexdigest().encode() != archive.comment:
                    raise ValueError(
                        "BACnet file receipt checksum differs from its saved evidence."
                    )
                receipt = json.loads(raw_receipt)
        except (
            ValueError,
            zipfile.BadZipFile,
            RuntimeError,
            OSError,
            EOFError,
            RecursionError,
        ) as exc:
            raise ValueError("Invalid saved BACnet file capture.") from exc
        _bounded_receipt(receipt)
        if (
            not isinstance(receipt, dict)
            or receipt.get("id") != identifier
            or receipt.get("profile") != PROFILE
            or type(receipt.get("bytes")) is not int
            or receipt.get("bytes") != len(data)
            or receipt.get("sha256") != hashlib.sha256(data).hexdigest()
            or receipt.get("native_caf") is not False
            or receipt.get("complete") is not True
            or receipt.get("source_kind") != "device-file"
            or not isinstance(receipt.get("access_method"), str)
            or receipt.get("access_method") not in {"stream-access", "record-access"}
            or any(
                not isinstance(receipt.get(key), dict)
                for key in ("target", "connector_config", "device_identity", "metadata")
            )
            or any(
                not isinstance(receipt.get(key), str)
                for key in ("read_at", "received_at", "scope", "consistency")
            )
        ):
            raise ValueError("BACnet file capture integrity check failed.")
        metadata = receipt["metadata"]
        if "discovery_source" in receipt:
            configuration_files = receipt.get("configuration_files")
            advertised_files = receipt.get("advertised_files")
            if any(
                not isinstance(values, list)
                or len(values) > MAX_FILES
                or any(not isinstance(value, str) for value in values)
                for values in (configuration_files, advertised_files)
            ):
                raise ValueError("Saved File discovery evidence is invalid.")
            if (
                len(set(configuration_files)) != len(configuration_files)
                or len(set(advertised_files)) != len(advertised_files)
                or any(_oid(value, 10) != value for value in configuration_files + advertised_files)
                or receipt["target"].get("object_id") not in advertised_files
                or (
                    receipt["discovery_source"] == "configuration-files"
                    and (
                        not configuration_files
                        or advertised_files != configuration_files
                        or receipt.get("object_list_count") is not None
                    )
                )
                or (
                    receipt["discovery_source"] == "object-list"
                    and (
                        configuration_files
                        or type(receipt.get("object_list_count")) is not int
                        or not len(advertised_files) <= receipt["object_list_count"] <= MAX_OBJECTS
                    )
                )
                or receipt["discovery_source"] not in {"configuration-files", "object-list"}
            ):
                raise ValueError("Saved File discovery evidence does not cover the selected File.")
        if (
            any(
                not isinstance(receipt["target"].get(key), str)
                for key in ("address", "device", "object_id")
            )
            or metadata.get("object_id") != receipt["target"]["object_id"]
            or metadata.get("file_size") != len(data)
            or metadata.get("file_access_method") != receipt["access_method"]
            or metadata.get("metadata_sha256")
            != _hash({key: value for key, value in metadata.items() if key != "metadata_sha256"})
        ):
            raise ValueError("BACnet file capture metadata integrity check failed.")
        boundaries = receipt.get("record_boundaries")
        if not isinstance(boundaries, list) or len(boundaries) > MAX_RECORDS:
            raise ValueError("Saved File record boundaries are invalid.")
        position = 0
        for index, row in enumerate(boundaries):
            if (
                not isinstance(row, dict)
                or set(row) != {"record", "offset", "length"}
                or any(type(value) is not int for value in row.values())
                or row["record"] != index
                or row["offset"] != position
                or not 0 <= row["length"] <= len(data) - position
            ):
                raise ValueError("Saved File record boundaries are invalid.")
            position += row["length"]
        if (
            receipt["access_method"] == "record-access"
            and (position != len(data) or len(boundaries) != metadata.get("record_count"))
        ) or (receipt["access_method"] == "stream-access" and boundaries):
            raise ValueError("Saved File record boundaries do not cover their data.")
        return receipt, data

    def capture(self, identifier):
        return self._load(identifier)[0]

    def captures(self):
        rows = []
        paths = sorted(self.directory.glob("*.capture"))
        if len(paths) > MAX_CAPTURES:
            raise ValueError("Saved File capture count exceeds its bounded storage profile.")
        for path in paths:
            report = self.capture(path.stem)
            rows.append(
                {
                    key: report[key]
                    for key in (
                        "id",
                        "target",
                        "bytes",
                        "sha256",
                        "received_at",
                        "access_method",
                        "native_caf",
                    )
                }
            )
        return rows

    def export(self, identifier):
        receipt, data = self._load(identifier)
        if receipt["access_method"] == "stream-access":
            return data, identifier + ".bin", "application/octet-stream"
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("receipt.json", _json(receipt))
            for row in receipt["record_boundaries"]:
                start, size = row["offset"], row["length"]
                archive.writestr(f"records/{row['record']:08d}.bin", data[start : start + size])
        return result.getvalue(), identifier + "-records.zip", "application/zip"
