"""Inspect a network sensor's same-controller zone temperature input reference."""

import math

from bacpypes3.primitivedata import ObjectIdentifier, TagClass


def temperature_reference(tags, sensor):
    shape = [(tag.tag_class, tag.tag_number) for tag in tags]
    app, opening, closing = TagClass.application, TagClass.opening, TagClass.closing
    if shape != [
        (opening, 3),
        (app, 7),
        (opening, 4),
        (closing, 4),
        (app, 0),
        (app, 12),
        (app, 2),
        (app, 6),
        (app, 12),
        (closing, 3),
    ]:
        raise ValueError("Unsupported network sensor input reference encoding.")
    if (
        not 2 <= len(tags[1].tag_data) <= 1024
        or tags[4].tag_data
        or len(tags[5].tag_data) != 4
        or tags[6].tag_data != b"\x01"
        or len(tags[7].tag_data) != 3
        or len(tags[8].tag_data) != 4
    ):
        raise ValueError("Incomplete network sensor input reference fields.")
    item = str(tags[1].app_to_object())
    child, device = tags[5].app_to_object(), tags[8].app_to_object()
    _, sensor_instance = ObjectIdentifier(sensor)
    suffix = f".627_{sensor_instance}.0_{child[1]}"
    if (
        int(child[0]) != 0
        or int(device[0]) != 8
        or max(child[1], device[1]) > 4194302
        or not item.isprintable()
        or not item.endswith(suffix)
    ):
        raise ValueError("Network sensor item reference and typed input identifiers disagree.")
    return {"item_reference": item, "device": str(device), "object": str(child)}


async def read_temperature(workspace, session, budget, options, item):
    source = item["properties"]["941"]
    result = {"status": "unconfirmed", "sensor": item["object"]}
    ref = source.get("value")
    if source.get("datatype") != "NetworkSensorInputReference" or ref["device"] != options.device:
        return {**result, "reason": "No qualified temperature link to the selected controller."}
    obj = ref["object"]
    actual, identity = await workspace._read(session, budget, obj, "object-identifier")
    result.update(object=obj, identity=identity)
    if actual != ObjectIdentifier(obj):
        return {**result, "reason": "The linked input did not confirm its identity."}
    _, child_reference = await workspace._read(session, budget, obj, "32527")
    if (
        child_reference.get("status") != "ok"
        or child_reference.get("value") != ref["item_reference"]
    ):
        return {**result, "reason": "The input did not confirm the sensor's exact item reference."}
    fields = await workspace._fields(
        session,
        budget,
        options,
        obj,
        ["object-name", "present-value", "units", "reliability", "out-of-service", "status-flags"],
    )
    _, closing = await workspace._read(session, budget, item["object"], "941")
    if (
        closing.get("datatype") != "NetworkSensorInputReference"
        or closing.get("encoded_value", {}).get("sha256") != source["encoded_value"]["sha256"]
    ):
        return {**result, "reason": "The sensor link changed during the read."}
    value = fields["present-value"].get("value")
    units = fields["units"].get("value") or {}
    if (
        any(v.get("status") != "ok" for v in fields.values())
        or type(value) not in (int, float)
        or not math.isfinite(value)
        or not isinstance(units, dict)
        or units.get("value") not in (62, 63, 64)
    ):
        return {
            **result,
            "reason": "A linked input value, unit or quality property was unavailable.",
            "properties": fields,
        }
    reliability = fields["reliability"].get("value") or {}
    good = (
        item["properties"].get("913", {}).get("value") is False
        and isinstance(reliability, dict)
        and reliability.get("value") == 0
        and fields["out-of-service"].get("value") is False
        and fields["status-flags"].get("value") == [0, 0, 0, 0]
    )
    return {
        **result,
        "status": "observed",
        "quality": "good" if good else "flagged",
        "properties": fields,
    }
