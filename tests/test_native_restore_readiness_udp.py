"""Exercise real post-commit UDP silence without mocking the readiness observer."""

import asyncio
import time
import types

import pytest

from .test_native_applications import apply_request, review
from .test_native_applications import native_link as native_link  # noqa: F401


@pytest.mark.parametrize("renaming", [False, True], ids=["instance", "name"])
async def test_actual_property_silence_waits_without_repeating_native_restore(
    native_link, monkeypatch, renaming
):
    peer, _, _, service, target = native_link
    # Exercise production readiness bounds while retaining every original short
    # request deadline in the authored peer fixture. A missing readiness feature
    # must fail on behavior, rather than on the new constants' existence.
    monkeypatch.setattr(
        "bms_tool.native_applications.RESTORE_READINESS_SECONDS", 60.0, raising=False
    )
    monkeypatch.setattr(
        "bms_tool.native_applications.RESTORE_READINESS_INTERVAL", 2.0, raising=False
    )
    read, reinitialize = peer.do_ReadPropertyRequest, peer.do_ReinitializeDeviceRequest
    dropped, boot_until = [], 0.0

    async def reboot(self, request):
        nonlocal boot_until
        if str(request.reinitializedStateOfDevice) == "end-restore":
            # Longer than the former fixed delay plus all three short identity
            # fallback deadlines. The next production readiness poll can succeed.
            boot_until = time.monotonic() + 1.6
        return await reinitialize(request)

    async def silent(self, request):
        if time.monotonic() < boot_until:
            dropped.append((str(request.objectIdentifier), str(request.propertyIdentifier)))
            return  # A real received UDP request deliberately gets no response.
        return await read(request)

    peer.do_ReinitializeDeviceRequest = types.MethodType(reboot, peer)
    peer.do_ReadPropertyRequest = types.MethodType(silent, peer)
    if renaming:
        captured = await service.capture(**target, operation_id="real-startup-capture")
        plan = await service.preview(
            **target,
            operation_id="real-startup-preview",
            capture_id=captured["id"],
            new_instance=5136,
            new_name="After actual UDP silence",
        )
    else:
        _, plan = await review(native_link)
    result = await asyncio.wait_for(
        service.apply(**{**apply_request(plan), "name_change_confirmed": renaming}),
        timeout=10.0,
    )
    assert result["result"]["status"] == "verified", result
    readiness = result["result"]["restore_readiness"]
    assert readiness["ready"] and readiness["read_only"] and len(readiness["attempts"]) >= 2
    assert dropped and readiness["attempts"][0]["identity_status"] in ("unknown", "unconfirmed")
    assert readiness["attempts"][-1]["identity_status"] == "verified_new"
    assert peer.events.count(("state", "start-restore")) == 1
    assert peer.events.count(("state", "end-restore")) == 1
    offsets = [event[2] for event in peer.events if event[0] == "write"]
    assert len(set(offsets)) == len(offsets)
    assert len([e for e in result["events"] if e["stage"] == "restore-readiness-read"]) == len(
        readiness["attempts"]
    )
