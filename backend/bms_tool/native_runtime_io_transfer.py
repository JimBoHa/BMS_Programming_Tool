"""Reviewed single-attempt I/O transfers with original backup and independent readback."""

import asyncio
import copy
import secrets
import sqlite3
import time

from bacpypes3.basetypes import StatusFlags
from bacpypes3.errors import InvalidTag
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from fastapi import APIRouter
from pydantic import Field, StrictBool

from .application_preservation import runtime_parameter_changes
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_applications import RESTORE_PREPARATION_SECONDS, NativeCapture
from .native_contact_points import CONTACT_ACTIONS, POLARITIES, contact_options
from .native_output_points import (
    ALLOCATION_ACTIONS,
    OUTPUT_ACTIONS,
    discrete_terminals,
    output_options,
    signal,
)
from .native_runtime_io import (
    PROFILE,
    RuntimeIOEdit,
    compile_io,
    factory_io_candidate,
    qualified_io_source,
)
from .property_evidence import PropertyEvidence


class IOSource(NativeCapture):
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class IOReview(IOSource):
    edit: RuntimeIOEdit


class IOApply(StrictModel):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    review_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    local_io_testing_confirmed: StrictBool
    application_transfer_confirmed: StrictBool
    output_wiring_confirmed: StrictBool = False
    input_wiring_confirmed: StrictBool = False


class IOReadback(NativeCapture):
    receipt_id: str = Field(pattern=r"^[a-f0-9]{32}$")


async def published_fields(native, session, obj, expected):
    observed = {}
    for pid, (dtype, wanted) in expected.items():
        if wanted is None:
            continue
        raw = await native.input_atomic(session, obj, pid, dtype)
        value = str(raw) if dtype in (CharacterString, ObjectIdentifier) else int(raw)
        if value != wanted:
            raise ValueError(f"Independent published I/O property {pid} does not match.")
        observed[str(pid)] = value
    return observed


async def contact_value(native, session, obj):
    value = int(await native.input_atomic(session, obj, 85, Enumerated))
    flags = list(await native.input_atomic(session, obj, 111, StatusFlags))
    reliability = int(await native.input_atomic(session, obj, 103, Enumerated))
    oos = bool(await native.input_atomic(session, obj, 81, Boolean))
    if value not in (0, 1) or len(flags) != 4 or any(flags[1:]) or reliability or oos:
        raise ValueError("The published dry contact has no healthy, in-service binary readback.")
    return {
        "present_value": value,
        "status_flags": flags,
        "out_of_service": oos,
        "reliability": reliability,
    }


class RuntimeIOOperations:
    def __init__(self, native):
        self.native = native
        self.plans = {}

    def capture_source(self, request):
        capture, files = self.native.storage.load(request.capture_id)
        if (
            capture["evidence_sha256"] != request.snapshot_sha256
            or capture["target"] != self.native.target(request)
            or capture["device"] != request.device
        ):
            raise ValueError("Reopen the original native capture for this exact controller.")
        return capture, files

    def source(self, request):
        capture, files = self.capture_source(request)
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
        guard = {}
        if request.edit.action == "allocate-binary" or request.edit.action in ALLOCATION_ACTIONS:
            present, proof = await native.input_presence(session, obj)
            next_id = int(await native.input_atomic(session, request.device, 787, Unsigned))
            if present or request.edit.object_instance < next_id:
                raise ValueError(
                    f"New point identifier is occupied or precedes the reported allocator. Choose an unused instance at or above {next_id}."
                )
            guard = {"absence": proof, "next_available_instance": next_id}
            if request.edit.action in {"allocate-binary", "allocate-discrete-output"}:
                return guard
            obj = compilation["changes"][0]["source_object"]
        if request.edit.action in CONTACT_ACTIONS:
            change = compilation["changes"][0]
            expected = {
                75: (ObjectIdentifier, obj),
                77: (CharacterString, change["source_name"]),
                31: (CharacterString, f"UI IN{request.edit.expected_slot}"),
                519: (Unsigned, request.edit.expected_slot),
                4: (CharacterString, change["states"][1]),
                46: (CharacterString, change["states"][0]),
                931: (Enumerated, change["states_text_index"]),
            }
            await published_fields(native, session, obj, expected)
            current = int(await native.input_atomic(session, obj, 84, Enumerated))
            if current not in (0, 1) or change["before_polarity"] not in (
                None,
                POLARITIES[current],
            ):
                raise ValueError("The published contact polarity differs from the captured input.")
            if (
                request.edit.action == "binary-input-polarity"
                and POLARITIES[current] == request.edit.polarity
            ):
                raise ValueError("The published input already has the selected polarity.")
            await contact_value(native, session, obj)
            return {"object": obj, "slot": request.edit.expected_slot, "polarity": current}
        if await native.path._read(session, obj, "object-identifier") != ObjectIdentifier(obj):
            raise ValueError("The published output identity changed.")
        actual = int(await native.input_atomic(session, obj, 990, Unsigned))
        label = str(await native.input_atomic(session, obj, 31, CharacterString))
        change = compilation["changes"][0]
        if actual != request.edit.expected_slot or label != change["before_device_type"]:
            raise ValueError("The published output binding changed after capture.")
        if request.edit.action in OUTPUT_ACTIONS:
            name = str(await native.input_atomic(session, obj, 77, CharacterString))
            if name != change["source_name"]:
                raise ValueError("The published source output name changed after capture.")
            pid, expected = (518, 0) if change["mode"] == "binary" else (117, 98)
            if int(await native.input_atomic(session, obj, pid, Enumerated)) != expected:
                raise ValueError("The source electrical profile differs from the captured output.")
            if (change["mode"] == "proportional" or change.get("has_slot_alias")) and int(
                await native.input_atomic(session, obj, 519, Unsigned)
            ) != actual:
                raise ValueError("Published output slot and slot A disagree.")
            if request.edit.action not in ALLOCATION_ACTIONS:
                slots = await native.path._read(session, obj, "priority-array")
                choices = [getattr(slot, "_choice", None) for slot in slots]
                if len(choices) != 16 or any(c != "null" for c in choices[:15]):
                    raise ValueError(
                        "Release or resolve the existing output command before moving the point."
                    )
        return {**guard, "object": obj, "slot": actual, "device_type": label}

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
        is_input = edit.action in CONTACT_ACTIONS
        change = intent["compilation"]["changes"][0]
        expected = {
            75: (ObjectIdentifier, obj),
            77: (CharacterString, intent["compilation"]["object_name"]),
            31: (
                CharacterString,
                f"UI IN{edit.slot}" if is_input else change["after_device_type"],
            ),
            519 if is_input else 990: (Unsigned, edit.slot),
        }
        if is_input:
            expected.update(
                {
                    4: (CharacterString, change["states"][1]),
                    46: (CharacterString, change["states"][0]),
                    84: (
                        Enumerated,
                        POLARITIES.index(change["polarity"])
                        if change.get("polarity") is not None
                        else intent["contact_source_polarity"],
                    ),
                    931: (Enumerated, change.get("states_text_index", 83)),
                }
            )
        if edit.action in OUTPUT_ACTIONS:
            if change.get("mode", "binary") == "binary":
                expected[518] = (Enumerated, 0)
                if change.get("has_slot_alias"):
                    expected[519] = (Unsigned, edit.slot)
            else:
                expected[117] = (Enumerated, 98)
                expected[519] = (Unsigned, edit.slot)
        published = await published_fields(native, session, obj, expected)
        if is_input:
            published.update(await contact_value(native, session, obj))
        if edit.action in ALLOCATION_ACTIONS:
            dtype = Enumerated if change["mode"] == "binary" else Real
            pv = float(await native.input_atomic(session, obj, 85, dtype))
            default = float(await native.input_atomic(session, obj, 104, dtype))
            flags = list(await native.input_atomic(session, obj, 111, StatusFlags))
            reliability = int(await native.input_atomic(session, obj, 103, Enumerated))
            offline = bool(await native.input_atomic(session, obj, 81, Boolean))
            slots = await native.path._read(session, obj, "priority-array")
            choices = [getattr(slot, "_choice", None) for slot in slots]
            if (
                pv != 0
                or default != 0
                or offline
                or reliability
                or any(flags)
                or len(choices) != 16
                or any(c != "null" for c in choices[:15])
                or (
                    choices[15] != "null"
                    and (
                        choices[15] not in ("enumerated", "real")
                        or float(getattr(slots[15], choices[15])) != 0
                    )
                )
            ):
                raise ValueError(
                    "The new output did not publish a healthy, uncommanded neutral state."
                )
            published.update(
                neutral_present_value=pv, relinquish_default=default, priority_1_to_15_clear=True
            )
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
        plan = self.plans.get(confirmation.token)
        if (
            plan is None
            or plan["digest"] != confirmation.review_sha256
            or plan["expires"] <= time.monotonic()
        ):
            raise ValueError("The I/O review is absent, expired, changed or already consumed.")
        edit = plan["body"]["request"]["edit"]
        # Dedicated-terminal moves keep their established two-confirmation API.
        if (
            edit["action"] in OUTPUT_ACTIONS
            and not confirmation.output_wiring_confirmed
            and (edit["action"] != "binary-output-terminal" or edit["slot"] > 3)
        ):
            raise ValueError(
                "Confirm the connected load and electrical mode before an output transfer."
            )
        if (
            edit["action"] in CONTACT_ACTIONS
            and (edit["action"] != "allocate-binary" or edit.get("polarity") is not None)
            and not confirmation.input_wiring_confirmed
        ):
            raise ValueError("Confirm the input terminal and contact polarity before transfer.")
        self.plans.pop(confirmation.token)
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
                    guard = await self.live_guard(session, request, body["compilation"])
                    if (
                        edit["action"] in CONTACT_ACTIONS
                        and edit["action"] != "allocate-binary"
                        and guard != body["live_guard"]
                    ):
                        raise ValueError("The live contact changed after review.")
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
                    # A new object, device allocator, override or contact polarity can
                    # change while the backup runs. Check the field evidence once more.
                    current = await self.live_guard(session, request, compilation)
                    if (
                        edit["action"] in {"binary-input-terminal", "binary-input-polarity"}
                        and current != guard
                    ):
                        raise ValueError("The live contact changed during backup.")
                    if time.monotonic() >= plan["expires"]:
                        raise ValueError("The I/O review expired during final readback.")
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
                            **(
                                {"contact_source_polarity": guard["polarity"]}
                                if "polarity" in guard
                                else {}
                            ),
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
        except (
            ValueError,
            InvalidTag,
            OSError,
            TimeoutError,
            sqlite3.Error,
            asyncio.CancelledError,
        ) as exc:
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
        if intent["connector_config"] != native.bacnet.config:
            raise ValueError(
                "Reopen the I/O receipt's original controller interface before readback."
            )
        async with native.operation(options.operation_id, "runtime-io-readback"):
            async with native.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                result = await self.verify(session, request, intent)
                native.storage.resolve(intent["id"], result)
        return native.storage.receipt(intent["id"])


def router(native):
    service = RuntimeIOOperations(native)
    routes = APIRouter(prefix="/api/bacnet/controller/native-application/runtime-io")

    def sources(body, actions):
        target = native.target(body)
        return {
            "sources": [
                {
                    "capture_id": c["id"],
                    "snapshot_sha256": c["evidence_sha256"],
                    "identity": c["identity"],
                    "target": c["target"],
                    "captured_at": c["captured_at"],
                }
                for c in native.storage.captures()
                if c["target"] == target
                and c["identity"]["device"] == body.device
                and (
                    c.get("source_identity_matches")
                    or factory_io_candidate(c.get("application") or {}, c["identity"])
                )
            ],
            "receipts": [
                {
                    "id": r["intent"]["id"],
                    "pending": r["pending"],
                    "status": (r.get("latest_readback") or r.get("result") or {}).get(
                        "status", "unknown"
                    ),
                }
                for r in native.storage.receipts(include_events=False)
                if r["intent"].get("operation_profile") == PROFILE
                and r["intent"]["target"] == target
                and r["intent"]["identity"]["device"] == body.device
                and r["intent"]["request"]["edit"]["action"] in actions
            ],
        }

    @routes.post("/output-sources")
    def output_sources(body: DeviceDetailsRequest):
        return sources(body, OUTPUT_ACTIONS)

    @routes.post("/contact-sources")
    def contact_sources(body: DeviceDetailsRequest):
        return sources(body, CONTACT_ACTIONS)

    def catalog(body, contacts):
        capture, files = service.capture_source(body)
        app, proof, capacity, _ = qualified_io_source(files, capture["identity"])
        instances = [
            ObjectIdentifier(obj)[1]
            for r in app.records
            if r["class_id"] in (239, 240, 241, 242, 251)
            and (obj := app.reader.scalar(r, 75)) is not None
        ]
        candidate = max(max(instances, default=0) + 1, app.reader.scalar(app.root, 787) or 1)
        free_discrete = [] if contacts else discrete_terminals(app)
        return {
            "capture_id": capture["id"],
            "identity": capture["identity"],
            "target": capture["target"],
            "suggested_instance": candidate if candidate <= 4194302 else None,
            "local_review_only": (
                proof["factory_identity_materialized"]
                or capture["identity"].get("firmware-revision") != "10.0.0.2125"
            ),
            **(
                contact_options(app, capacity)
                if contacts
                else {
                    "outputs": output_options(app),
                    "discrete_terminals": free_discrete,
                    "discrete_terminal_signals": {
                        slot: signal(slot, "binary") for slot in free_discrete
                    },
                }
            ),
            "controller_queries": False,
            "controller_writes": False,
        }

    @routes.post("/outputs")
    def outputs(body: IOSource):
        return catalog(body, False)

    @routes.post("/contacts")
    def contacts(body: IOSource):
        return catalog(body, True)

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
