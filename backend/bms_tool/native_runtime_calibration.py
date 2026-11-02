"""Separately observe calculated flow offsets; a stored file is not a live read."""

import math

from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.errors import InvalidTag
from bacpypes3.primitivedata import ObjectIdentifier, Real, TagClass

from .application_store import utc
from .moi_identity import MoiIdentity

PROFILE = "native-flow-calibration-readback/1"


def candidates(application):
    app = MoiIdentity(application)
    result, identifiers = [], set()
    for record in app.records:
        if record["class_id"] != 570:
            continue
        declared = app.reader.scalar(record, 75)
        native_id = int.from_bytes(app.data[record["offset"] + 6 : record["offset"] + 10], "big")
        obj = str(
            ObjectIdentifier(declared if isinstance(declared, str) else (570, native_id & 4194303))
        )
        if obj in identifiers:
            raise ValueError("Duplicate flow identities prevent runtime calibration readback.")
        identifiers.add(obj)
        prop = record["properties"].get(3506)
        previous = None
        if prop is not None:
            raw = app.data[prop["value_start_offset"] : prop["value_end_offset"]]
            previous = app.reader.scalar(record, 3506)
            if (
                len(raw) != 6
                or raw[0] != 0x44
                or raw[-1] != 0x2F
                or not isinstance(previous, float)
                or not math.isfinite(previous)
            ):
                raise ValueError("Stored flow calibration has an unsupported non-Real value.")
        result.append(
            {
                "object": obj,
                "record_ref": app.reader.scalar(record, 32527),
                "native_class": 570,
                "property": 3506,
                "property_name": "Autocalibrate Offset",
                "application_value": previous,
            }
        )
    return result


async def read_runtime_calibration(application, exchange, session, *, limit=32):
    fields = candidates(application)
    rows = []
    for selected in fields[:limit]:
        request = ReadPropertyRequest(objectIdentifier=selected["object"], propertyIdentifier=3506)
        try:
            reply = await exchange(session, request, ReadPropertyACK)
        except (ValueError, TimeoutError, OSError) as exc:
            rows.append(
                {
                    **selected,
                    "status": "unavailable",
                    "error": (str(exc) or "Live calibration read timed out.")[:256],
                }
            )
            continue
        if (
            reply.objectIdentifier != request.objectIdentifier
            or reply.propertyIdentifier != request.propertyIdentifier
            or reply.propertyArrayIndex is not None
        ):
            raise ValueError("Runtime calibration reply does not match the selected property.")
        try:
            tags = list(reply.propertyValue.tagList)
            if (
                len(tags) >= 2
                and tags[0].tag_class == TagClass.opening
                and tags[0].tag_number == 3
                and tags[-1].tag_class == TagClass.closing
                and tags[-1].tag_number == 3
            ):
                tags = tags[1:-1]
            if (
                len(tags) != 1
                or tags[0].tag_class != TagClass.application
                or tags[0].tag_number != 4
                or len(tags[0].tag_data) != 4
            ):
                raise ValueError("Live flow calibration is not one native Real.")
            value = float(reply.propertyValue.cast_out(Real))
        except (InvalidTag, TypeError, AttributeError) as exc:
            raise ValueError("Malformed live flow calibration encoding.") from exc
        if not math.isfinite(value):
            raise ValueError("Live flow calibration is nonfinite.")
        rows.append(
            {
                **selected,
                "status": "ok",
                "live_value": value,
                "changed_from_application": selected["application_value"] is not None
                and value != selected["application_value"],
                "observed_at": utc(),
                "wire": session.get("last_application_wire"),
            }
        )
    return {
        "profile": PROFILE,
        "read_only": True,
        "field_writes": False,
        "scope": "Current Flow Primitive calculated calibration outputs, separately from stored-image/settings verification. Values may continue to change during normal control.",
        "complete": len(fields) <= limit and all(r["status"] == "ok" for r in rows),
        "not_applicable": not fields,
        "total": len(fields),
        "limit": limit,
        "fields": rows,
        "changed": [r for r in rows if r.get("changed_from_application")],
    }
