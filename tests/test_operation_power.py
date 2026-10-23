"""Owned requests, same-thread release and advisory operation lifecycle."""

import asyncio
import threading

import pytest
from bms_tool.operation_power import OperationPower, UnavailableProvider, WindowsProvider


class Provider:
    name = "observed-test-provider"

    def __init__(self, *, fail_open=False, fail_close=False, lost=False, gate=None):
        self.calls = []
        self.fail_open, self.fail_close, self.lost, self.gate = fail_open, fail_close, lost, gate

    def availability(self):
        return True

    def open(self, seconds):
        self.calls.append(("open", threading.get_ident(), seconds))
        if self.gate:
            self.gate.wait(3)
        if self.fail_open:
            raise OSError("denied")
        owner = self

        class Handle:
            def alive(self):
                return not owner.lost

            def close(self):
                owner.calls.append(("close", threading.get_ident(), seconds))
                if owner.fail_close:
                    raise OSError("clear failed")

        return Handle()


async def eventually(predicate):
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_no_startup_assertion_normal_release_is_idempotent_same_thread_and_daemon():
    provider = Provider()
    manager = OperationPower(provider)
    assert manager.status()["active"] == manager.status()["recent"] == [] and not provider.calls
    async with manager.operation("temco-native-apply") as lease:
        assert lease.snapshot()["state"] == "active" and lease.thread.daemon
        assert manager.status()["active"][0]["id"] == lease.row["id"]
    await manager._release(lease)
    assert [r[0] for r in provider.calls] == ["open", "close"]
    assert provider.calls[0][1] == provider.calls[1][1]
    assert lease.snapshot()["state"] == "released" and lease.snapshot()["cleanup_confirmed"]
    assert not manager.status()["active"]


async def test_body_exception_releases_without_replacing_primary_error():
    provider = Provider()
    manager = OperationPower(provider)
    with pytest.raises(ValueError, match="original"):
        async with manager.operation("temco-native-apply"):
            raise ValueError("original")
    assert [r[0] for r in provider.calls] == ["open", "close"]


@pytest.mark.parametrize(
    "provider", [UnavailableProvider(), Provider(fail_open=True), Provider(lost=True)]
)
async def test_failed_or_unavailable_acquisition_is_advisory_and_body_still_runs(provider):
    manager = OperationPower(provider)
    async with manager.operation("temco-native-apply") as lease:
        assert lease.snapshot()["state"] in ("failed", "unavailable")
        assert not lease.snapshot()["request_active"]
    assert not manager.status()["active"]


async def test_cleanup_failure_is_not_misreported_as_released_or_evicted():
    manager = OperationPower(Provider(fail_close=True))
    async with manager.operation("temco-native-apply") as lease:
        pass
    assert lease.snapshot()["state"] == "cleanup_failed"
    assert not lease.snapshot()["cleanup_confirmed"]
    assert manager.status()["active"][0]["id"] == lease.row["id"]
    assert (await manager.close(wait_seconds=0))["pending_active"]


async def test_close_stops_admission_but_operation_owns_lease_until_finally():
    provider = Provider()
    manager = OperationPower(provider)
    async with manager.operation("temco-native-apply") as lease:
        closed = await manager.close(wait_seconds=0)
        assert closed["pending_active"] and not closed["forced_release"]
        assert lease.snapshot()["request_active"] and len(provider.calls) == 1
        async with manager.operation("temco-native-apply") as refused:
            assert refused.snapshot()["state"] == "unavailable"
        assert len(provider.calls) == 1
    assert [r[0] for r in provider.calls] == ["open", "close"]


async def test_hard_ttl_releases_power_without_cancelling_operation_or_renewing_on_status():
    manager = OperationPower(Provider())
    async with manager.operation("temco-native-apply", seconds=1) as lease:
        for _ in range(3):
            assert manager.status()["active"]
        await eventually(lease.done.is_set)
        assert lease.snapshot()["state"] == "expired" and lease.snapshot()["cleanup_confirmed"]
        # The business body is still executing after power expiry.
        assert not asyncio.current_task().cancelling()


async def test_cancelled_before_acquisition_finishes_still_cleans_owned_request():
    gate = threading.Event()
    provider = Provider(gate=gate)
    manager = OperationPower(provider)
    entered = False

    async def work():
        nonlocal entered
        async with manager.operation("temco-native-apply"):
            entered = True

    task = asyncio.create_task(work())
    await eventually(lambda: bool(provider.calls))
    task.cancel()
    asyncio.get_running_loop().call_soon(task.cancel)
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not entered
    assert [r[0] for r in provider.calls] == ["open", "close"]
    assert not manager.status()["active"]


async def test_concurrency_limit_independent_release_and_bounded_history():
    manager = OperationPower(Provider())
    contexts = [manager.operation("temco-native-apply") for _ in range(8)]
    leases = [await c.__aenter__() for c in contexts]
    try:
        async with manager.operation("temco-native-apply") as excess:
            assert excess.snapshot()["state"] == "unavailable"
        await contexts[0].__aexit__(None, None, None)
        assert leases[0].done.is_set() and all(not x.done.is_set() for x in leases[1:])
    finally:
        for c in contexts[1:]:
            await c.__aexit__(None, None, None)
    for _ in range(35):
        async with manager.operation("temco-native-apply"):
            pass
    assert len(manager.status()["recent"]) <= 32 and not manager.status()["active"]


@pytest.mark.parametrize("seconds", [0, 1801, True, 1.5])
async def test_invalid_ttl_refused_before_provider_request(seconds):
    provider = Provider()
    with pytest.raises(ValueError):
        async with OperationPower(provider).operation("temco-native-apply", seconds):
            pass
    assert not provider.calls


@pytest.mark.parametrize("seconds", [-1, 4, float("inf"), True])
async def test_close_observation_is_bounded(seconds):
    with pytest.raises(ValueError):
        await OperationPower(Provider()).close(seconds)


async def test_windows_actual_api_wrapper_uses_exact_flags_on_same_owning_thread(monkeypatch):
    import bms_tool.operation_power as power

    calls = []

    class Setter:
        def __call__(self, flags):
            calls.append((flags, threading.get_ident()))
            return 0x80000000

    class Kernel:
        SetThreadExecutionState = Setter()

    monkeypatch.setattr(power.ctypes, "WinDLL", lambda *a, **k: Kernel(), raising=False)
    provider = WindowsProvider()
    monkeypatch.setattr(provider, "availability", lambda: True)
    async with OperationPower(provider).operation("temco-native-apply"):
        assert len(calls) == 1
    assert [r[0] for r in calls] == [0x80000001, 0x80000000]
    assert calls[0][1] == calls[1][1] != threading.get_ident()


@pytest.mark.parametrize("fail_on", ["acquire", "clear"])
async def test_windows_failure_is_advisory_and_clear_failure_remains_visible(monkeypatch, fail_on):
    import bms_tool.operation_power as power

    class Setter:
        def __call__(self, flags):
            return 0 if (flags == 0x80000001) == (fail_on == "acquire") else 0x80000000

    class Kernel:
        SetThreadExecutionState = Setter()

    monkeypatch.setattr(power.ctypes, "WinDLL", lambda *a, **k: Kernel(), raising=False)
    provider = WindowsProvider()
    monkeypatch.setattr(provider, "availability", lambda: True)
    manager = OperationPower(provider)
    async with manager.operation("temco-native-apply") as lease:
        assert lease.snapshot()["state"] == ("failed" if fail_on == "acquire" else "active")
    assert lease.snapshot()["state"] == ("failed" if fail_on == "acquire" else "cleanup_failed")


async def test_lost_provider_request_is_reported_failed_and_business_body_is_not_cancelled():
    provider = Provider()
    manager = OperationPower(provider)
    async with manager.operation("temco-native-apply") as lease:
        provider.lost = True
        await eventually(lease.done.is_set)
        assert lease.snapshot()["state"] == "failed"
        assert not asyncio.current_task().cancelling()


async def test_slow_admission_times_out_advisory_and_late_resource_cleans_without_body_delay():
    gate = threading.Event()
    provider = Provider(gate=gate)
    manager = OperationPower(provider)
    async with manager.operation("temco-native-apply") as lease:
        assert "admission timed out" in lease.snapshot()["error"]
        gate.set()
    assert [r[0] for r in provider.calls] == ["open", "close"]
    assert not manager.status()["active"]


async def test_unknown_operation_kind_does_not_create_a_request():
    provider = Provider()
    with pytest.raises(ValueError):
        async with OperationPower(provider).operation("idle-tab"):
            pass
    assert not provider.calls
