"""Reviewed single-attempt I/O transfers with original backup and independent readback."""

import asyncio
import copy
import secrets
import sqlite3
import time

from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned
from fastapi import APIRouter
from pydantic import Field, StrictBool

from .application_preservation import runtime_parameter_changes
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_applications import RESTORE_PREPARATION_SECONDS, NativeCapture
from .native_runtime_io import PROFILE, RuntimeIOEdit, compile_io
from .property_evidence import PropertyEvidence


class IOReview(NativeCapture):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    edit: RuntimeIOEdit


class IOApply(StrictModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    local_io_testing_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


class IOReadback(NativeCapture):
    receipt_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RuntimeIOOperations:
    def __init__(self, native):
        self.native = native
        self.plans = {}

    def source(self, request):
        capture, files = self.native.storage.load(request.capture_id)
        if (
            capture["evidence_sha256"] != request.snapshot_sha256
            or capture["target"] != self.native.target(request)
            or capture["device"] != request.device
        ):
            raise ValueError("Reopen the original native capture for this exact controller.")
        output, compilation = compile_io(files, capture["identity"], request.edit)
        return capture, files, output, compilation

    async def bank_guard(self, session, request, identity):
        """This field profile edits an already active, operational custom bank."""
        native = self.native
        if identity.get("firmware-revision") != "10.0.0.2125":
            raise ValueError("This live I/O profile requires separately qualified CV firmware.")
        root = str(await native.input_atomic(session, request.device, 32527, CharacterString))
        selector = "multi-state-value,1000"
        label = str(await native.path._read(session, selector, "object-name"))
        value = int(await native.path._read(session, selector, "present-value"))
        custom = str(await native.path._read(session, selector, "state-text", 1))
        if (
            label != root + "/Preloaded App Loader.App Selector"
            or value != 1
            or custom != "Custom Application"
        ):
            raise ValueError(
                "Select and independently qualify an active custom application first. "
                "This operation does not switch factory/custom banks."
            )
        if int(await native.path._read(session, request.device, "system-status")) != 0:
            raise ValueError("The current custom application is not operational.")
        return {"object": selector, "value": value, "custom_label": custom, "name": label}

    async def live_guard(self, session, request, compilation):
        native = self.native
        obj = compilation["object_id"]
        if request.edit.action == "allocate-binary":
            present, proof = await native.input_presence(session, obj)
            next_id = int(await native.input_atomic(session, request.device, 787, Unsigned))
            if present or request.edit.object_instance < next_id:
                raise ValueError(
                    "New input identifier is occupied or precedes the reported allocator."
                )
            return {"absence": proof, "next_available_instance": next_id}
        if await native.path._read(session, obj, "object-identifier") != ObjectIdentifier(obj):
            raise ValueError("The published output identity changed.")
        actual = int(await native.input_atomic(session, obj, 990, Unsigned))
        label = str(await native.input_atomic(session, obj, 31, CharacterString))
        change = compilation["changes"][0]
        if actual != request.edit.expected_slot or label != change["before_device_type"]:
            raise ValueError("The published output binding changed after capture.")
        return {"object": obj, "slot": actual, "device_type": label}

    async def preview(self, request):
        native = self.native
        async with native.operation(request.operation_id, "runtime-io-review"):
            native.available(request)
            capture, files, _, compilation = self.source(request)
            if compilation["factory_identity_materialized"]:
                raise ValueError("Factory-derived copies are offline only in this field profile.")
            if capture["connector_config"] != native.bacnet.config:
                raise ValueError("Open the capture's exact original interface before field review.")
            async with native.path._path(request) as session:
                PropertyEvidence.pin(session, request.router)
                actual, _ = await native.identity(session, request.device)
                if actual != capture["identity"]:
                    raise ValueError("Controller identity differs from the retained capture.")
                bank = await self.bank_guard(session, request, actual)
                guard = await self.live_guard(session, request, compilation)
            self.plans = {k: p for k, p in self.plans.items() if p["expires"] > time.monotonic()}
            if len(self.plans) >= 32:
                raise ValueError("I/O review capacity is full; finish or expire an earlier review.")
            body = {
                "profile": PROFILE,
                "request": request.model_dump(),
                "identity": actual,
                "compilation": compilation,
                "live_guard": guard,
                "application_bank": bank,
                "original_files": {str(k): sha(v) for k, v in files.items()},
                "connector_config": copy.deepcopy(native.bacnet.config),
                "credentials_sha256": seal(native.credentials.get()),
                "effects": "File 3 application transfer; control can restart. No firmware/boot transfer.",
            }
            digest, token = seal(body), secrets.token_hex(16)
            self.plans[token] = {
                "body": body,
                "digest": digest,
                "expires": time.monotonic() + 120,
                "app": native.bacnet.require(),
            }
            return {**body, "token": token, "review_sha256": digest, "expires_seconds": 120}

    async def verify(self, session, request, intent):
        native = self.native
        actual, _ = await native.identity(session, request.device)
        if actual != intent["identity"]:
            raise ValueError("The physical controller identity changed after transfer.")
        if int(await native.path._read(session, request.device, "system-status")) != 0:
            raise ValueError("The controller is not operational after transfer.")
        await self.bank_guard(session, request, actual)
        capture, after, _ = await native.capture_session(request, session, identity=actual)
        if sha(MoiIdentity(after[3]).data) != intent["native_payload_sha256"]:
            raise ValueError("Readback application differs from the exact reviewed native image.")
        post = ParameterApplication(after[3], after[11], after[12])
        current, counters, calculated = runtime_parameter_changes(MoiIdentity(after[3]), post)
        edit, obj = request.edit, intent["compilation"]["object_id"]
        expected = {
            75: (ObjectIdentifier, obj),
            77: (CharacterString, intent["compilation"]["object_name"]),
            31: (
                CharacterString,
                f"UI IN{edit.slot}" if edit.action == "allocate-binary" else f"BO OUT{edit.slot}",
            ),
            519 if edit.action == "allocate-binary" else 990: (Unsigned, edit.slot),
        }
        if edit.action == "allocate-binary":
            expected.update(
                {
                    4: (CharacterString, "On"),
                    46: (CharacterString, "Off"),
                    84: (Enumerated, 0),
                    931: (Enumerated, 83),
                }
            )
        published = {}
        for pid, (dtype, value) in expected.items():
            if value is None:
                continue
            observed = await native.input_atomic(session, obj, pid, dtype)
            text = str(observed) if dtype in (CharacterString, ObjectIdentifier) else int(observed)
            if text != value:
                raise ValueError(f"Independent published I/O property {pid} does not match.")
            published[str(pid)] = text
        return {
            "status": "verified",
            "operational": True,
            "identity": actual,
            "verification_capture_id": capture["id"],
            "published_io": published,
            "native_image_matches": True,
            "runtime_counter_changes": counters,
            "device_calculated_changes": calculated,
            "saved_parameters_verified": current["matched_parameters"],
            "may_have_applied": True,
        }

    async def apply(self, confirmation):
        if (
            not confirmation.local_io_testing_confirmed
            or not confirmation.application_transfer_confirmed
        ):
            raise ValueError("Confirm the local I/O test and application transfer before Apply.")
        plan = self.plans.pop(confirmation.token, None)
        if (
            plan is None
            or plan["digest"] != confirmation.review_sha256
            or plan["expires"] <= time.monotonic()
        ):
            raise ValueError("The I/O review is absent, expired, changed or already consumed.")
        native, body = self.native, plan["body"]
        if seal(body) != plan["digest"]:
            raise ValueError("I/O review contents changed.")
        request = IOReview.model_validate(body["request"])
        intent = None
        dispatched = False
        result = {"status": "not_sent", "may_have_applied": False, "errors": []}
        try:
            async with native.operation(request.operation_id, "runtime-io-apply"):
                native.available(request)
                if (
                    native.bacnet.require() is not plan["app"]
                    or native.bacnet.config != body["connector_config"]
                    or seal(native.credentials.get()) != body["credentials_sha256"]
                ):
                    raise ValueError("Interface or credentials changed after review.")
                async with native.path._path(request) as session:
                    PropertyEvidence.pin(session, request.router)
                    actual, _ = await native.identity(session, request.device)
                    if actual != body["identity"]:
                        raise ValueError("Controller identity changed after review.")
                    bank = await self.bank_guard(session, request, actual)
                    if bank != body["application_bank"]:
                        raise ValueError("The active application bank changed after review.")
                    await self.live_guard(session, request, body["compilation"])
                    backup, files, chunk = await native.capture_session(
                        request, session, identity=actual
                    )
                    if sha(files[3]) != body["original_files"]["3"]:
                        raise ValueError(
                            "Application or saved settings changed; capture and review again."
                        )
                    output, compilation = compile_io(files, actual, request.edit)
                    if (
                        compilation["configuration_guard"]
                        != body["compilation"]["configuration_guard"]
                        or compilation["changes"] != body["compilation"]["changes"]
                        or time.monotonic() >= plan["expires"]
                    ):
                        raise ValueError("The compiled I/O review changed or expired.")
                    capacity = int(await native.input_atomic(session, "file,3", 3380, Unsigned))
                    if not len(output) <= capacity <= 2 * 1024 * 1024:
                        raise ValueError("The reviewed image exceeds verified File 3 capacity.")
                    intent = native.storage.intent(
                        {
                            "id": secrets.token_hex(16),
                            "operation_id": request.operation_id,
                            "operation_profile": PROFILE,
                            "change_kind": "runtime-io",
                            "target": native.target(request),
                            "identity": actual,
                            "old_instance": ObjectIdentifier(request.device)[1],
                            "new_instance": ObjectIdentifier(request.device)[1],
                            "old_name": actual["object-name"],
                            "new_name": actual["object-name"],
                            "connector_config": body["connector_config"],
                            "backup_id": backup["id"],
                            "review_sha256": plan["digest"],
                            "request": request.model_dump(),
                            "compilation": compilation,
                            "payload_sha256": sha(output),
                            "native_payload_sha256": sha(MoiIdentity(output).data),
                        }
                    )

                    def before(stage, detail):
                        def dispatch(packet):
                            nonlocal dispatched
                            PropertyEvidence(native.path).guard(session)
                            native.storage.event(
                                intent["id"], stage, {**detail, "invoke_id": packet.apduInvokeID}
                            )
                            dispatched = True

                        return dispatch

                    await native.files.state(
                        session,
                        "start-restore",
                        password=native.credentials.get()["restore"],
                        before_send=before("dispatch-start-restore", {}),
                    )
                    await asyncio.sleep(RESTORE_PREPARATION_SECONDS)
                    await native.files.write(
                        session,
                        3,
                        output,
                        chunk=chunk,
                        before_send=lambda detail, packet: before("dispatch-block", detail)(packet),
                    )
                    await native.files.state(
                        session, "end-restore", before_send=before("dispatch-end-restore", {})
                    )
                    readiness = await native.wait_for_restore_readiness(session, intent)
                    if not readiness["ready"]:
                        raise ValueError(
                            "Controller did not become ready; read back the retained receipt."
                        )
                    result.update(await self.verify(session, request, intent))
        except (ValueError, OSError, TimeoutError, sqlite3.Error, asyncio.CancelledError) as exc:
            result["errors"].append((str(exc) or type(exc).__name__)[:512])
            result.update(
                status="unknown" if dispatched else "not_sent", may_have_applied=dispatched
            )
        if intent is None:
            return {"intent": None, "result": result}
        return native.storage.finish(
            intent["id"], {**result, "intent_sha256": intent["evidence_sha256"]}
        )

    async def readback(self, options):
        native = self.native
        receipt = native.storage.receipt(options.receipt_id)
        intent = receipt["intent"]
        if (
            intent.get("operation_profile") != PROFILE
            or intent["target"] != native.target(options)
            or intent["identity"]["device"] != options.device
        ):
            raise ValueError("This I/O receipt belongs to another profile or controller.")
        request = IOReview.model_validate(intent["request"])
        async with native.operation(options.operation_id, "runtime-io-readback"):
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                result = await self.verify(session, request, intent)
                native.storage.resolve(intent["id"], result)
        return native.storage.receipt(intent["id"])


def router(native):
    service = RuntimeIOOperations(native)
    routes = APIRouter(prefix="/api/bacnet/controller/native-application/runtime-io")

    @routes.post("/source")
    def source(body: IOReview):
        capture, _, _, compilation = service.source(body)
        return {
            "capture_id": capture["id"],
            "compilation": compilation,
            "controller_queries": False,
            "controller_writes": False,
        }

    @routes.post("/preview")
    async def preview(body: IOReview):
        return await service.preview(body)

    @routes.post("/apply")
    async def apply(body: IOApply):
        return await service.apply(body)

    @routes.post("/readback")
    async def readback(body: IOReadback):
        return await service.readback(body)

    return routes
