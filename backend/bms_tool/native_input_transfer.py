"""Input-specific authority and published readback, sharing the native transfer journal."""

import copy
import struct
from datetime import UTC, datetime, timedelta

from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.object import AnalogInputObject, BinaryInputObject
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Boolean, Enumerated, ObjectIdentifier, Real, TagList, Unsigned

from .application_store import PROFILE as TRANSFER_PROFILE
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_encoded_analog_recovery_transfer import EncodedAnalogRecoveryPreview
from .native_encoded_analog_recovery_transfer import (
    recovery_origin as encoded_analog_recovery_origin,
)
from .native_inputs import (
    CONFIG,
    ENUM_FIELDS,
    PROFILE,
    SCOPE,
    TERMINAL_SCOPE,
    InputCopy,
    InputEdit,
    InputLocalSource,
    InputPreview,
    InputSupport,
    NativeInputCompiler,
    compile_input,
    input_operation_profile,
)
from .native_terminal_recovery_transfer import TerminalRecoveryPreview, recovery_origin
from .property_evidence import PropertyEvidence, ReadBudget


class NativeInputOperations:
    def input_sources(self):
        return {
            "profile": PROFILE,
            "controller_queries": False,
            "controller_writes": False,
            "sources": [
                {
                    "capture_id": c["id"],
                    "snapshot_sha256": c["evidence_sha256"],
                    "identity": c["identity"],
                    "target": c["target"],
                    "captured_at": c["captured_at"],
                }
                for c in self.storage.captures()
                if c.get("source_identity_matches")
            ],
        }

    def input_local_capture(self, source):
        source = InputLocalSource.model_validate(source)
        capture, files = self.storage.load(source.capture_id)
        if capture["evidence_sha256"] != source.snapshot_sha256 or not capture.get(
            "source_identity_matches"
        ):
            raise ValueError("Reopen a complete identity-matched native input source.")
        return capture, files

    def input_source(self, **arguments):
        source = InputLocalSource(**arguments)
        capture, files = self.input_local_capture(source.model_dump())
        return {
            **NativeInputCompiler(files).source(),
            "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "target": capture["target"],
            "identity": capture["identity"],
            "controller_queries": False,
        }

    def binary_input_source(self, **arguments):
        from .native_binary_terminal import BinaryTerminalCompiler

        source = InputLocalSource(**arguments)
        capture, files = self.input_local_capture(source.model_dump())
        compiler = BinaryTerminalCompiler(NativeInputCompiler(files))
        identity = compiler.app.summary()
        if (
            capture["identity"].get("vendor-identifier") != 5
            or capture["device"] != f"device,{identity['instance']}"
            or capture["identity"].get("object-name") != identity["name"]
            or capture["identity"].get("model-name") != identity["model"]
        ):
            raise ValueError("Binary native archive and captured controller identity disagree.")
        return {
            **compiler.source(),
            "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "target": capture["target"],
            "identity": capture["identity"],
        }

    def encoded_analog_input_source(self, **arguments):
        from .native_encoded_terminal_input import EncodedAnalogTerminalCompiler

        source = InputLocalSource(**arguments)
        capture, files = self.input_local_capture(source.model_dump())
        compiler = EncodedAnalogTerminalCompiler(NativeInputCompiler(files))
        identity = compiler.app.summary()
        if (
            capture["identity"].get("vendor-identifier") != 5
            or capture["device"] != f"device,{identity['instance']}"
            or capture["identity"].get("object-name") != identity["name"]
            or capture["identity"].get("model-name") != identity["model"]
        ):
            raise ValueError("Encoded analog archive and captured controller identity disagree.")
        return {
            **compiler.source(), "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "target": capture["target"], "identity": capture["identity"],
        }

    def input_allocation_origin(self, edit, capture):
        edit = InputEdit.model_validate(edit)
        if edit.action != "remove-allocated":
            return None
        receipt = self.storage.receipt(edit.allocation_receipt)
        intent = receipt["intent"]
        result = receipt.get("result") or {}
        readbacks = [e["detail"] for e in receipt.get("events", []) if e["stage"] == "readback"]
        observed = readbacks[-1] if readbacks else result
        origin = intent.get("input_edit", {})
        if (
            receipt["pending"]
            or observed.get("status") != "verified"
            or intent.get("operation_profile") != PROFILE
            or origin.get("action") != "allocate"
            or intent["target"] != capture["target"]
            or intent["identity"] != capture["identity"]
            or origin.get("object_instance") != edit.object_instance
            or origin.get("slot") != edit.slot
        ):
            raise ValueError(
                "This is not the verified allocation of this input on this exact controller."
            )
        return {
            **copy.deepcopy(intent["compilation"]),
            "initialized_input_parameters": copy.deepcopy(
                observed.get("preservation", {}).get("initialized_input_parameters", [])
            ),
        }

    def input_copy(self, **arguments):
        request = InputCopy(**arguments)
        capture, files = self.input_local_capture(
            request.model_dump(include={"capture_id", "snapshot_sha256"})
        )
        origin = self.input_allocation_origin(request.edit, capture)
        output, compilation = compile_input(files, request.edit, allocation_origin=origin)
        body = {
            "profile": input_operation_profile(request.edit),
            "scope": "Local native input copy; no controller query, plan or transfer authority.",
            "capture_id": capture["id"],
            "snapshot_sha256": capture["evidence_sha256"],
            "target": capture["target"],
            "identity": capture["identity"],
            "edit": request.edit.model_dump(),
            "compilation": compilation,
            "controller_queries": False,
            "controller_writes": False,
            "output_sha256": sha(output),
        }
        body["review_sha256"] = seal(body)
        if (
            request.expected_review_sha256 is not None
            and request.expected_review_sha256 != body["review_sha256"]
        ):
            raise ValueError("The local input copy changed; review it again.")
        return output, body

    async def input_atomic(self, session, obj, pid, datatype):
        request = ReadPropertyRequest(objectIdentifier=obj, propertyIdentifier=pid)
        reply = await self.files.exchange(session, request, ReadPropertyACK)
        if (
            reply.objectIdentifier != request.objectIdentifier
            or reply.propertyIdentifier != request.propertyIdentifier
            or reply.propertyArrayIndex is not None
        ):
            raise ValueError("Input property reply differs from its requested object/property.")
        raw = bytes(reply.propertyValue.tagList.encode().pduData)
        if raw[:1] == b"\x3e" and raw[-1:] == b"\x3f":
            raw = raw[1:-1]
        tags = TagList.decode(PDUData(raw))
        value = datatype.decode(tags)
        if tags:
            raise ValueError("Input property reply contains trailing values.")
        return value

    async def input_presence(self, session, obj):
        value, row = await PropertyEvidence(self.path).read(
            session,
            ReadBudget(max_requests=1, max_bytes=128 * 1024),
            obj,
            75,
            BinaryInputObject if ObjectIdentifier(obj)[0] == 3 else AnalogInputObject,
            timeout=self.files.timeout,
        )
        if row["status"] == "ok" and value == ObjectIdentifier(obj):
            return True, row
        error = row.get("native_error", {})
        if (
            row["status"] == "native_error"
            and error.get("errorClass", {}).get("value") == 1
            and error.get("errorCode", {}).get("value") == 31
            and row.get("transport_evidence")
        ):
            return False, row
        raise ValueError(
            "The input presence/absence was not established by an attributable object identity response."
        )

    async def input_live_guard(self, session, options, compilation, files):
        edit = options.edit
        obj = compilation["object_id"]
        present, presence = await self.input_presence(session, obj)
        if edit.action == "allocate":
            next_id = int(await self.input_atomic(session, options.device, 787, Unsigned))
            if not 0 <= next_id <= 4194302 or edit.object_instance < next_id or present:
                raise ValueError(
                    "The proposed input identifier is occupied or precedes the controller-reported next available identifier."
                )
            return {"next_available_instance": next_id, "presence": presence}
        if not present:
            raise ValueError("The selected native input no longer responds.")
        observation = await self.verify_published_input(session, files, edit)
        return {"presence": presence, "configuration": observation}

    async def input_support(self, **arguments):
        options = InputSupport(**arguments)
        async with self.operation(options.operation_id, "input-capabilities"):
            self.available(options)
            captured, files = self.check_capture(options)
            source = self.input_source(
                **options.model_dump(include={"capture_id", "snapshot_sha256"})
            )
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
                if actual != captured["identity"]:
                    raise ValueError("The controller identity changed after this input capture.")
                next_id = int(await self.input_atomic(session, options.device, 787, Unsigned))
            return {
                **source,
                "operation_id": options.operation_id,
                "next_available_instance": next_id,
                "controller_queries": True,
            }

    async def preview_input(self, **arguments):
        return await self.review_input(InputPreview(**arguments))

    async def preview_terminal_recovery(self, **arguments):
        return await self.review_input(TerminalRecoveryPreview(**arguments))

    async def preview_encoded_analog_recovery(self, **arguments):
        return await self.review_input(EncodedAnalogRecoveryPreview(**arguments))

    async def review_input(self, options):
        async with self.operation(options.operation_id, "review-input"):
            self.available(options)
            captured, files = self.check_capture(options)
            (
                self.encoded_analog_input_source
                if options.edit.action == "encoded-terminal"
                else self.binary_input_source
                if options.edit.action == "binary-terminal"
                else self.input_source
            )(**options.model_dump(include={"capture_id", "snapshot_sha256"}))
            origin = self.input_allocation_origin(options.edit, captured)
            output, compilation = compile_input(files, options.edit, allocation_origin=origin)
            recovery = {
                **recovery_origin(self, options, compilation),
                **encoded_analog_recovery_origin(self, options, compilation),
            }
            config, app = copy.deepcopy(self.bacnet.config), self.bacnet.require()
            async with self.path._path(options) as session:
                PropertyEvidence.pin(session, options.router)
                actual, _ = await self.identity(session, options.device)
                if actual != captured["identity"]:
                    raise ValueError("The controller identity changed after the input capture.")
                live = await self.input_live_guard(session, options, compilation, files)
            now = datetime.now(UTC)
            body = {
                "profile": TRANSFER_PROFILE,
                "operation_profile": input_operation_profile(options.edit),
                "operation_id": options.operation_id,
                "target": self.target(options),
                "identity": actual,
                "old_instance": ObjectIdentifier(options.device)[1],
                "new_instance": ObjectIdentifier(options.device)[1],
                "change_kind": "input",
                "old_name": actual["object-name"],
                "new_name": actual["object-name"],
                "capture_id": options.capture_id,
                "snapshot_sha256": captured["evidence_sha256"],
                "application_sha256": sha(files[3]),
                "static_parameters_sha256": sha(files[11]),
                "input_edit": options.edit.model_dump(),
                "compilation": compilation,
                "allocation_origin": origin,
                "input_live_preflight": live,
                "payload_sha256": sha(output),
                "collision_check": self.name_scope(),
                "parameter_policy": "Merge fresh saved settings. Retain every non-selected record and wire; verify complete application and published input configuration.",
                "scope": self.input_scope(options.edit),
                "vendor_runtime_required": False,
                "can_apply": True,
                "connector_config": config,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=900)).isoformat(),
                **recovery,
            }
            from .native_applications import backup_effects

            body["backup_effects"] = backup_effects()
            return self.retain_plan(body, options, app, config)

    async def verify_published_input(self, session, files, edit):
        edit = InputEdit.model_validate(edit)
        if edit.action == "binary-terminal":
            from .native_binary_terminal import verify_published

            return await verify_published(self, session, files, edit)
        obj = f"analog-input,{edit.object_instance}"
        merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
        app = MoiIdentity(merged)
        records = [r for r in app.records if app.reader.scalar(r, 75) == obj]
        if len(records) > 1:
            raise ValueError("Multiple native records declare the input identity.")
        present, evidence = await self.input_presence(session, obj)
        if not records:
            if present:
                raise ValueError("The removed input remains published by the controller.")
            return {"object_id": obj, "present": False, "absence_evidence": evidence}
        if not present:
            raise ValueError("The configured input is absent from the controller.")
        record = records[0]
        rows = []
        for pid in [77, 31, 519, *CONFIG, 22, 118, 3407, 3422, 813, 3164, 1302]:
            expected = app.reader.scalar(record, 2390 if pid == 77 else pid)
            if expected is None:
                continue  # An original nonlinear source can omit linear defaults.
            from bacpypes3.primitivedata import CharacterString

            dtype = (
                CharacterString
                if pid in (31, 77)
                else Boolean
                if pid == 1302
                else Unsigned
                if pid in (519, 118, 813)
                else Enumerated
                if pid in ENUM_FIELDS | {3407, 3422}
                else Real
            )
            value = await self.input_atomic(session, obj, pid, dtype)
            native_default, comparison = expected, "stored configuration"
            if pid == 118 and value != expected and app.reader.scalar(record, 3407) == 2:
                # Monitor Only derives Update Interval from Time Constant / 30
                # seconds, regardless of the stored interval. CCT help's AI
                # Filter Setup table documents this controller-calculated input.
                constant = await self.input_atomic(session, obj, 3164, Real)
                configured = app.reader.scalar(record, 3164)
                interval = float(constant) * 100 / 30
                if (
                    configured is None
                    or struct.pack(">f", float(constant)) != struct.pack(">f", configured)
                    or not 0 <= interval <= 4294967295
                    or not interval.is_integer()
                ):
                    raise ValueError(
                        "Monitor Only interval has no qualified Time Constant evidence."
                    )
                expected, comparison = (
                    int(interval),
                    "Monitor Only Time Constant / 30 in hundredths of seconds",
                )
            matches = (
                struct.pack(">f", float(value)) == struct.pack(">f", expected)
                if dtype is Real
                else value == expected
            )
            if not matches:
                raise ValueError(
                    f"Published input property {pid} differs from the reviewed application."
                )
            rows.append(
                {
                    "property": pid,
                    "expected": expected,
                    "native_application_value": native_default,
                    "comparison": comparison,
                    "actual": str(value)
                    if dtype is CharacterString
                    else bool(value)
                    if dtype is Boolean
                    else float(value)
                    if dtype is Real
                    else int(value),
                    "matches": True,
                }
            )
        return {
            "object_id": obj,
            "present": True,
            "properties": rows,
            "identity_evidence": evidence,
        }

    @staticmethod
    def input_scope(edit):
        if edit.action == "encoded-terminal":
            from .native_encoded_terminal_input import SCOPE as ENCODED_SCOPE

            return ENCODED_SCOPE
        if edit.action == "binary-terminal":
            from .native_binary_terminal import SCOPE as BINARY_SCOPE

            return BINARY_SCOPE
        return TERMINAL_SCOPE if edit.action == "terminal" else SCOPE
