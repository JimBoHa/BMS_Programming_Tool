"""One-use, journalled creation of isolated native monitoring test mappings.

Does not edit existing points. In particular, a successful creation does not
qualify an existing point's configuration-only source property as writable.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime

from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned

from .device_details import DeviceDetailsRequest
from .metasys_configuration_api import MONITOR_TYPES, guid
from .property_evidence import ReadBudget

PROFILE = "metasys-temporary-monitor/1"
PLAN_SECONDS = 90


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def nodes(document):
    result, pending = {}, list(document.get("items", []))
    while pending:
        node = pending.pop()
        if type(node) is not dict or len(result) >= 10000:
            raise ValueError("Invalid or excessive configuration tree context.")
        key = guid(node.get("id"))
        if key in result:
            raise ValueError("Duplicate configuration tree identity.")
        result[key] = node
        children = node.get("items", [])
        if type(children) is not list:
            raise ValueError("Invalid configuration tree children.")
        pending.extend(children)
    return result


def temporary_payload(
    schema, *, parent_id, object_type, local_instance, source_instance, operation_id
):
    if type(operation_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", operation_id):
        raise ValueError("Use a generated temporary-monitor operation identity.")
    if object_type not in MONITOR_TYPES:
        raise ValueError("Only the monitoring mapper families are admitted.")
    for value in (local_instance, source_instance):
        if type(value) is not int or not 0 <= value <= 4194302:
            raise ValueError("Use explicit real local and source instances.")
    properties = schema.get("properties", {})
    required = schema.get("required")
    if type(properties) is not dict or type(required) is not list:
        raise ValueError("A complete current creation schema is required.")
    kind = MONITOR_TYPES[object_type]
    default_oid = properties.get("objectIdentifier", {}).get("default", {})
    if default_oid.get("bacnetObjectType") != kind:
        raise ValueError("Creation schema local type differs from the selected mapper family.")
    item = {
        "name": "BMS source probe " + operation_id[:12],
        "description": "BMS temporary source test " + operation_id,
        "objectCategory": "objectCategoryEnumSet.generalCategory",
        "objectIdentifier": {"bacnetObjectType": kind, "instance": local_instance},
        "userNameIsBacnetObjName": False,
        "instanceNumber": source_instance,
    }
    if object_type == "objectTypeEnumSet.bacnetDeviceClass":
        item.update(manTimeSyncType="timeSyncChoiceEnumSet.tscNoTimeBcast", disableAutoAlarm=True)
    else:
        item.update(intrinsicAlarmingDefined=False, useRemoteAlarming=False)
        optional_defaults = ("statesText", "userSelectedStatesText", "displayPrecision")
        for key in optional_defaults:
            if key in properties:
                if "default" not in properties[key]:
                    raise ValueError("Monitoring schema did not supply a required display default.")
                item[key] = copy.deepcopy(properties[key]["default"])
    if any(key not in item for key in required):
        raise ValueError("Creation has additional unqualified required configuration.")
    for key, value in item.items():
        field = properties.get(key)
        if type(field) is not dict or field.get("readOnly") is True:
            raise ValueError("Creation schema does not admit the exact monitoring fields.")
        if field.get("maxLength") is not None and isinstance(value, str):
            if len(value) > field["maxLength"]:
                raise ValueError("Temporary monitoring label exceeds the native field width.")
    # There is deliberately no Present Value, priority, clock, output command,
    # historian, control link, auto-restore or caller-supplied attribute payload.
    return {
        "parentId": guid(parent_id),
        "localUniqueIdentifier": "BMS-SM-" + operation_id[:16],
        "objectType": object_type,
        "item": item,
    }


class MetasysTemporaryMapping:
    def __init__(self, workspace, api, directory):
        self.workspace, self.api, self.directory = workspace, api, directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._plans = {}
        self.journal = directory / "temporary-mappings.sqlite3"
        # This database is the tool's own local recovery journal. It never
        # connects to, or edits, the Metasys configuration database.
        descriptor = (
            os.open(self.journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            if not self.journal.exists()
            else None
        )
        if descriptor is not None:
            os.close(descriptor)
        with self._database() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    engine_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    review TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_unresolved_engine
                    ON operations(engine_id) WHERE status = 'outcome_uncertain';
                CREATE TABLE IF NOT EXISTS events (
                    operation_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    body TEXT NOT NULL,
                    PRIMARY KEY(operation_id, phase),
                    FOREIGN KEY(operation_id) REFERENCES operations(operation_id)
                );
            """)

    @contextmanager
    def _database(self):
        db = sqlite3.connect(self.journal, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @asynccontextmanager
    async def _lease(self, options):
        async with asyncio.timeout(60):
            async with self.workspace.path._path(options) as session:
                yield session

    def _record(self, operation_id, phase, value):
        body = {
            "profile": PROFILE,
            "operation_id": operation_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            **value,
        }
        raw = json.dumps(body, sort_keys=True, allow_nan=False)
        try:
            with self._database() as db:
                if phase == "intent":
                    review = value["review"]
                    db.execute(
                        "INSERT INTO operations VALUES (?, ?, 'outcome_uncertain', ?)",
                        (operation_id, review["engine_id"], json.dumps(review, allow_nan=False)),
                    )
                elif phase in (
                    "probe-intent",
                    "restore-intent",
                    "api-probe-intent",
                    "api-restore-intent",
                    "cleanup-intent",
                ):
                    if (
                        db.execute(
                            "UPDATE operations SET status='outcome_uncertain' WHERE operation_id=?",
                            (operation_id,),
                        ).rowcount
                        != 1
                    ):
                        raise ValueError("Source experiment has no retained creation ownership.")
                db.execute("INSERT INTO events VALUES (?, ?, ?)", (operation_id, phase, raw))
                if phase == "result":
                    db.execute(
                        "UPDATE operations SET status = ? WHERE operation_id = ?",
                        (value["status"], operation_id),
                    )
                elif phase.endswith("-verification"):
                    if value.get("status") == "temporary_mapping_removed_verified":
                        db.execute(
                            "UPDATE operations SET status='removed_verified' WHERE operation_id=?",
                            (operation_id,),
                        )
                        return body
                    row = db.execute(
                        "SELECT review FROM operations WHERE operation_id=?", (operation_id,)
                    ).fetchone()
                    original_source = json.loads(row[0])["payload"]["item"]["instanceNumber"]
                    if type(value.get("source")) is int and value["source"] == original_source:
                        db.execute(
                            "UPDATE operations SET status='created_configuration_verified' WHERE operation_id=?",
                            (operation_id,),
                        )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "A creation was already recorded or an engine outcome needs reconciliation."
            ) from exc
        return body

    def records(self, operation_id):
        with self._database() as db:
            return {
                phase: json.loads(body)
                for phase, body in db.execute(
                    "SELECT phase, body FROM events WHERE operation_id = ? ORDER BY rowid",
                    (operation_id,),
                )
            }

    def discard_reviews(self):
        """Cancel local reviews without touching a configuration resource."""
        self._plans.clear()

    async def _engine(self, session, options):
        ws = self.workspace
        ws.reader.pin(session, options.router)
        budget, report = ReadBudget(max_requests=20, max_bytes=256 * 1024), {}
        report = ws._report(options, "metasys-engine-binding")
        await ws._identity(session, budget, options, report, "before")
        fields = {}
        evidence = {}
        for prop in [
            "vendor-identifier",
            "model-name",
            "firmware-revision",
            "32527",
            "system-status",
            "backup-and-restore-state",
        ]:
            value, row = await ws._read(session, budget, options.device, prop)
            evidence[prop] = row
            if row["status"] != "ok":
                raise ValueError(
                    "The selected engine's current identity/configuration was not read."
                )
            if prop == "vendor-identifier":
                if not isinstance(value, Unsigned) or value != 5:
                    raise ValueError("A responding vendor-5 supervisory engine is required.")
                fields[prop] = int(value)
            elif prop in ("system-status", "backup-and-restore-state"):
                if not isinstance(value, Enumerated) or int(value) != 0:
                    raise ValueError("The selected engine is not operational and idle.")
                fields[prop] = int(value)
            elif not isinstance(value, CharacterString) or not str(value).strip():
                raise ValueError("The selected engine's native identity has an unexpected type.")
            else:
                fields[prop] = str(value)
        await ws._identity(session, budget, options, report, "after")
        binding = {
            "target": options.model_dump(),
            "connector_config": copy.deepcopy(session["config"]),
            "fields": fields,
        }
        return {
            **binding,
            "binding_sha256": sha(binding),
            "property_evidence": evidence,
            "identity_checks": report["identity_checks"],
        }

    async def _free_local(self, session, object_type, local_instance):
        kinds = {
            "objectTypeEnumSet.bacnetDeviceClass": 508,
            "objectTypeEnumSet.bacnetAiClass": 0,
            "objectTypeEnumSet.bacnetBvClass": 5,
        }
        if object_type not in kinds:
            raise ValueError("Unqualified temporary mapping class.")
        if type(local_instance) is not int or not 0 <= local_instance <= 4194302:
            raise ValueError("Use an explicit local monitoring instance.")
        budget = ReadBudget(max_requests=2, max_bytes=64 * 1024)
        _, row = await self.workspace._read(
            session,
            budget,
            str(ObjectIdentifier((kinds[object_type], local_instance))),
            "object-identifier",
        )
        native = row.get("native_error", {})
        if (
            row.get("status") != "native_error"
            or native.get("errorClass", {}).get("value") != 1
            or native.get("errorCode", {}).get("value") != 31
        ):
            raise ValueError(
                "The proposed local identifier is occupied or absence was not confirmed."
            )
        return row

    async def _category_permission(self):
        enum = await self.api.enumeration("objectCategoryEnumSet", configuration_categories=True)
        if not any(
            v.get("const") == "objectCategoryEnumSet.generalCategory" for v in enum.get("oneOf", [])
        ):
            raise ValueError("General monitoring configuration permission is not available.")

    async def _context(self, engine_id, parent_id, native):
        engine = await self.api.network_device(engine_id)
        reference = native["fields"]["32527"]
        if engine.get("itemReference") != reference:
            raise ValueError("Native engine reference differs from authenticated server metadata.")
        context = nodes(await self.api.tree_context(parent_id))
        if engine_id not in context or parent_id not in context:
            raise ValueError("The selected engine and parent were not in the current tree context.")
        visited, current = set(), parent_id
        while current != engine_id:
            if current in visited or current not in context:
                raise ValueError("The selected parent does not belong to the selected engine.")
            visited.add(current)
            current = self.api.resource_guid(context[current].get("parentUrl"))
        if context[engine_id].get("itemReference") != reference:
            raise ValueError("Tree context changed its native engine reference.")
        return engine, context[parent_id]

    async def prepare(
        self, *, target, engine_id, parent_id, object_type, local_instance, source_instance
    ):
        if len(self._plans) >= 16:
            raise ValueError("Temporary-monitor review limit reached; discard local reviews.")
        engine_id, parent_id = guid(engine_id), guid(parent_id)
        options = DeviceDetailsRequest(**target)
        ws = self.workspace
        async with self._lease(options) as session:
            account = self.api.session_key
            native = await self._engine(session, options)
            absence = await self._free_local(session, object_type, local_instance)
            await self._category_permission()
            engine, parent = await self._context(engine_id, parent_id, native)
            expected_parent = (
                "objectTypeEnumSet.bacnetIntegrationClass"
                if object_type == "objectTypeEnumSet.bacnetDeviceClass"
                else "objectTypeEnumSet.bacnetDeviceClass"
            )
            if parent.get("objectType") != expected_parent:
                raise ValueError("The selected monitoring parent has a different native class.")
            schema = (await self.api.creation_schema(parent_id, object_type))["schema"]
            if object_type == "objectTypeEnumSet.bacnetDeviceClass":
                enum = await self.api.enumeration("timeSyncChoiceEnumSet")
                if not any(
                    v.get("const") == "timeSyncChoiceEnumSet.tscNoTimeBcast"
                    for v in enum.get("oneOf", [])
                ):
                    raise ValueError("No qualified no-time-command creation mode was exposed.")
            operation_id = secrets.token_hex(16)
            payload = temporary_payload(
                schema,
                parent_id=parent_id,
                object_type=object_type,
                local_instance=local_instance,
                source_instance=source_instance,
                operation_id=operation_id,
            )
            children = nodes(await self.api.children(parent_id))
            reference = parent["itemReference"] + "." + payload["localUniqueIdentifier"]
            if any(v.get("itemReference") == reference for v in children.values()):
                raise ValueError("Temporary monitor reference is already occupied.")
            ws.path._guard(session)
            if self.api.session_key != account:
                raise ValueError("Configuration account/session changed during preparation.")
            review = {
                "profile": PROFILE,
                "operation_id": operation_id,
                "engine_id": engine_id,
                "configuration_session": account,
                "parent_id": parent_id,
                "expected_reference": reference,
                "native": native,
                "engine": engine,
                "parent": parent,
                "schema_sha256": sha(schema),
                "payload": payload,
                "source_edit_qualified": False,
                "local_absence_evidence": absence,
                "scope": "Create one isolated monitoring object; no existing source edits.",
            }
            review["review_sha256"] = sha(review)
            token = secrets.token_urlsafe(24)
            self._plans[operation_id] = (
                copy.deepcopy(review),
                token,
                time.monotonic(),
                (session["app"], session["evidence_socket"]),
            )
            return {**review, "token": token}

    async def create(self, *, operation_id, token, review_sha256):
        stored = self._plans.pop(operation_id, None)
        if stored is None:
            raise ValueError("Temporary-monitor review was already consumed or does not exist.")
        review, expected_token, made, connector = stored
        if (
            type(token) is not str
            or not secrets.compare_digest(token, expected_token)
            or review_sha256 != review["review_sha256"]
            or time.monotonic() - made > PLAN_SECONDS
            or self.api.session_key != review["configuration_session"]
        ):
            raise ValueError("Temporary-monitor review is stale or does not match.")
        ws = self.workspace
        options = DeviceDetailsRequest(**review["native"]["target"])
        async with self._lease(options) as session:
            native = await self._engine(session, options)
            if session["app"] is not connector[0] or session["evidence_socket"] is not connector[1]:
                raise ValueError("Selected native connector reopened; review again.")
            if native["binding_sha256"] != review["native"]["binding_sha256"]:
                raise ValueError("Selected native engine/interface changed; review again.")
            engine, parent = await self._context(review["engine_id"], review["parent_id"], native)
            if engine != review["engine"] or parent != review["parent"]:
                raise ValueError("Configuration parent/engine context changed; review again.")
            schema = (
                await self.api.creation_schema(review["parent_id"], review["payload"]["objectType"])
            )["schema"]
            if sha(schema) != review["schema_sha256"]:
                raise ValueError("Monitoring creation schema changed; review again.")
            await self._category_permission()
            await self._free_local(
                session,
                review["payload"]["objectType"],
                review["payload"]["item"]["objectIdentifier"]["instance"],
            )
            children = nodes(await self.api.children(review["parent_id"]))
            if any(
                v.get("itemReference") == review["expected_reference"] for v in children.values()
            ):
                raise ValueError("Temporary monitor reference became occupied.")
            ws.path._guard(session)
            if self.api.session_key != review["configuration_session"]:
                raise ValueError("Configuration account/session changed; review again.")
            self._record(operation_id, "intent", {"status": "outcome_uncertain", "review": review})
            try:
                # Exactly one request; no retry, source edit, command or fallback.
                from .metasys_configuration_api import PREFIX

                reply = await self.api._request(
                    "POST", PREFIX + "/v6/objects", body=review["payload"]
                )
                self._record(
                    operation_id,
                    "response",
                    {
                        "http_status": reply.http_status,
                        "location": reply.location,
                        "response": reply.data,
                    },
                )
                ws.path._guard(session)
                if self.api.session_key != review["configuration_session"]:
                    raise ValueError("Configuration account/session changed during creation.")
                # The online UI proxy has been observed returning 200 with the
                # same Location contract documented as 201 by the public API.
                # Neither status alone qualifies creation: verify that resource.
                if reply.http_status not in (200, 201) or reply.location is None:
                    raise ValueError("Create did not return a verifiable new resource location.")
                created_id = self.api.resource_guid(reply.location)
                result = await self._verify_created(review, created_id)
                ws.path._guard(session)
                if self.api.session_key != review["configuration_session"]:
                    raise ValueError("Configuration account/session changed during verification.")
                self._record(operation_id, "result", result)
                return result
            except BaseException:
                # Intent remains unresolved. Never replay or silently delete a
                # resource whose creation or verification has an uncertain outcome.
                raise

    async def _verify_created(self, review, created_id):
        created = await self.api.object(created_id, view="viewNameEnumSet.focusView")
        context = nodes(await self.api.tree_context(created_id))
        node = context.get(created_id, {})
        item, original = created["item"], review["payload"]["item"]
        oid = item.get("objectIdentifier", {})
        if (
            item.get("name") != original["name"]
            or item.get("description") != original["description"]
            or node.get("itemReference") != review["expected_reference"]
            or self.api.resource_guid(node.get("parentUrl")) != review["parent_id"]
            or item.get("itemReference", review["expected_reference"])
            != review["expected_reference"]
            or created.get("objectType") != review["payload"]["objectType"]
            or self.api.resource_guid(created.get("parentUrl")) != review["parent_id"]
            or type(oid.get("instance")) is not int
            or oid != original["objectIdentifier"]
        ):
            raise ValueError("Created monitoring object did not match the reviewed identity.")
        source = await self.api.attribute(created_id, "instanceNumber")
        instance = source.get("item", {}).get("instanceNumber")
        if type(instance) is not int or instance != original["instanceNumber"]:
            raise ValueError("Created monitoring object did not retain its reviewed source.")
        return {
            "status": "created_configuration_verified",
            "created_id": created_id,
            "created": created,
            "created_context": node,
            "source": source,
            "native_activation_verified": False,
            "source_edit_qualified": False,
        }

    async def reconcile(self, operation_id):
        """Read-only recovery after an uncertain reply, including after restart.

        Absence in navigation does not prove rejection. Never repeats a create,
        edits a source, commands a value or deletes a resource.
        """
        records = self.records(operation_id)
        if "intent" not in records:
            raise ValueError("No retained temporary-monitor intent exists.")
        if "result" in records:
            return records["result"]
        review = records["intent"]["review"]
        options = DeviceDetailsRequest(**review["native"]["target"])
        async with self._lease(options) as session:
            native = await self._engine(session, options)
            if native["binding_sha256"] != review["native"]["binding_sha256"]:
                raise ValueError("Native engine/interface differs from the retained intent.")
            await self._context(review["engine_id"], review["parent_id"], native)
            children = nodes(await self.api.children(review["parent_id"]))
            matches = [
                key
                for key, item in children.items()
                if item.get("itemReference") == review["expected_reference"]
            ]
            if len(matches) != 1:
                return {
                    "status": "outcome_uncertain",
                    "matching_resources": len(matches),
                    "source_edit_qualified": False,
                }
            result = await self._verify_created(review, matches[0])
            self.workspace.path._guard(session)
            self._record(operation_id, "result", result)
            return result

    def _cleanup_owner(self, operation_id):
        records = self.records(operation_id)
        if "intent" not in records or "result" not in records:
            raise ValueError("Cleanup requires a verified tool-created temporary mapping.")
        with self._database() as db:
            row = db.execute(
                "SELECT status FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
        if row is None or row[0] != "created_configuration_verified" or "cleanup-intent" in records:
            raise ValueError(
                "The temporary mapping has an unresolved outcome or cleanup was already dispatched."
            )
        return records["intent"]["review"], records["result"]["created_id"]

    async def _cleanup_snapshot(self, session, owner, created_id):
        created = await self._verify_created(owner, created_id)
        children = nodes(await self.api.children(created_id))
        if set(children) - {created_id}:
            raise ValueError(
                "Temporary mapping has children or extensions; cleanup is unavailable."
            )
        local = owner["payload"]["item"]["objectIdentifier"]
        number = {
            "objectTypeEnumSet.bacnetDeviceClass": 508,
            "objectTypeEnumSet.bacAiClass": 0,
            "objectTypeEnumSet.bacBvClass": 5,
        }[local["bacnetObjectType"]]
        oid = ObjectIdentifier((number, local["instance"]))
        budget, evidence = ReadBudget(max_requests=4, max_bytes=128 * 1024), {}
        for prop in ("object-identifier", "32527", "32589"):
            value, row = await self.workspace._read(session, budget, str(oid), prop)
            evidence[prop] = row
            if row.get("status") != "ok":
                raise ValueError("Native temporary mapping identity was not read before cleanup.")
            if prop == "object-identifier" and (
                not isinstance(value, ObjectIdentifier) or value != oid
            ):
                raise ValueError("Native temporary mapping identifier changed before cleanup.")
            if prop == "32527" and (
                not isinstance(value, CharacterString) or str(value) != owner["expected_reference"]
            ):
                raise ValueError("Native temporary mapping reference changed before cleanup.")
            if prop == "32589" and (
                not isinstance(value, Unsigned)
                or int(value) != owner["payload"]["item"]["instanceNumber"]
            ):
                raise ValueError("Restore the original temporary source before cleanup.")
        return {"created": created, "native_properties": evidence}

    async def prepare_cleanup(self, operation_id):
        owner, created_id = self._cleanup_owner(operation_id)
        options = DeviceDetailsRequest(**owner["native"]["target"])
        async with self._lease(options) as session:
            account = self.api.session_key
            native = await self._engine(session, options)
            if native["binding_sha256"] != owner["native"]["binding_sha256"]:
                raise ValueError(
                    "Native engine/interface differs from the temporary mapping owner."
                )
            await self._context(owner["engine_id"], owner["parent_id"], native)
            snapshot = await self._cleanup_snapshot(session, owner, created_id)
            self.workspace.reader.guard(session)
            if account != self.api.session_key:
                raise ValueError("Configuration account changed during cleanup review.")
            review = {
                "profile": PROFILE,
                "operation_id": operation_id,
                "created_id": created_id,
                "configuration_session": account,
                "native": native,
                "snapshot": snapshot,
                "scope": "Remove this owned isolated temporary mapping only; no child cascade or production deletion.",
            }
            review["review_sha256"] = sha(review)
            token = secrets.token_urlsafe(24)
            if len(self._plans) >= 16:
                raise ValueError("Discard local reviews before preparing another cleanup.")
            self._plans[(operation_id, "cleanup")] = (
                copy.deepcopy(review),
                token,
                time.monotonic(),
                (session["app"], session["evidence_socket"]),
            )
            return {**review, "token": token}

    async def cleanup(self, *, operation_id, token, review_sha256):
        stored = self._plans.pop((operation_id, "cleanup"), None)
        if stored is None:
            raise ValueError("Cleanup review was consumed or does not exist.")
        review, expected_token, made, connector = stored
        if (
            type(token) is not str
            or not secrets.compare_digest(token, expected_token)
            or review_sha256 != review["review_sha256"]
            or time.monotonic() - made > PLAN_SECONDS
            or self.api.session_key != review["configuration_session"]
        ):
            raise ValueError("Cleanup review is stale or does not match.")
        owner, created_id = self._cleanup_owner(operation_id)
        options = DeviceDetailsRequest(**owner["native"]["target"])
        async with self._lease(options) as session:
            native = await self._engine(session, options)
            if (
                session["app"] is not connector[0]
                or session["evidence_socket"] is not connector[1]
                or native["binding_sha256"] != review["native"]["binding_sha256"]
            ):
                raise ValueError("Native engine/interface changed before cleanup.")
            await self._context(owner["engine_id"], owner["parent_id"], native)
            await self._cleanup_snapshot(session, owner, created_id)
            self.workspace.reader.guard(session)
            if (
                self.api.session_key != review["configuration_session"]
                or time.monotonic() - made > PLAN_SECONDS
            ):
                raise ValueError("Cleanup review expired or configuration account changed.")
            self._record(
                operation_id, "cleanup-intent", {"status": "outcome_uncertain", "review": review}
            )
            from .metasys_configuration_api import PREFIX

            reply = await self.api._request("DELETE", PREFIX + "/v6/objects/" + created_id)
            result = {"status": "removal_acknowledged_unverified", "http_status": reply.http_status}
            self._record(operation_id, "cleanup-response", result)
            return result

    async def verify_removed(self, operation_id):
        records = self.records(operation_id)
        if "cleanup-intent" not in records:
            raise ValueError("No owned temporary-mapping cleanup was dispatched.")
        owner = records["intent"]["review"]
        options = DeviceDetailsRequest(**owner["native"]["target"])
        async with self._lease(options) as session:
            native = await self._engine(session, options)
            if native["binding_sha256"] != owner["native"]["binding_sha256"]:
                raise ValueError("Native engine/interface changed during cleanup verification.")
            # Native unknown-object and authenticated navigation absence are
            # independent; an HTTP 404 alone cannot establish removal.
            absent = await self._free_local(
                session,
                owner["payload"]["objectType"],
                owner["payload"]["item"]["objectIdentifier"]["instance"],
            )
            children = nodes(await self.api.children(owner["parent_id"]))
            created_id = records["result"]["created_id"]
            if created_id in children or any(
                x.get("itemReference") == owner["expected_reference"] for x in children.values()
            ):
                raise ValueError("Temporary mapping remains in authenticated navigation.")
            self.workspace.reader.guard(session)
            result = {
                "status": "temporary_mapping_removed_verified",
                "native_absence": absent,
                "created_id": created_id,
                "native": native,
            }
            self._record(operation_id, "cleanup-verification", result)
            return result
