"""Observe command priorities on the root network inputs named by a retained application."""

import copy
import json
import math
import secrets

from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field

from .application_store import encoded, evidence, identifier, utc
from .device_details import DeviceDetailsRequest
from .moi_identity import MoiIdentity, seal
from .property_evidence import PropertyEvidence

PROFILE = "native-network-input-commands/1"
TYPES = {526: 2, 528: 19, 530: 5}
PROPERTIES = (
    "object-name",
    "present-value",
    "priority-array",
    "relinquish-default",
    "reliability",
    "out-of-service",
    "status-flags",
)
IDENTITY_FIELDS = (
    "device",
    "object-name",
    "vendor-identifier",
    "model-name",
    "firmware-revision",
    "application-software-version",
)


class NetworkInputRead(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    capture_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    offset: int = Field(default=0, ge=0, le=131072, strict=True)
    limit: int = Field(default=16, ge=1, le=32, strict=True)
    baseline_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


def root_network_inputs(image):
    app = MoiIdentity(image)
    scalar = app.reader.scalar
    roots = [r for r in app.records if r["class_id"] == 575]
    if len(roots) > 1:
        roots = [
            r
            for r in roots
            if isinstance(ref := scalar(r, 32527), str)
            and ref.rpartition("/")[0] == app.ref
            and "." not in ref.rpartition("/")[2]
        ]
    if len(roots) != 1 or not isinstance(scope := scalar(roots[0], 32527), str) or not scope:
        raise ValueError("The retained application requires one identifiable root activity.")
    found = {}
    references = set()
    unresolved = []
    for r in app.records:
        kind = r["class_id"]
        if kind not in TYPES:
            continue
        ref = scalar(r, 32527)
        if not isinstance(ref, str) or ref.rpartition(".")[0] != scope:
            continue
        if ref in references:
            raise ValueError("The retained network input has an ambiguous BACnet identity.")
        references.add(ref)
        flags = (scalar(r, 3807), scalar(r, 2567))
        if any(flag is False for flag in flags):
            continue
        oid, name = scalar(r, 75), scalar(r, 2390)
        if (
            any(flag is not True for flag in flags)
            or not isinstance(oid, str)
            or not isinstance(name, str)
            or not name
        ):
            unresolved.append(ref)
            continue
        ident = ObjectIdentifier(oid)
        if (
            int(ident[0]) != TYPES[kind]
            or int(ident[1]) > 4194302
            or str(ident) != oid
            or oid in found
        ):
            raise ValueError("The retained network input has an ambiguous BACnet identity.")
        found[oid] = {"object": oid, "name": name, "reference": ref}
    ordered = sorted(found.values(), key=lambda p: tuple(ObjectIdentifier(p["object"])))
    return ordered, unresolved


def scalar_value(value):
    return (
        value["value"]
        if isinstance(value, dict) and "native_datatype" in value and "value" in value
        else value
    )


def valid_input_value(kind, value):
    if kind == "analog-value":
        return type(value) in (int, float) and math.isfinite(value)
    if kind == "multi-state-value":
        return type(value) is int and 1 <= value <= 4294967295
    if isinstance(value, dict) and value.get("native_datatype") in ("BinaryPV", "Enumerated"):
        value = value.get("value")
    return kind == "binary-value" and type(value) is int and value in (0, 1)


def valid_slot(kind, slot):
    if not isinstance(slot, dict) or "value" not in slot:
        return False
    if slot.get("type") == "null":
        return slot["value"] is None
    tag = {"analog-value": "real", "binary-value": "enumerated", "multi-state-value": "unsigned"}
    return slot.get("type") == tag.get(kind) and valid_input_value(kind, slot["value"])


def observe_point(expected, result, target, config):
    point = {
        **expected,
        "verified": False,
        "values": {},
        "unavailable": {},
        "finished_at": result.get("finished_at"),
    }
    objects = result.get("objects", [])
    if result.get("target") != target or result.get("connector_config") != config:
        point["unavailable"]["identity"] = (
            "The field response belongs to a different route or interface."
        )
        return point
    if result.get("identity_verified") is not True:
        details = " ".join(str(e) for e in result.get("errors", [])[:3])
        point["unavailable"]["identity"] = (
            "The responding Device could not be verified. " + details
        ).strip()
        return point
    if (
        len(objects) != 1
        or objects[0].get("object") != expected["object"]
        or objects[0].get("identity_verified") is not True
    ):
        point["unavailable"]["identity"] = (
            "The requested BACnet input did not return its expected object identifier."
        )
        return point
    props = objects[0].get("properties", {})
    if (
        props.get("object-name", {}).get("status") != "ok"
        or props["object-name"].get("value") != expected["name"]
    ):
        point["unavailable"]["object-name"] = (
            "The live name differs from the retained input, or is unreadable."
        )
        return point
    for key in PROPERTIES:
        row = props.get(key, {})
        if row.get("status") == "ok" and "value" in row:
            point["values"][key] = row["value"]
        else:
            point["unavailable"][key] = row.get("status", "missing")
    v = point["values"]
    kind = expected["object"].split(",", 1)[0]
    for key in ("present-value", "relinquish-default"):
        if key in v and not valid_input_value(kind, v[key]):
            point["unavailable"][key] = "Unexpected BACnet value for this input type."
    slots = v.get("priority-array")
    if (
        not isinstance(slots, list)
        or len(slots) != 16
        or not all(valid_slot(kind, slot) for slot in slots)
    ):
        point["unavailable"]["priority-array"] = "Expected all 16 typed priority slots."
    flags = v.get("status-flags")
    reliability = v.get("reliability")
    if isinstance(reliability, dict) and reliability.get("native_datatype") == "Reliability":
        reliability = scalar_value(reliability)
    healthy = (
        type(reliability) is int
        and reliability == 0
        and v.get("out-of-service") is False
        and isinstance(flags, list)
        and len(flags) == 4
        and all(type(flag) in (int, bool) and flag in (0, 1) for flag in flags)
        and flags[1] == 0
        and flags[3] == 0
    )
    point["verified"] = not point["unavailable"] and healthy
    if not healthy:
        point["unavailable"]["quality"] = "Review reliability, service state and status flags."
    return point


def compare_points(before, after):
    changes = []
    for original, current in zip(before, after, strict=True):
        if (original["object"], original["name"], original["reference"]) != (
            current["object"],
            current["name"],
            current["reference"],
        ):
            raise ValueError("The two observations refer to different network inputs.")
        row = {
            "object": current["object"],
            "status": "unverified",
            "priority_changes": [],
            "changed_fields": [],
        }
        if original["verified"] and current["verified"]:
            old, new = original["values"], current["values"]
            for priority, (a, b) in enumerate(
                zip(old["priority-array"], new["priority-array"], strict=True), 1
            ):
                if encoded(a) != encoded(b):
                    row["priority_changes"].append({"priority": priority, "before": a, "after": b})
            row["changed_fields"] = [
                key
                for key in PROPERTIES
                if key not in ("priority-array", "object-name")
                and encoded(old[key]) != encoded(new[key])
            ]
            row["status"] = "changed" if row["priority_changes"] else "unchanged"
        changes.append(row)
    return changes


class NetworkInputReports:
    def __init__(self, native, workspace):
        self.native, self.workspace = native, workspace
        with native.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS native_network_input_reports (id TEXT PRIMARY KEY, capture TEXT NOT NULL, body BLOB NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS native_network_input_capture ON native_network_input_reports(capture)"
            )

    def get(self, report_id):
        with self.native.store.connect() as db:
            row = db.execute(
                "SELECT body FROM native_network_input_reports WHERE id=?", (identifier(report_id),)
            ).fetchone()
        if row is None:
            raise ValueError("The saved network input observation was not found.")
        report = json.loads(row[0])
        digest = report.pop("evidence_sha256", None)
        if (
            report.get("id") != report_id
            or report.get("profile") != PROFILE
            or digest != seal(report)
        ):
            raise ValueError("The saved network input observation failed its integrity check.")
        return {**report, "evidence_sha256": digest}

    def history(self, capture_id):
        # Newest entries first. A saved report remains directly accessible by its ID.
        with self.native.store.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM native_network_input_reports WHERE capture=? ORDER BY rowid DESC LIMIT 32",
                    (identifier(capture_id),),
                )
            ]
        result = []
        for report_id in ids:
            r = self.get(report_id)
            result.append(
                {
                    "id": report_id,
                    "finished_at": r["finished_at"],
                    "offset": r["selection"]["offset"],
                    "limit": r["selection"]["limit"],
                    "verified": sum(p["verified"] for p in r["points"]),
                    "points": len(r["points"]),
                }
            )
        return result

    async def read(self, options):
        native = self.native
        snapshot, files = native.storage.load(options.capture_id)
        target = options.model_dump(include={"router", "dnet", "address", "device"})
        if (
            snapshot.get("evidence_sha256") != options.snapshot_sha256
            or not snapshot.get("source_identity_matches")
            or {**snapshot["target"], "device": snapshot["device"]} != target
        ):
            raise ValueError("Select the original controller route and its verified capture.")
        identity = {k: snapshot["identity"][k] for k in IDENTITY_FIELDS}
        inputs, unresolved = root_network_inputs(files[3])
        if options.offset and options.offset >= len(inputs):
            raise ValueError("That network input page lies beyond the retained application.")
        page = inputs[options.offset : options.offset + options.limit]
        selection = {
            "capture_id": options.capture_id,
            "snapshot_sha256": options.snapshot_sha256,
            "scope": "root-exposed-commandable-file-3",
            "target": target,
            "identity": identity,
            "offset": options.offset,
            "limit": options.limit,
        }
        before = self.get(options.baseline_id) if options.baseline_id else None
        if before and before["selection"] != selection:
            raise ValueError("Select a baseline for the same capture, controller and input page.")
        async with native.operation(options.operation_id, "read-network-input-commands"):
            app = native.bacnet.require()
            config = copy.deepcopy(native.bacnet.config)
            if before and before["connector_config"] != config:
                raise ValueError("Reconnect the field interface used for the baseline reading.")

            async def verify_device():
                if native.bacnet.require() is not app or native.bacnet.config != config:
                    raise ValueError("The field interface changed during network input inspection.")
                async with native.path._path(options) as session:
                    PropertyEvidence.pin(session, options.router)
                    actual = await native.instances._identity(session, options.device)
                if any(actual.get(k) != val for k, val in identity.items()):
                    raise ValueError(
                        "Current controller name, model, firmware or Device identity differs from the capture."
                    )
                return actual

            started = utc()
            opening = await verify_device()
            points = []
            for p in page:
                if native.bacnet.require() is not app or native.bacnet.config != config:
                    raise ValueError("The field interface changed during network input inspection.")
                native.phase("reading network input " + p["object"])
                result = await self.workspace.properties(
                    **target, object_ids=[p["object"]], properties=list(PROPERTIES)
                )
                points.append(observe_point(p, result, target, config))
            closing = await verify_device()
            if opening != closing:
                raise ValueError(
                    "The controller application identity changed while its inputs were being read."
                )
            comparison = compare_points(before["points"], points) if before else None
            report = evidence(
                {
                    "id": secrets.token_hex(16),
                    "profile": PROFILE,
                    "read_only": True,
                    "selection": selection,
                    "started_at": started,
                    "finished_at": utc(),
                    "connector_config": config,
                    "opening_identity": opening,
                    "closing_identity": closing,
                    "source_sha256": snapshot["files"]["3"]["sha256"],
                    "input_count": len(inputs),
                    "unclassified_root_inputs": unresolved,
                    "points": points,
                    "baseline_id": options.baseline_id,
                    "baseline_sha256": before["evidence_sha256"] if before else None,
                    "comparison": comparison,
                }
            )
        with native.store.connect() as db:
            db.execute(
                "INSERT INTO native_network_input_reports(id,capture,body) VALUES(?,?,?)",
                (report["id"], options.capture_id, encoded(report)),
            )
        return report
