"""Temco T3 program-slot transfer over the manufacturer's private BACnet service.

This transfers native program images, not BACnet point commands. Only the pinned
37-byte descriptor / five 400-byte block profile is implemented. Real hardware
and power-loss persistence remain unverified; tests use actual BACpypes3 UDP.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import struct
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from bacpypes3.apdu import ConfirmedPrivateTransferACK, ConfirmedPrivateTransferRequest
from bacpypes3.constructeddata import Any
from bacpypes3.errors import InvalidTag
from bacpypes3.primitivedata import Null, OctetString

from .bacnet_exchange import confirmed_exchange
from .file_access import open_regular, sync_directory
from .macros import expand_macros
from .temco import compile_source, import_source

VENDOR = 148  # device identity; private service uses the historical namespace 260
PRIVATE_VENDOR = 260
SERVICE = 1
SLOTS = 16
CHUNK = 400
IMAGE = 2000
DESCRIPTOR = 37
READ_META, READ_CODE, WRITE_META, WRITE_CODE = 7, 16, 107, 116
PROFILE = "temco-t3-private-program/1"
FIRMWARE_PIN = "845973a37b91ac5ddac9c465787f2ab3a5037708"
CLIENT_PIN = "ae9b9d082de93b35ff2ca59eb1d0c06ae04cec9b"
SCOPE = "Manufacturer protocol; loopback emulator tested; physical hardware unverified"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def packet(command: int, slot: int, package: int = 0, body: bytes = b"") -> bytes:
    """Exact packed Str_user_data_header; indices are zero based."""
    if type(slot) is not int or not 0 <= slot < SLOTS:
        raise ValueError("Temco program slot must be 0..15 (zero based).")
    if command not in (READ_META, READ_CODE, WRITE_META, WRITE_CODE):
        raise ValueError("Unsupported Temco program-transfer command.")
    code = command in (READ_CODE, WRITE_CODE)
    if type(package) is not int or not 0 <= package < (5 if code else 1):
        raise ValueError("Program code package must be 0..4; metadata uses package 0.")
    size = CHUNK if code else DESCRIPTOR
    if len(body) != (size if command > 100 else 0):
        raise ValueError("Private-transfer body has the wrong length.")
    return struct.pack("<HBBBH", 7 + len(body), command, slot, slot, size | package << 9) + body


def response_body(payload: bytes, command: int, slot: int, package: int = 0) -> bytes:
    """Read responses in firmware report body length; desktop variants use total."""
    expected = packet(command, slot, package)
    size = CHUNK if command == READ_CODE else DESCRIPTOR
    if len(payload) != size + 7 or payload[2:7] != expected[2:7]:
        raise ValueError("Temco response command/slot/package/size mismatch.")
    if int.from_bytes(payload[:2], "little") not in (size, size + 7):
        raise ValueError("Temco response length field is inconsistent.")
    return payload[7:]


def metadata(raw: bytes) -> dict:
    if len(raw) != DESCRIPTOR or raw[32] not in (0, 1) or raw[33] not in (0, 1):
        raise ValueError("Unsupported Temco descriptor length or run/manual state.")
    size = int.from_bytes(raw[30:32], "little")
    if size >= IMAGE:
        raise ValueError("Existing Temco base-code size exceeds this transfer profile.")
    return {
        "description": raw[:21].split(b"\0", 1)[0].decode("ascii", "replace"),
        "label": raw[21:30].split(b"\0", 1)[0].decode("ascii", "replace"),
        "base_code_bytes": size,
        "running": bool(raw[32]),
        "manual": bool(raw[33]),
    }


class TemcoTransfer:
    def __init__(self, bacnet, store_or_directory=None, *, timeout=1.0, operation_power=None):
        if not 0.05 <= timeout <= 2.0:
            raise ValueError("Private-transfer timeout must be 0.05..2 seconds.")
        self.bacnet = bacnet
        self.store = store_or_directory if hasattr(store_or_directory, "record") else bacnet.store
        directory = getattr(store_or_directory, "directory", store_or_directory)
        self.directory = Path(directory or self.store.directory) / "temco-program-transfers"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.timeout = timeout
        self.operation_power = operation_power
        self.plans = {}
        self.journal = self.directory / "operations.json"
        self.operations = json.loads(self.journal.read_text()) if self.journal.exists() else {}

    def _save(self, path, value):
        temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
        fd = open_regular(temporary, writable=True, create=True, exclusive=True)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            sync_directory(self.directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _record(self, operation, state, **detail):
        row = self.operations.setdefault(operation, {})
        row.update(detail, state=state, updated=datetime.now(UTC).isoformat())
        self._save(self.journal, self.operations)
        self.store.record("temco.program." + state, {"operation": operation, **detail})

    def status(self):
        return {
            "profile": PROFILE,
            "scope": SCOPE,
            "connected": self.bacnet.status()["connected"],
            "slots": SLOTS,
            "image_bytes": IMAGE,
            "chunk_bytes": CHUNK,
            "physical_variables": 128,
            "minimum_accepted_apdu_bytes": 480,
            "private_vendor": PRIVATE_VENDOR,
            "device_vendor": VENDOR,
            "plans": len(self.plans),
            "backups": self.backups(),
            "operations": [{"id": key, **row} for key, row in self.operations.items()],
            "uncertain": [
                key
                for key, row in self.operations.items()
                if row["state"] not in ("complete", "restored", "preflight_failed")
            ],
            "limits": [
                "Exact device/model/firmware and slot required; no JCI support.",
                "Physical profile permits VAR1..128 and requires accepted APDU size >=480 bytes.",
                "Generated Schedule programs require a commissioned calendar host and are refused here.",
                "Stops slot for replacement; outputs are not automatically relinquished.",
                "No atomic swap, controller scan acknowledgement or power-cycle/flash proof.",
                "Host calendar and physical scan-cadence services are not provisioned.",
                "Only program slot image/descriptor backed up; not a whole-device backup.",
            ],
            "source_commits": {"client": CLIENT_PIN, "firmware": FIRMWARE_PIN},
        }

    def backups(self):
        rows = []
        for path in sorted(self.directory.glob("backup-*.json")):
            row = json.loads(path.read_text())
            rows.append(
                {
                    key: row[key]
                    for key in ("id", "created", "target", "image_sha256", "generation", "metadata")
                }
            )
        return rows

    def backup(self, backup_id):
        if (
            not isinstance(backup_id, str)
            or len(backup_id) != 32
            or any(c not in "0123456789abcdef" for c in backup_id)
        ):
            raise ValueError("Invalid Temco backup identifier.")
        path = self.directory / ("backup-" + backup_id + ".json")
        if not path.exists():
            raise ValueError("Temco backup not found.")
        row = json.loads(path.read_text())
        seal = row.get("backup_sha256")
        content = {key: value for key, value in row.items() if key != "backup_sha256"}
        if seal != digest(json.dumps(content, sort_keys=True, allow_nan=False).encode()):
            raise ValueError("Temco backup integrity check failed.")
        image = base64.b64decode(row["image_base64"], validate=True)
        descriptor = base64.b64decode(row["descriptor_base64"], validate=True)
        if (
            row.get("profile") != PROFILE
            or len(image) != IMAGE
            or digest(image) != row["image_sha256"]
            or digest(image + descriptor[:34]) != row["generation"]
        ):
            raise ValueError("Temco backup integrity check failed.")
        metadata(descriptor)
        return row

    async def _identity(self, address, instance, model, firmware):
        if type(instance) is not int or not 0 <= instance <= 4194302:
            raise ValueError("Exact BACnet device instance must be 0..4194302.")
        if (
            not isinstance(model, str)
            or not model.strip()
            or not isinstance(firmware, str)
            or not firmware.strip()
        ):
            raise ValueError("Exact expected model and firmware are required.")
        self.bacnet.target_address(address)
        obj = f"device,{instance}"
        values = []
        for prop in (
            "vendor-identifier",
            "model-name",
            "firmware-revision",
            "max-apdu-length-accepted",
        ):
            values.append(
                await asyncio.wait_for(self.bacnet._read(address, obj, prop), self.timeout)
            )
        if int(values[0]) != VENDOR or str(values[1]) != model or str(values[2]) != firmware:
            raise ValueError("Temco identity/model/firmware differs from the pinned target.")
        if int(values[3]) < 480:
            raise ValueError(
                "Temco program blocks require an accepted BACnet APDU size of at least 480 bytes."
            )
        return {
            "address": str(self.bacnet.target_address(address)),
            "device_instance": instance,
            "vendor_id": VENDOR,
            "model": model,
            "firmware": firmware,
        }

    async def _exchange(self, address, command, slot, package=0, body=b""):
        app = self.bacnet.require()
        target = self.bacnet.target_address(address)
        request = ConfirmedPrivateTransferRequest(
            vendorID=PRIVATE_VENDOR,
            serviceNumber=SERVICE,
            serviceParameters=Any(OctetString(packet(command, slot, package, body))),
            destination=target,
        )
        loop = asyncio.get_running_loop()
        proprietary = loop.create_future()
        name = "do_UnconfirmedPrivateTransferRequest"
        original = getattr(app, name, None)
        had_own = name in app.__dict__

        def decode(apdu, field):
            if (
                apdu.pduSource != target
                or int(apdu.vendorID) != PRIVATE_VENDOR
                or int(apdu.serviceNumber) != SERVICE
            ):
                return None
            value = getattr(apdu, field, None)
            if value is None:
                return b"" if command > 100 else None
            if command > 100:
                # ESP32 firmware returns BACnet NULL for writes, not a header.
                try:
                    value.cast_out(Null)
                    return b""
                except (TypeError, ValueError, InvalidTag):
                    payload = bytes(value.cast_out(OctetString))
                    return b"" if payload == packet(command, slot, package, body) else None
            return response_body(bytes(value.cast_out(OctetString)), command, slot, package)

        async def received(apdu):
            try:
                value = decode(apdu, "serviceParameters")
                if value is not None and not proprietary.done():
                    proprietary.set_result(value)
                    return
            except (ValueError, TypeError, AttributeError, InvalidTag):
                pass  # unrelated/malformed unconfirmed packets cannot satisfy a read
            if original:
                await original(apdu)

        setattr(app, name, received)
        future = None
        try:
            future = asyncio.create_task(confirmed_exchange(app, request))
            done, _ = await asyncio.wait(
                (future, proprietary), timeout=self.timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if proprietary in done:
                return proprietary.result()
            if future in done:
                reply = future.result()
                if (
                    not isinstance(reply, ConfirmedPrivateTransferACK)
                    or reply.apduInvokeID != request.apduInvokeID
                ):
                    raise ValueError("Temco private-transfer request was rejected.")
                result = decode(reply, "resultBlock")
                if result is None:
                    raise ValueError("Temco acknowledgement identity does not match.")
                return result
            raise TimeoutError("Temco private-transfer response timed out.")
        finally:
            # Firmware may answer via unconfirmed service before the confirmed
            # task completes. Cancel AND join our owned dispatch so even a
            # pre-invoke cache lookup cannot send a write after we return.
            if future is not None:
                future.cancel()
                while not future.done():
                    try:
                        await asyncio.shield(future)
                    except asyncio.CancelledError:
                        # A cancelled child is terminal. Repeated cancellation
                        # of the outer operation must still let cleanup finish.
                        if future.done():
                            break
                    except Exception:
                        break
                if not future.cancelled():
                    future.exception()
            proprietary.cancel()
            if had_own:
                setattr(app, name, original)
            else:
                delattr(app, name)

    async def _meta(self, address, slot):
        raw = await self._exchange(address, READ_META, slot)
        metadata(raw)
        return raw

    async def _image(self, address, slot):
        return b"".join([await self._exchange(address, READ_CODE, slot, i) for i in range(5)])

    async def _snapshot(self, address, slot):
        before = await self._meta(address, slot)
        image = await self._image(address, slot)
        # A running program can change local values in its image. Never claim a
        # coherent backup from unmatched reads or ignore a concurrent editor.
        repeated = await self._image(address, slot)
        after = await self._meta(address, slot)
        if image != repeated or before[:34] != after[:34]:
            raise ValueError(
                "Temco slot changed while reading; no coherent backup or plan created."
            )
        if int.from_bytes(image[:2], "little") != int.from_bytes(after[30:32], "little"):
            raise ValueError("Temco descriptor/base-code length differs from its image.")
        return {
            "image": image,
            "descriptor": after,
            "generation": digest(image + after[:34]),
            "metadata": metadata(after),
        }

    async def inspect(self, address, device_instance, slot, *, expected_model, expected_firmware):
        packet(READ_META, slot)
        async with self.bacnet.lock:
            target = await self._identity(
                address, device_instance, expected_model, expected_firmware
            )
            snapshot = await self._snapshot(address, slot)
            return {
                "target": {**target, "slot": slot},
                "metadata": snapshot["metadata"],
                "image_sha256": digest(snapshot["image"]),
                "generation": snapshot["generation"],
                "scope": SCOPE,
            }

    async def _plan(
        self,
        address,
        device_instance,
        slot,
        image,
        *,
        expected_model,
        expected_firmware,
        resume,
        source_sha256=None,
        restored_backup=None,
        desired_running=None,
    ):
        packet(READ_META, slot)
        if type(resume) is not bool:
            raise ValueError("Temco resume requires an explicit Boolean.")
        if len(image) > IMAGE or len(image) < 2 or int.from_bytes(image[:2], "little") >= IMAGE:
            raise ValueError("Native image does not fit this Temco program-slot profile.")
        async with self.bacnet.lock:
            app = self.bacnet.require()
            target = await self._identity(
                address, device_instance, expected_model, expected_firmware
            )
            snapshot = await self._snapshot(address, slot)
            # T3000 checks a 10,000-byte total-code budget on small panels. This
            # conservative profile requires the same budget, even on larger ones.
            budget = await self._budget(address, slot, len(image))
            backup_id = secrets.token_hex(16)
            target = {**target, "slot": slot}
            backup = {
                "id": backup_id,
                "profile": PROFILE,
                "created": datetime.now(UTC).isoformat(),
                "target": target,
                "metadata": snapshot["metadata"],
                "image_sha256": digest(snapshot["image"]),
                "generation": snapshot["generation"],
                "image_base64": base64.b64encode(snapshot["image"]).decode(),
                "descriptor_base64": base64.b64encode(snapshot["descriptor"]).decode(),
            }
            backup["backup_sha256"] = digest(
                json.dumps(backup, sort_keys=True, allow_nan=False).encode()
            )
            self._save(self.directory / ("backup-" + backup_id + ".json"), backup)
            native_bytes = len(image)
            image = image.ljust(IMAGE, b"\0")
            token = secrets.token_urlsafe(24)
            public = {
                "token": token,
                "backup_id": backup_id,
                "target": target,
                "generation": snapshot["generation"],
                "before_sha256": digest(snapshot["image"]),
                "after_sha256": digest(image),
                "compiled_bytes": native_bytes,
                "resume": bool(resume),
                "original_running": snapshot["metadata"]["running"],
                "final_running": bool(
                    resume
                    and (
                        snapshot["metadata"]["running"]
                        if desired_running is None
                        else desired_running
                    )
                ),
                "expires_seconds": 300,
                "scope": SCOPE,
                "source_sha256": source_sha256,
                "restored_backup": restored_backup,
                "program_budget_bytes": budget,
            }
            self.plans[token] = {
                "public": public,
                "app": app,
                "config": dict(self.bacnet.config),
                "created": time.monotonic(),
                "snapshot": snapshot,
                "image": image,
            }
            if len(self.plans) > 32:
                self.plans.pop(next(iter(self.plans)))
            self.store.record(
                "temco.program.plan",
                {key: value for key, value in public.items() if key != "token"},
            )
            return public

    async def _budget(self, address, slot, native_bytes):
        occupied = 0
        for other in range(SLOTS):
            if other != slot:
                occupied += int.from_bytes((await self._meta(address, other))[30:32], "little")
        if occupied + native_bytes > 10_000:
            raise ValueError("Replacement exceeds the conservative 10,000-byte program budget.")
        return occupied + native_bytes

    async def plan_replace(
        self,
        address,
        device_instance,
        slot,
        source,
        *,
        expected_model,
        expected_firmware,
        resume=True,
    ):
        program = expand_macros(import_source(source))
        if any(node.kind == "Schedule" for node in program.nodes):
            raise ValueError(
                "Native Schedule transfer requires a commissioned calendar host; this adapter does not provision one."
            )
        for line in source.splitlines():
            if re.match(r"\s*\d+\s+REM(?:\s|$)", line, re.IGNORECASE):
                continue
            if any(int(match) > 128 for match in re.findall(r"\bVAR(\d+)\b", line, re.IGNORECASE)):
                raise ValueError(
                    "This pinned physical transfer profile supports VAR1..128, not the host VM's 256 variables."
                )
        image = await asyncio.to_thread(compile_source, source)
        return await self._plan(
            address,
            device_instance,
            slot,
            image,
            expected_model=expected_model,
            expected_firmware=expected_firmware,
            resume=resume,
            source_sha256=digest(source.encode()),
        )

    async def plan_restore(
        self,
        backup_id,
        address,
        device_instance,
        slot,
        *,
        expected_model,
        expected_firmware,
        resume=True,
    ):
        saved = self.backup(backup_id)
        target = {
            "address": str(self.bacnet.target_address(address)),
            "device_instance": device_instance,
            "slot": slot,
            "vendor_id": VENDOR,
            "model": expected_model,
            "firmware": expected_firmware,
        }
        if saved["target"] != target:
            raise ValueError(
                "Backup belongs to a different device, firmware, interface address or slot."
            )
        return await self._plan(
            address,
            device_instance,
            slot,
            base64.b64decode(saved["image_base64"]),
            expected_model=expected_model,
            expected_firmware=expected_firmware,
            resume=resume,
            restored_backup=backup_id,
            desired_running=saved["metadata"]["running"],
        )

    async def _run_state(self, address, slot, running, expected_descriptor):
        current = await self._meta(address, slot)
        if current[:30] != expected_descriptor[:30] or current[33] != expected_descriptor[33]:
            raise ValueError("Temco slot identity/manual mode changed during replacement.")
        replacement = current[:32] + bytes([int(running)]) + current[33:]
        if replacement != current:
            await self._exchange(address, WRITE_META, slot, body=replacement)
        verified = await self._meta(address, slot)
        if verified[:34] != replacement[:34]:
            raise ValueError("Temco run-state readback failed.")
        return verified

    async def _write_image(self, address, slot, image, old_image, descriptor):
        expected = bytearray(old_image)
        for package in range(5):
            current_descriptor = await self._meta(address, slot)
            if (
                current_descriptor[32] != 0
                or current_descriptor[:30] != descriptor[:30]
                or current_descriptor[33] != descriptor[33]
            ):
                raise ValueError(
                    "Temco slot resumed or its identity/manual mode changed during transfer."
                )
            if await self._image(address, slot) != bytes(expected):
                raise ValueError("Temco image changed concurrently during transfer.")
            chunk = image[package * CHUNK : (package + 1) * CHUNK]
            await self._exchange(address, WRITE_CODE, slot, package, chunk)
            if await self._exchange(address, READ_CODE, slot, package) != chunk:
                raise ValueError("Temco program chunk readback failed.")
            expected[package * CHUNK : (package + 1) * CHUNK] = chunk
        if await self._image(address, slot) != image:
            raise ValueError("Temco full program-image readback failed.")

    async def apply(self, token):
        async with self.bacnet.lock:
            plan = self.plans.pop(token, None)
            if not plan or time.monotonic() - plan["created"] > 300:
                raise ValueError("Temco plan expired, consumed or unknown; create a fresh plan.")
            if self.bacnet.require() is not plan["app"] or self.bacnet.config != plan["config"]:
                raise ValueError("BACnet connection changed; create a fresh Temco plan.")
            power_scope = (
                self.operation_power.operation("temco-native-apply")
                if self.operation_power is not None
                else nullcontext()
            )
            async with power_scope:
                public = plan["public"]
                target = public["target"]
                address, slot = target["address"], target["slot"]
                operation = secrets.token_hex(16)
                await self._identity(
                    address, target["device_instance"], target["model"], target["firmware"]
                )
                current = await self._snapshot(address, slot)
                if current["generation"] != public["generation"]:
                    raise ValueError(
                        "Temco generation/hash changed; create a fresh plan before writing."
                    )
                await self._budget(address, slot, public["compiled_bytes"])
                # Backup and intent reach fsync before the first stop/write request.
                self.backup(public["backup_id"])
                self._record(
                    operation,
                    "intent",
                    target=target,
                    backup_id=public["backup_id"],
                    before_sha256=public["before_sha256"],
                    after_sha256=public["after_sha256"],
                )
                original = current["image"]
                descriptor = current["descriptor"]
                try:
                    await self._run_state(address, slot, False, descriptor)
                    self._record(operation, "stopped")
                    await self._write_image(address, slot, plan["image"], original, descriptor)
                    self._record(operation, "verified")
                    await self._run_state(address, slot, public["final_running"], descriptor)
                    self._record(operation, "complete")
                    return {
                        "ok": True,
                        "operation": operation,
                        "backup_id": public["backup_id"],
                        "target": target,
                        "image_sha256": public["after_sha256"],
                        "readback_verified": True,
                        "scope": SCOPE,
                        "running": public["final_running"],
                        "power_cycle_persistence_verified": False,
                    }
                except (Exception, asyncio.CancelledError) as error:
                    journal_error = None
                    try:
                        self._record(
                            operation, "uncertain", error=str(error) or type(error).__name__
                        )
                    except Exception as logging_error:
                        journal_error = str(logging_error)
                    # Cancellation must not abandon a half-written slot. Recovery has
                    # its own bounded requests, then reports a durable outcome.
                    recovery = asyncio.create_task(self._recover(plan, operation))
                    outer_cancelled = isinstance(error, asyncio.CancelledError)
                    while True:
                        try:
                            recovered = await asyncio.shield(recovery)
                            break
                        except asyncio.CancelledError:
                            outer_cancelled |= bool(asyncio.current_task().cancelling())
                            if recovery.done():
                                if recovery.cancelled():
                                    recovered = self._recovery_failure(
                                        operation,
                                        "Recovery task cancelled before original-image verification.",
                                    )
                                else:
                                    try:
                                        recovered = recovery.result()
                                    except Exception as recovery_error:
                                        recovered = self._recovery_failure(
                                            operation, str(recovery_error)
                                        )
                                break
                            # Keep the connection lock until bounded recovery ends,
                            # including repeated client/HTTP cancellation.
                            continue
                        except Exception as recovery_error:
                            recovered = self._recovery_failure(operation, str(recovery_error))
                            break
                    result = {
                        "ok": False,
                        "operation": operation,
                        "backup_id": public["backup_id"],
                        "target": target,
                        "error": str(error) or type(error).__name__,
                        "recovery": recovered,
                        "scope": SCOPE,
                    }
                    if journal_error:
                        result["journal_error"] = journal_error
                    if outer_cancelled:
                        raise asyncio.CancelledError from error
                    return result

    def _recovery_failure(self, operation, message):
        result = {"restored": False, "manual_recovery_required": True, "error": message}
        try:
            self._record(operation, "recovery_required", recovery_error=message)
        except Exception as journal_error:
            result["journal_error"] = str(journal_error)
        return result

    async def _recover(self, plan, operation):
        target, snapshot = plan["public"]["target"], plan["snapshot"]
        address, slot = target["address"], target["slot"]
        try:
            if self.bacnet.require() is not plan["app"] or self.bacnet.config != plan["config"]:
                raise ValueError("BACnet connection changed; automatic restore refused.")
            await self._identity(
                address, target["device_instance"], target["model"], target["firmware"]
            )
            current = await self._image(address, slot)
            for package in range(5):
                start = package * CHUNK
                chunk = current[start : start + CHUNK]
                if chunk not in (
                    snapshot["image"][start : start + CHUNK],
                    plan["image"][start : start + CHUNK],
                ):
                    raise ValueError("Unrelated program bytes detected; automatic restore refused.")
            await self._run_state(address, slot, False, snapshot["descriptor"])
            await self._write_image(
                address, slot, snapshot["image"], current, snapshot["descriptor"]
            )
            await self._run_state(
                address, slot, bool(snapshot["descriptor"][32]), snapshot["descriptor"]
            )
            result = {
                "restored": True,
                "image_sha256": digest(snapshot["image"]),
                "readback_verified": True,
            }
            try:
                self._record(operation, "restored")
            except Exception as journal_error:
                result["journal_error"] = str(journal_error)
            return result
        except Exception as error:
            result = {"restored": False, "manual_recovery_required": True, "error": str(error)}
            try:
                self._record(operation, "recovery_required", recovery_error=str(error))
            except Exception as journal_error:
                result["journal_error"] = str(journal_error)
            return result
