"""Connect the two verified outputs of an installed inline sequence to its original control graph."""

import asyncio
import math
import time

from bacpypes3.apdu import ReadPropertyMultipleACK, ReadPropertyMultipleRequest
from bacpypes3.basetypes import PropertyReference, ReadAccessSpecification
from bacpypes3.primitivedata import Boolean, Enumerated, ObjectIdentifier, Real, TagClass
from pydantic import Field, StrictBool

from . import native_inline_monitor_transfer as monitor
from . import native_inline_shadow as shadow
from .device_details import DeviceDetailsRequest
from .models import StrictModel
from .moi_application import _structs
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_inline_sequence import _wire
from .native_inputs import archive, replace_properties
from .native_parameter_qualification import qualify_parameter_additions
from .native_snapshot_restore import Hash, Identifier, fresh_current

PROFILE = "native-inline-elapsed-airflow-valve/1"
KIND = "inline-sequence-activate"


class ActivationReview(DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    capture_id: Identifier
    snapshot_sha256: Hash
    observation_receipt_id: Identifier


class ActivationApply(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{32}$")
    review_sha256: Hash
    valve_connection_confirmed: StrictBool
    application_transfer_confirmed: StrictBool


def prepare(native, identity, files, receipt_id, target):
    from bacpypes3.primitivedata import Unsigned

    receipt = native.storage.receipt(receipt_id, include_events=False)
    intent = receipt["intent"]
    outcome = receipt["result"] or {}
    if (
        receipt["pending"]
        or outcome.get("status") != "verified"
        or not outcome.get("operational")
        or intent.get("change_kind") != shadow.KIND
        or intent["target"] != target
        or intent["identity"] != identity
        or not outcome.get("preservation", {}).get("existing_control_connections_preserved")
    ):
        raise ValueError(
            "Activation requires the verified operating station's observation transfer."
        )
    original = shadow.reconstruct(native, intent)
    if MoiIdentity(original).data != MoiIdentity(files[3]).data:
        raise ValueError("The connected application differs from the observed sequence.")
    effective, settings = ParameterApplication(files[3], files[11], files[12]).compile()
    qualification = qualify_parameter_additions(effective, settings)
    app = MoiIdentity(effective)
    report = intent["compilation"]
    root = app.reader.records[report["root_ref"]]
    wires = _structs(root["properties"][3118]["tags"], (Unsigned,) * 4)
    before = [tuple(int(i) for i in t) for t in wires]
    after = before.copy()
    pairs = report["control_edges"]
    if len(pairs) != 2:
        raise ValueError("Expected a heat-enable and final valve connection.")
    for pair in pairs:
        old, new = tuple(pair["before"]), tuple(pair["after"])
        if (
            len(old) != 4
            or len(new) != 4
            or old[2:] != new[2:]
            or after.count(old) != 1
            or old == new
            or new in after
        ):
            raise ValueError("The original valve or heat-enable connection changed.")
        after[after.index(old)] = new
    changed = replace_properties(app, root, {3118: b"".join(_wire(*row) for row in after)})
    payload = archive(
        app,
        [
            changed if r["offset"] == root["offset"] else app.data[r["offset"] : r["end_offset"]]
            for r in app.records
        ],
    )
    installed = MoiIdentity(payload)
    zr = installed.reader.records[report["root_ref"]]
    reread = _structs(zr["properties"][3118]["tags"], (Unsigned,) * 4)
    if (
        after != [tuple(int(i) for i in t) for t in reread]
        or len(app.records) != len(installed.records)
        or any(
            a["sha256"] != b["sha256"]
            for a, b in zip(app.records, installed.records, strict=True)
            if a["offset"] != root["offset"]
        )
    ):
        raise ValueError("Verification of the two valve-sequence connections failed.")
    graph = app.reader.diagram(report["root_ref"], retained_activity_refs=True)
    by_name = {b["name"]: b["object"] for b in graph["blocks"]}
    indices = report["runtime"]
    av = report["new_avs"]
    selectors = {
        "flow": [report["points"]["flow"], 85],
        "sample": [by_name["Inline corroborated measured CFM"], 85],
        "mean": [indices["mean"], 85],
        "count": [indices["n_samples"], 85],
        "ready": [indices["ready"], 85],
        "permit": [indices["permit"], 85],
        "proposed_valve": [indices["command"], 85],
        "actual_valve": [report["points"]["valve"], 85],
        "duct": [report["points"]["duct"], 85],
        "threshold": [av["VLV-LOCKOUT-CFM"]["object"], 85],
        "limit": [av["MAX-DA-T"]["object"], 85],
        "clock_witness": [by_name["Inline previous clock second"], 85],
    }
    return payload, {
        "profile": PROFILE,
        "points": report["points"],
        "selectors": selectors,
        "root": report["root_ref"],
        "control_edges": pairs,
        "saved_parameters": settings["matched_parameters"],
        "parameter_qualification": qualification,
        "shadow_receipt_sha256": intent["evidence_sha256"],
        "native_sha256": sha(installed.data),
    }


async def sample(native, session, compilation):
    selectors = compilation["selectors"]
    requests = [
        ReadAccessSpecification(
            objectIdentifier=ObjectIdentifier(oid),
            listOfPropertyReferences=[
                PropertyReference(propertyIdentifier=pid),
                PropertyReference(propertyIdentifier=103),
            ],
        )
        for oid, pid in selectors.values()
    ]
    req = ReadPropertyMultipleRequest(listOfReadAccessSpecs=requests)
    ack = await native.files.exchange(session, req, ReadPropertyMultipleACK)
    rows = ack.listOfReadAccessResults
    if len(rows) != len(selectors):
        raise ValueError("Incomplete running sequence observations.")
    out = {}
    for (name, (oid, pid)), row in zip(selectors.items(), rows, strict=True):
        fields = row.listOfResults
        if (
            str(row.objectIdentifier) != oid
            or len(fields) != 2
            or [int(i.propertyIdentifier) for i in fields] != [pid, 103]
            or any(
                i.propertyArrayIndex is not None or i.readResult.propertyValue is None
                for i in fields
            )
        ):
            raise ValueError(f"Missing identified runtime value or quality for {name}.")
        values = []
        for field in fields:
            tags = list(field.readResult.propertyValue.tagList)
            # RPM's propertyValue choice uses context 4. A native scalar can carry
            # one additional context-3 value wrapper, including on standard ports.
            for context in (4, 3):
                if (
                    len(tags) >= 3
                    and (tags[0].tag_class, int(tags[0].tag_number)) == (TagClass.opening, context)
                    and (tags[-1].tag_class, int(tags[-1].tag_number))
                    == (TagClass.closing, context)
                ):
                    tags = tags[1:-1]
            if len(tags) != 1 or tags[0].tag_class != TagClass.application:
                raise ValueError(
                    f"Unexpected runtime framing for {oid} property {int(field.propertyIdentifier)}: {[(int(t.tag_class), int(t.tag_number)) for t in tags]}."
                )
            values.append(tags[0].app_to_object())
        value, quality = values
        if not isinstance(quality, Enumerated) or int(quality) != 0:
            raise ValueError(f"The running {name} signal is unreliable.")
        if name in ("ready", "permit"):
            if not isinstance(value, Boolean):
                raise ValueError("Invalid Boolean observation.")
            out[name] = bool(value)
        elif not isinstance(value, Real) or not math.isfinite(float(value)):
            raise ValueError("Invalid analog sequence observation.")
        else:
            out[name] = float(value)
    return out


def validate_samples(rows):
    if (
        len(rows) < 36
        or rows[-1]["time"] - rows[0]["time"] < 35
        or any(not 0 < b["time"] - a["time"] <= 2.5 for a, b in zip(rows, rows[1:], strict=False))
    ):
        raise ValueError("A continuous 35-second observation of the actual sequence is required.")
    ticks = {r["clock_witness"] for r in rows}
    if len(ticks) < 28:
        raise ValueError("The sampling clock is not advancing independently.")
    for row in rows:
        if row["threshold"] != 30 or row["limit"] != 125 or row["count"] != 30 or not row["ready"]:
            raise ValueError(
                "The running sequence has not filled a 30-sample window with the reviewed tuning values."
            )
        cap = max(0, min(100, (row["limit"] - row["duct"]) * 10))
        if (
            not 0 <= row["proposed_valve"] <= cap + 0.05
            or row["mean"] < 0
            or (
                (row["mean"] < row["threshold"] or not row["permit"])
                and row["proposed_valve"] > 0.05
            )
        ):
            raise ValueError(
                "The actual shadow valve exceeds its airflow or discharge-temperature limit."
            )
    end = rows[-1]
    window = [r["sample"] for r in rows if end["time"] - r["time"] <= 29.5]
    if not min(window) - 0.5 <= end["mean"] <= max(window) + 0.5:
        raise ValueError("The running mean differs from its independently observed airflow window.")
    # The two clocks need not have aligned sampling instants. For each elapsed
    # second, bracket the actual sample with the readings immediately on either
    # side. Average the bounds to distinguish a moving mean from a recent peak.
    from bisect import bisect_left

    times = [row["time"] for row in rows]
    for last, row in enumerate(rows):
        if row["time"] - times[0] < 30:
            continue
        lower = upper = 0.0
        for age in range(30):
            i = bisect_left(times, row["time"] - age, hi=last + 1)
            before = rows[max(0, i - 1)]["sample"]
            after = rows[i]["sample"]
            lower += min(before, after)
            upper += max(before, after)
        if not lower / 30 - 0.5 <= row["mean"] <= upper / 30 + 0.5:
            raise ValueError("The running mean differs from independent elapsed airflow samples.")
    return {
        "samples": len(rows),
        "elapsed": rows[-1]["time"] - rows[0]["time"],
        "distinct_clock_values": len(ticks),
        "flow_range": [min(window), max(window)],
        "mean": end["mean"],
        "shadow_valve": end["proposed_valve"],
        "actual_valve": end["actual_valve"],
        "threshold": end["threshold"],
        "limit": end["limit"],
    }


async def guard(native, session, identity, compiled):
    physical = await monitor.operating_state(native, session, identity, compiled)
    rows = []
    start = time.monotonic()
    for i in range(37):
        await asyncio.sleep(max(0, start + i - time.monotonic()))
        values = await sample(native, session, compiled)
        rows.append({**values, "time": time.monotonic() - start})
    return {**validate_samples(rows), "operating_state": physical}


async def review(native, options):
    from .native_inline_shadow import TRANSFER_HOLD

    raise ValueError(TRANSFER_HOLD)


def validate_review(plan):
    b = plan["body"]
    if (
        b.get("operation_profile") != PROFILE
        or seal(b) != plan["digest"]
        or b.get("observation_receipt_id") != plan["options"].observation_receipt_id
    ):
        raise ValueError("The retained valve activation review has changed.")


def fresh_compile(native, body, files):
    original, before = native.storage.load(body["capture_id"])
    if original["evidence_sha256"] != body["snapshot_sha256"]:
        raise ValueError("Original capture changed.")
    fresh_current(before, files)
    return prepare(native, body["identity"], files, body["observation_receipt_id"], body["target"])


def reconstruct(native, intent):
    if (
        intent.get("operation_profile") != PROFILE
        or intent.get("valve_connection_confirmed") is not True
    ):
        raise ValueError("Valve activation receipt lacks its confirmed profile.")
    _, files = native.storage.load(intent["backup_id"])
    out, report = prepare(
        native, intent["identity"], files, intent["observation_receipt_id"], intent["target"]
    )
    if (
        intent["compilation"] != report
        or sha(out) != intent["payload_sha256"]
        or report["native_sha256"] != intent["native_payload_sha256"]
    ):
        raise ValueError("The activation receipt differs from its verified source graph.")
    return out


def verify(native, intent, files):
    from .application_preservation import runtime_parameter_changes
    from .native_snapshot_restore import qualify_restore_counters

    actual = MoiIdentity(files[3])
    if MoiIdentity(reconstruct(native, intent)).data != actual.data:
        raise ValueError("Installed valve graph differs from review.")
    verified, counters, calculated = runtime_parameter_changes(
        actual, ParameterApplication(files[3], files[11], files[12])
    )
    qualify_restore_counters(files, counters)
    return {
        "native_graph_verified": True,
        "control_connections_changed": 2,
        "saved_parameters_verified": verified["matched_parameters"],
        "runtime_counter_changes": counters,
        "device_calculated_changes": calculated,
        "physical_response_verified": False,
    }


CONFIRMATION = "valve_connection_confirmed"


def receipt_fields(options):
    return {"observation_receipt_id": options.observation_receipt_id}


def scope():
    return {
        "scope": "Two existing control connections on the staged valve sequence",
        "devices": [],
        "allocation_required": False,
    }
