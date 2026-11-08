"""Single-attempt source-property experiment on tool-created isolated AIs only.

This is not an existing-point editor or a production write capability. A readable
configuration property, schema, or successful creation never qualifies a write.
The retained creation intent is mandatory and cannot be supplied by an API caller.
"""

from __future__ import annotations

import copy
import secrets
import time

import httpx
from bacpypes3.apdu import ErrorPDU, ErrorRejectAbortNack, SimpleAckPDU, WritePropertyRequest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned

from .bacnet_exchange import confirmed_exchange
from .device_details import DeviceDetailsRequest
from .metasys_configuration_api import PREFIX, MetasysApiError
from .metasys_temporary_mapping import PLAN_SECONDS, nodes, sha
from .property_evidence import ReadBudget


class MetasysTemporarySourceProbe:
    def __init__(self, mappings):
        self.mappings = mappings
        self.workspace = mappings.workspace
        self.api = mappings.api
        self._plans = {}

    def discard_reviews(self):
        self._plans.clear()

    def _owned(self, operation_id):
        records = self.mappings.records(operation_id)
        if "intent" not in records or "result" not in records:
            raise ValueError("A verified tool-created temporary monitoring point is required.")
        review = records["intent"]["review"]
        result = records["result"]
        if (
            review["payload"]["objectType"] != "objectTypeEnumSet.bacnetAiClass"
            or result["status"] != "created_configuration_verified"
            or result.get("source_edit_qualified") is not False
        ):
            raise ValueError("This experiment admits only an owned temporary AI mapping.")
        return records, review, result["created_id"]

    async def _snapshot(self, session, review, created_id, expected_source):
        # API verification uses the original GUID, reference, local OID and nonce.
        expected = copy.deepcopy(review)
        expected["payload"]["item"]["instanceNumber"] = expected_source
        configuration = await self.mappings._verify_created(expected, created_id)
        for key in ("intrinsicAlarmingDefined", "useRemoteAlarming"):
            attribute = await self.api.attribute(created_id, key)
            if attribute.get("item", {}).get(key) is not False:
                raise ValueError("The temporary point no longer has isolated monitoring alarming.")
        children = nodes(await self.api.children(created_id))
        if set(children) - {created_id}:
            raise ValueError("The temporary point acquired children or extensions.")
        oid = ObjectIdentifier((0, review["payload"]["item"]["objectIdentifier"]["instance"]))
        fields, evidence = {}, {}
        budget = ReadBudget(max_requests=12, max_bytes=256 * 1024)
        for prop in ("object-identifier", "32527", "description", "object-name", "32589", "units"):
            value, row = await self.workspace._read(session, budget, str(oid), prop)
            if row.get("status") != "ok":
                raise ValueError("A required native temporary-point property was not read.")
            evidence[prop] = row
            if prop == "object-identifier":
                if not isinstance(value, ObjectIdentifier) or value != oid:
                    raise ValueError("Native temporary-point identifier changed.")
                fields[prop] = str(value)
            elif prop == "32589":
                if not isinstance(value, Unsigned) or int(value) != expected_source:
                    raise ValueError(
                        "Native temporary-point source differs from the expected source."
                    )
                fields[prop] = int(value)
            elif prop in ("description", "32527", "object-name"):
                if not isinstance(value, CharacterString):
                    raise ValueError("Native temporary-point text has an unexpected type.")
                fields[prop] = str(value)
            else:
                fields[prop] = int(value)
        if (
            fields["32527"] != review["expected_reference"]
            or fields["description"] != review["payload"]["item"]["description"]
        ):
            raise ValueError("Native temporary-point ownership differs from its creation intent.")
        return {"fields": fields, "property_evidence": evidence, "configuration": configuration}

    @staticmethod
    def _phase(method, restore):
        if method not in ("bacnet", "configuration-api"):
            raise ValueError("Unqualified temporary source experiment method.")
        return ("api-" if method == "configuration-api" else "") + (
            "restore" if restore else "probe"
        )

    async def prepare(
        self, *, operation_id, replacement_source=None, restore=False, method="bacnet"
    ):
        if len(self._plans) >= 8:
            raise ValueError("Discard existing local source-probe reviews first.")
        records, owner, created_id = self._owned(operation_id)
        original = owner["payload"]["item"]["instanceNumber"]
        phase = self._phase(method, restore)
        if phase + "-intent" in records:
            raise ValueError("This experiment was already dispatched; reconcile without retrying.")
        if restore:
            probe = records.get(self._phase(method, False) + "-intent")
            if probe is None:
                raise ValueError("No retained source experiment exists to restore.")
            old, new = probe["review"]["replacement_source"], original
        else:
            old, new = original, replacement_source
        if type(new) is not int or not 0 <= new <= 4194302 or new == old:
            raise ValueError("An explicit different real source instance is required.")
        options = DeviceDetailsRequest(**owner["native"]["target"])
        async with self.mappings._lease(options) as session:
            account = self.api.session_key
            native = await self.mappings._engine(session, options)
            if native["binding_sha256"] != owner["native"]["binding_sha256"]:
                raise ValueError("Native engine/interface differs from the retained creation.")
            await self.mappings._context(owner["engine_id"], owner["parent_id"], native)
            point = await self._snapshot(session, owner, created_id, old)
            self.workspace.reader.guard(session)
            if self.api.session_key != account:
                raise ValueError("Configuration account changed during the source-probe review.")
            review = {
                "profile": "metasys-temporary-source-probe/1",
                "operation_id": operation_id,
                "phase": phase,
                "method": method,
                "created_id": created_id,
                "expected_source": old,
                "replacement_source": new,
                "original_source": original,
                "native": native,
                "point": point,
                "configuration_session": account,
                "scope": "One experimental source update on an owned isolated AI only; no retries, commands or production capability.",
                "production_source_edit_qualified": False,
            }
            review["review_sha256"] = sha(review)
            token = secrets.token_urlsafe(24)
            self._plans[(operation_id, phase)] = (
                copy.deepcopy(review),
                token,
                time.monotonic(),
                (session["app"], session["evidence_socket"]),
            )
            return {**review, "token": token}

    async def apply(self, *, operation_id, phase, token, review_sha256):
        plan = self._plans.pop((operation_id, phase), None)
        if plan is None:
            raise ValueError("The source-probe review was consumed or does not exist.")
        review, expected_token, made, connector = plan
        if (
            type(token) is not str
            or not secrets.compare_digest(token, expected_token)
            or review_sha256 != review["review_sha256"]
            or time.monotonic() - made > PLAN_SECONDS
            or self.api.session_key != review["configuration_session"]
        ):
            raise ValueError("The source-probe review is stale or does not match.")
        _, owner, created_id = self._owned(operation_id)
        options = DeviceDetailsRequest(**owner["native"]["target"])
        async with self.mappings._lease(options) as session:
            native = await self.mappings._engine(session, options)
            if (
                session["app"] is not connector[0]
                or session["evidence_socket"] is not connector[1]
                or native["binding_sha256"] != review["native"]["binding_sha256"]
            ):
                raise ValueError("The native engine/interface changed; review again.")
            await self.mappings._context(owner["engine_id"], owner["parent_id"], native)
            point = await self._snapshot(session, owner, created_id, review["expected_source"])
            if point["fields"] != review["point"]["fields"]:
                raise ValueError("Temporary point identity/configuration changed; review again.")
            if self.api.session_key != review["configuration_session"]:
                raise ValueError("Configuration account changed; review again.")
            if review["method"] == "configuration-api":
                self.workspace.reader.guard(session)
                self.mappings._record(
                    operation_id,
                    phase + "-intent",
                    {"status": "outcome_uncertain", "review": review},
                )
                result = {"status": "outcome_uncertain", "production_source_edit_qualified": False}
                try:
                    reply = await self.api._request(
                        "PATCH",
                        PREFIX + "/v6/objects/" + created_id,
                        body={"item": {"instanceNumber": review["replacement_source"]}},
                    )
                    result.update(
                        status="acknowledged_unverified",
                        http_status=reply.http_status,
                        response=reply.data,
                    )
                except MetasysApiError as exc:
                    result.update(
                        http_status=exc.http_status, response_problem=exc.response_problem
                    )
                    if exc.http_status is not None and 400 <= exc.http_status < 500:
                        result["status"] = "configuration_rejection"
                except (httpx.HTTPError, TimeoutError) as exc:
                    result["error"] = type(exc).__name__
                self.mappings._record(operation_id, phase + "-response", result)
                return result
            identifier = ObjectIdentifier(review["point"]["fields"]["object-identifier"])
            request = WritePropertyRequest(
                objectIdentifier=identifier,
                propertyIdentifier=32589,
                propertyValue=Unsigned(review["replacement_source"]),
                destination=session["target"],
            )

            def before_send(_packet):
                self.workspace.reader.guard(session)
                if (
                    self.api.session_key != review["configuration_session"]
                    or time.monotonic() - made > PLAN_SECONDS
                ):
                    raise ValueError("Configuration account changed before dispatch.")
                self.mappings._record(
                    operation_id,
                    phase + "-intent",
                    {"status": "outcome_uncertain", "review": review},
                )

            outcome = {"status": "outcome_uncertain", "production_source_edit_qualified": False}
            try:
                budget = ReadBudget(max_requests=1, max_bytes=64 * 1024)
                async with self.workspace.reader.wire(session, budget, request) as transport:
                    reply = await confirmed_exchange(
                        session["app"],
                        request,
                        single_attempt=True,
                        before_send=before_send,
                        response_timeout=2,
                    )
                if (
                    not isinstance(reply, SimpleAckPDU)
                    or reply.pduSource != session["target"]
                    or reply.apduInvokeID != request.apduInvokeID
                    or reply.apduService != request.apduService
                ):
                    raise ValueError(
                        "The source experiment did not return the matching acknowledgement."
                    )
                outcome.update(
                    status="acknowledged_unverified", transport_evidence=copy.deepcopy(transport)
                )
            except ErrorRejectAbortNack as exc:
                # A rejection is evidence against this method, never permission
                # to retry, force a property, or enter another device mode.
                if (
                    exc.pduSource == session["target"]
                    and exc.apduInvokeID == request.apduInvokeID
                    and (not isinstance(exc, ErrorPDU) or exc.apduService == request.apduService)
                ):
                    outcome.update(
                        status="native_rejection",
                        native_error=str(exc),
                        transport_evidence=copy.deepcopy(transport),
                    )
                    if isinstance(exc, ErrorPDU):
                        outcome["error_class"] = int(exc.errorClass)
                        outcome["error_code"] = int(exc.errorCode)
                else:
                    outcome["error"] = "Native error response identity/service mismatch."
            except (ValueError, TimeoutError) as exc:
                outcome["error"] = str(exc) or "The reply window expired."
            self.mappings._record(operation_id, phase + "-response", outcome)
            return outcome

    async def verify(self, *, operation_id, restored=False, method="bacnet"):
        records, owner, created_id = self._owned(operation_id)
        phase = self._phase(method, restored)
        attempt = records.get(phase + "-intent")
        if attempt is None:
            raise ValueError("No retained source experiment exists to verify.")
        review = attempt["review"]
        options = DeviceDetailsRequest(**owner["native"]["target"])
        async with self.mappings._lease(options) as session:
            native = await self.mappings._engine(session, options)
            if native["binding_sha256"] != owner["native"]["binding_sha256"]:
                raise ValueError("The native engine/interface changed during verification.")
            failures = []
            for source in (review["replacement_source"], review["expected_source"]):
                try:
                    point = await self._snapshot(session, owner, created_id, source)
                except ValueError as exc:
                    failures.append(str(exc))
                    continue
                expected = copy.deepcopy(review["point"]["fields"])
                expected["32589"] = source
                if point["fields"] != expected:
                    raise ValueError("Temporary point changed more than its source.")
                result = {
                    "status": "replacement_source_verified"
                    if source == review["replacement_source"]
                    else "original_source_verified",
                    "source": source,
                    "point": point,
                    "native": native,
                    "production_source_edit_qualified": False,
                }
                self.mappings._record(operation_id, phase + "-verification", result)
                return result
            return {
                "status": "outcome_uncertain",
                "errors": failures,
                "production_source_edit_qualified": False,
            }
