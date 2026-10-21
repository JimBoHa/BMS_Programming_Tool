"""Real TTY proof that cancelled requests cannot escape a waiting token queue."""

import asyncio

import pytest
from bacpypes3.apdu import ReadPropertyRequest
from bacpypes3.pdu import LocalStation
from bms_tool.bacnet_exchange import confirmed_exchange
from bms_tool.mstp import Frame, MstpMaster
from bms_tool.mstp_bacnet import create_mstp_application

from tests.test_mstp_bacnet import FixedWirePeer
from tests.test_mstp_connection import serial_path as serial_path


@pytest.mark.parametrize("exit_kind", ["timeout", "cancel"])
async def test_actual_cancel_before_first_token_retires_only_owned_request_and_restores_user_data(
    serial_path, exit_kind
):
    fd, path = serial_path
    peer = FixedWirePeer(fd)
    app = await create_mstp_application(path, 0, max_master=1)
    previous = {"caller": "unchanged"}
    request = ReadPropertyRequest(
        objectIdentifier="analog-input,1",
        propertyIdentifier="present-value",
        destination=LocalStation(1),
    )
    request.pduUserData = previous
    task = asyncio.create_task(confirmed_exchange(app, request))
    try:
        for _ in range(50):
            frames = list(app.mstp_link.link.master.tx_queue)
            if frames:
                break
            await asyncio.sleep(0.002)
        assert len(frames) == 1 and frames[0].owner is not None
        assert frames[0].owner is request.pduUserData
        assert request.pduUserData.previous is previous
        if exit_kind == "timeout":
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.03)
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await asyncio.sleep(0)
        assert request.pduUserData is previous
        assert app.mstp_link.status()["queued_frames"] == 0
        assert app.mstp_link.status()["statistics"]["retired_application_frames"] == 1
        assert not app.asap.clientTransactions and not app._requests
        peer.thread.start()
        # Let the actual serial master obtain/pass a token after cancellation.
        await asyncio.sleep(0.7)
        assert peer.requests == []
        # Reuse the retired invoke ID: no stale queue frame can be mistaken for it.
        app.next_invoke_id = 0
        assert (
            float(
                await asyncio.wait_for(app.read_property("1", "analog-input,1", "present-value"), 2)
            )
            == 12.5
        )
        assert peer.requests == ["read-property"]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        app.close()
        if peer.thread.ident is not None:
            peer.close()


def test_retirement_keeps_unrelated_requests_unowned_data_and_token_frames():
    master = MstpMaster(0, max_master=1, now=0)
    owner, other = object(), object()
    npdu = bytes.fromhex("01040005010c0c000000011955")
    master.send_npdu(1, npdu, expecting_reply=True, owner=owner)
    master.send_npdu(1, npdu, expecting_reply=True, owner=other)
    master.send_npdu(1, npdu, expecting_reply=True)
    token = Frame(0, 1, 0)
    master.pending_tx = (token, "pass-token")
    assert master.retire_owner(owner) == 1
    assert [frame.owner for frame in master.tx_queue] == [other, None]
    assert master.pending_tx == (token, "pass-token")
    master.pending_tx = (Frame(5, 1, 0, npdu, owner=other), "wait-for-reply")
    assert master.retire_owner(other) == 2
    assert master.pending_tx is None and len(master.tx_queue) == 1
    with pytest.raises(ValueError, match="explicit owner"):
        master.retire_owner(None)
