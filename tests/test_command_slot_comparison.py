"""Compare retained native readings, including a change hidden by an identical present value."""

import asyncio
import copy
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.command_slot_comparison import compare_command_slots
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_point_status import make_point_peer, options
from .test_schedule_inventory import verify_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [True, False])
async def test_compare_measured_slots_after_disconnect(tmp_path, routed):
    app = create_app(tmp_path)
    peer = await make_point_peer(routed=routed)
    original = peer.value

    def real(value):
        return b"\x44" + struct.pack(">f", value)

    slots = {2: real(-0.0), 15: real(12.5), 16: real(12.5)}
    obj = "analog-output,2"
    prefix = "/api/bacnet/point-status/"

    def native_value(identifier, prop, index):
        if str(identifier) == obj and prop == "priority-array" and index:
            return slots.get(index, b"\x00")
        return original(identifier, prop, index)

    peer.value = native_value
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            connected = await client.post(
                "/api/bacnet/connect",
                headers=headers,
                json={"local_address": f"127.0.0.1:{free_udp()}"},
            )
            connected.raise_for_status()

            async def inspect(operation):
                response = await client.post(
                    prefix + "read",
                    headers=headers,
                    json=options(
                        peer, operation_id=operation, object_ids=[obj], include_commandable=True
                    ),
                )
                response.raise_for_status()
                report = response.json()
                assert report["objects"][0]["properties"]["present-value"]["value"] == 12.5
                verify_hash(report)
                return report

            first = await inspect("before_priority_test")
            slots.update({2: real(0.0), 8: real(0.0)})
            del slots[15]
            second = await inspect("after_priority_test")
            third = await inspect("steady_priority_test")
            partial = await client.post(
                prefix + "read",
                headers=headers,
                json=options(peer, object_ids=[obj], operation_id="values_without_slots"),
            )
            partial.raise_for_status()
            closed = await client.post("/api/bacnet/disconnect", headers=headers, json={})
            closed.raise_for_status()
            request_count = len(peer.requests)

            summaries = (await client.get(prefix + "profile")).json()["reports"]
            assert all(s["command_slot_objects"] == [obj] for s in summaries[:3])
            assert summaries[-1]["command_slot_objects"] == []
            assert summaries[0]["connector_config"] == first["connector_config"]
            payload = {"baseline_id": first["id"], "current_id": second["id"], "object_id": obj}
            assert (
                await client.post(prefix + "compare-command-slots", json=payload)
            ).status_code == 403

            async def compare(**override):
                return await client.post(
                    prefix + "compare-command-slots", headers=headers, json=payload | override
                )

            compared = await compare()
            assert compared.status_code == 200, compared.text
            result = compared.json()
            assert result["target"] == first["target"]
            assert result["slots_compared"] == 16 and result["changes"] == [
                {"priority": 2, "change": "Changed", "before": "real -0.0", "after": "real 0.0"},
                {"priority": 8, "change": "Filled", "before": "Empty", "after": "real 0.0"},
                {"priority": 15, "change": "Cleared", "before": "real 12.5", "after": "Empty"},
            ]
            assert (await compare(baseline_id=second["id"], current_id=third["id"])).json()[
                "changes"
            ] == []
            for override in (
                {"baseline_id": second["id"]},
                {"baseline_id": third["id"]},
                {"object_id": "analog-output,99"},
                {"current_id": partial.json()["id"]},
                {"baseline_id": "f" * 32},
            ):
                assert (await compare(**override)).status_code == 422
            for mutate, message in (
                (lambda r: r["target"].update(device="device,999"), "must match"),
                (lambda r: r["connector_config"].update(instance=123), "must match"),
                (lambda r: r.update(identity_verified=False), "verify"),
                (
                    lambda r: r["objects"][0]["properties"]["object-name"].update(value="Renamed"),
                    "name changed",
                ),
                (
                    lambda r: r["objects"][0]["properties"]["priority-array"]["elements"][0].update(
                        array_index=2
                    ),
                    "slot 1",
                ),
                (
                    lambda r: r["objects"][0]["properties"]["priority-array"]["elements"].pop(),
                    "all 16",
                ),
            ):
                newer = copy.deepcopy(second)
                mutate(newer)
                with pytest.raises(ValueError, match=message):
                    compare_command_slots(first, newer, obj)
            assert len(peer.requests) == request_count and not peer.errors
            for report in (first, second, third):
                assert (await client.get(prefix + "reports/" + report["id"])).json() == report
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)
