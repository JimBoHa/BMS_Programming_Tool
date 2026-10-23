"""Browser-only manager fixtures; no OS power request or controller operation."""

from contextlib import asynccontextmanager

from bms_tool.app import create_app
from bms_tool.operation_power import OperationPower


class SimulatedProvider:
    name = "simulated-browser-idle-provider"

    def __init__(self):
        self.available = True
        self.fail_open = False
        self.fail_close = False

    def availability(self):
        return self.available

    def open(self, seconds):
        if self.fail_open:
            raise OSError("Simulated admission failure; no OS request made.")
        fail_close = self.fail_close

        class Handle:
            def alive(self):
                return True

            def close(self):
                if fail_close:
                    raise OSError("Simulated cleanup failure; no OS resource exists.")

        return Handle()


provider = SimulatedProvider()
power = OperationPower(provider)
app = create_app(operation_power=power)
original_lifespan = app.router.lifespan_context
live = []


async def clear():
    for lease in live:
        await power._release(lease)
    live.clear()
    with power.lock:
        power.leases.clear()
        power.accepting = True
    provider.available, provider.fail_open, provider.fail_close = True, False, False


@asynccontextmanager
async def lifespan(app):
    async with original_lifespan(app):
        try:
            yield
        finally:
            await clear()


app.router.lifespan_context = lifespan


@app.post("/__test_power/reset")
async def reset():
    await clear()
    async with power.operation("temco-native-apply", seconds=900):
        pass
    provider.fail_open = True
    async with power.operation("temco-native-apply", seconds=900):
        pass
    provider.fail_open = False
    provider.available = False
    async with power.operation("temco-native-apply", seconds=900):
        pass
    provider.available = True
    provider.fail_close = True
    async with power.operation("temco-native-apply", seconds=900):
        pass
    provider.fail_close = False
    lease = power._start("temco-native-apply", 1800)
    import asyncio

    assert await asyncio.to_thread(lease.ready.wait, 2)
    live.append(lease)
    return {"active_id": lease.row["id"], "simulated_provider": True, "OS_requests": 0}


@app.post("/__test_power/finish")
async def finish():
    for lease in live:
        await power._release(lease)
    live.clear()
    provider.available = False
    await power.close(wait_seconds=0)
    return {"simulated_provider": True, "OS_requests": 0}


# The production root StaticFiles mount handles every method, so these private
# fixture controls must precede it. Preserve all original application route order.
controls = [
    route for route in app.router.routes if getattr(route, "path", "").startswith("/__test_power/")
]
app.router.routes[:] = controls + [route for route in app.router.routes if route not in controls]
