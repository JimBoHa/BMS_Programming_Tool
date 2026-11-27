"""Corroborate a matching-image reinstall with the target's own restore marker."""

from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.basetypes import TimeStamp
from bacpypes3.errors import InvalidTag


def applies(identity):
    return (
        identity.get("vendor-identifier") == 5
        and identity.get("model-name") in {"MS-VMA1630-0", "FX-PCV1630-0"}
        and identity.get("firmware-revision") == "6.2.0.1054"
    )


async def read_marker(native, session, device):
    request = ReadPropertyRequest(objectIdentifier=device, propertyIdentifier="last-restore-time")
    ack = await native.files.exchange(session, request, ReadPropertyACK, optional=True)
    if ack is None:
        return {"state": "unsupported"}
    if (
        ack.objectIdentifier != request.objectIdentifier
        or ack.propertyIdentifier != request.propertyIdentifier
        or ack.propertyArrayIndex is not None
    ):
        raise ValueError(
            "The last-restore-time reply differs from the selected device or property."
        )
    try:
        stamp = ack.propertyValue.cast_out(TimeStamp)
        dt = stamp.dateTime
        if dt is not None:
            if dt.is_special:
                empty = tuple(dt.date) == tuple(dt.time) == (255, 255, 255, 255)
                return {"state": "unspecified" if empty else "undated"}
            return {"state": "dated", "value": dt.datetime.isoformat(timespec="milliseconds")}
    except (InvalidTag, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise ValueError("The selected device returned an invalid last-restore-time.") from exc
    # A time of day or sequence number alone can repeat after restart.
    return {"state": "undated"}


async def verify_marker(native, session, device, before):
    after = await read_marker(native, session, device)
    advanced = after["state"] == "dated" and (
        before["state"] == "unspecified"
        or (before["state"] == "dated" and after["value"] > before["value"])
    )
    return {"before": before, "after": after, "advanced": advanced}
