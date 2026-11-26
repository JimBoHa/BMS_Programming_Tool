"""Identify an acknowledged observation image on a controller reporting no application."""

from bacpypes3.apdu import AtomicReadFileACK, AtomicReadFileRequest
from bacpypes3.basetypes import (
    AtomicReadFileRequestAccessMethodChoice,
    AtomicReadFileRequestAccessMethodChoiceStreamAccess,
)

from .application_files import MAX_FILE_BYTES
from .moi_identity import sha
from .native_snapshot_restore import require_restore_source


async def inspect_failed_start(native, session, intent, identity, candidate):
    """Read the existing archive in place. Never enter a backup or restore state."""
    empty = {
        **intent["identity"],
        "device": "device,1",
        "object-name": "No Application",
        "application-software-version": "",
    }
    if identity != empty:
        return None
    receipt = native.storage.receipt(intent["id"])
    result = receipt.get("result") or {}
    if (
        not receipt["pending"]
        or result.get("status") != "unknown"
        or result.get("protocol_accepted") is not True
    ):
        return None
    acknowledged = {event["stage"]: event["detail"] for event in receipt["events"]}
    if (
        acknowledged.get("application-file-acknowledged")
        != {"file": 3, "bytes": len(candidate), "sha256": intent["payload_sha256"]}
        or "ack-end-restore" not in acknowledged
        or sha(candidate) != intent["payload_sha256"]
    ):
        return None
    at = 0
    proof = {
        "profile": "native-application-start-readback/1",
        "read_only": True,
        "status": "unconfirmed",
        "compared_bytes": 0,
    }
    try:
        dev = identity["device"]
        mode = int(await native.path._read(session, dev, "system-status"))
        size = int(await native.path._read(session, "file,3", "file-size"))
        kind = str(await native.path._read(session, "file,3", "file-type")).lower()
        if mode != 2 or kind != ".moi" or not 0 < len(candidate) <= size <= MAX_FILE_BYTES:
            raise ValueError("Current controller state or application archive bounds differ.")
        stamp = await native.path._read(session, dev, "last-restore-time")
        restored_at = getattr(stamp, "dateTime", None)
        if restored_at is None or restored_at.is_special:
            raise ValueError("Controller did not provide a specific last restore date and time.")
        restart = str(stamp)
        # A failed start can expose the full archive storage area, including unused
        # trailing bytes. Compare every byte of the acknowledged file at its offset.
        for _ in range(8192):
            if at == len(candidate):
                break
            count = min(384, len(candidate) - at)
            req = AtomicReadFileRequest(
                fileIdentifier=(10, 3),
                accessMethod=AtomicReadFileRequestAccessMethodChoice(
                    streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                        fileStartPosition=at, requestedOctetCount=count
                    )
                ),
            )
            ack = await native.files.exchange(session, req, AtomicReadFileACK)
            part = ack.accessMethod.streamAccess
            if part is None or int(part.fileStartPosition) != at:
                raise ValueError("The archive reply did not start at the requested offset.")
            data = bytes(part.fileData)
            end = at + len(data)
            if not 0 < len(data) <= count or data != candidate[at:end]:
                raise ValueError(
                    "The archive does not match the acknowledged image at the expected offset."
                )
            if ack.endOfFile and end != len(candidate):
                raise ValueError("The archive ended before the complete acknowledged image.")
            at = end
            proof["compared_bytes"] = at
        if at != len(candidate):
            raise ValueError("The archive exceeded its readback request budget.")
        if (
            await native.instances._identity(session, "device,4194303") != identity
            or int(await native.path._read(session, dev, "system-status")) != mode
            or str(await native.path._read(session, dev, "last-restore-time")) != restart
        ):
            raise ValueError(
                "Controller identity or startup state changed during the archive read."
            )
        before, _ = native.storage.load(intent["backup_id"])
        if (
            before["identity"] != intent["identity"]
            or before["target"] != intent["target"]
            or not before.get("source_identity_matches")
        ):
            raise ValueError("The retained original belongs to a different source.")
        _, original = native.restore_source(
            {
                "restore_capture_id": before["id"],
                "restore_snapshot_sha256": before["evidence_sha256"],
            }
        )
        require_restore_source(original)
        proof.update(
            status="image_present_application_not_running",
            image_sha256=intent["payload_sha256"],
            original_capture_id=before["id"],
            original_snapshot_sha256=before["evidence_sha256"],
            original_export_sha256=original["compilation"]["compiled_sha256"],
            last_restore_time=restart,
        )
    except (ValueError, TimeoutError, OSError) as err:
        proof["error"] = (str(err) or type(err).__name__)[:256]
    return proof
