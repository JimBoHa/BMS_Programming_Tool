"""Owned phase and actual deadline expiry distinguish native timeout outcomes."""

import asyncio
from types import SimpleNamespace

import pytest
from bms_tool.native_applications import NativeApplications


@pytest.fixture
def owner():
    # No transport/storage object exists: this wrapper may not issue field work.
    return SimpleNamespace(active=None, cancelled=set(), operation_timeout=0.5)


@pytest.mark.parametrize("detail", ["", "Missing authored reply", "cancel-cause"])
async def test_child_timeout_retains_its_owned_phase_and_original_detail(owner, detail):
    original = TimeoutError("" if detail == "cancel-cause" else detail)
    with pytest.raises(ValueError) as failure:
        async with NativeApplications.operation(owner, "child-timeout", "capture"):
            NativeApplications.phase(owner, "reading authored File 3")
            if detail == "cancel-cause":
                raise original from asyncio.CancelledError("Backup completion unconfirmed")
            raise original
    text = str(failure.value)
    assert "Native operation timed out. Last reported phase: reading authored File 3." in text
    assert "The overall operation time limit did not expire." in text
    assert "Consult retained transfer receipts before any further write." in text
    assert failure.value.__cause__ is original
    if detail == "cancel-cause":
        assert text.endswith("Backup completion unconfirmed")
    elif detail:
        assert text.endswith(detail)
    assert owner.active is None and owner.operation_timeout == 0.5


async def test_actual_owned_deadline_expiry_retains_phase_and_cancellation_cause(owner):
    owner.operation_timeout = 0.001
    with pytest.raises(ValueError) as failure:
        async with NativeApplications.operation(owner, "overall-timeout", "capture"):
            NativeApplications.phase(owner, "waiting for authored backup completion")
            await asyncio.Event().wait()
    text = str(failure.value)
    assert "Last reported phase: waiting for authored backup completion." in text
    assert "The overall operation time limit expired." in text
    assert "Consult retained transfer receipts before any further write." in text
    assert isinstance(failure.value.__cause__, TimeoutError)
    assert isinstance(failure.value.__cause__.__cause__, asyncio.CancelledError)
    assert owner.active is None and owner.operation_timeout == 0.001


async def test_successful_operation_keeps_ownership_until_normal_exit(owner):
    async with NativeApplications.operation(owner, "ordinary-operation", "readback"):
        NativeApplications.phase(owner, "verifying authored values")
        assert owner.active == {
            "operation_id": "ordinary-operation",
            "kind": "readback",
            "phase": "verifying authored values",
            "task": asyncio.current_task(),
        }
    assert owner.active is None and owner.operation_timeout == 0.5


async def test_explicit_cancellation_stays_cancellation_and_retires_only_its_owner(owner):
    entered = asyncio.Event()

    async def work():
        async with NativeApplications.operation(owner, "cancel-owned", "capture"):
            NativeApplications.phase(owner, "reading authored values")
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await entered.wait()
    assert owner.active["task"] is task
    task.cancel("Operator cancelled the authored operation")
    with pytest.raises(ValueError) as failure:
        await task
    text = str(failure.value)
    assert "Native operation cancelled" in text and "timed out" not in text
    assert text.endswith("Operator cancelled the authored operation")
    assert isinstance(failure.value.__cause__, asyncio.CancelledError)
    assert owner.active is None and owner.operation_timeout == 0.5


async def test_busy_or_previously_cancelled_ids_do_not_replace_the_active_operation(owner):
    owner.cancelled.add("cancelled-earlier")
    with pytest.raises(ValueError, match="busy or cancelled"):
        async with NativeApplications.operation(owner, "cancelled-earlier", "capture"):
            pytest.fail("A cancelled operation entered its body")
    assert owner.active is None
    async with NativeApplications.operation(owner, "active-operation", "capture"):
        original = owner.active
        with pytest.raises(ValueError, match="busy or cancelled"):
            async with NativeApplications.operation(owner, "second-operation", "capture"):
                pytest.fail("A busy operation entered its body")
        assert owner.active is original
    assert owner.active is None
