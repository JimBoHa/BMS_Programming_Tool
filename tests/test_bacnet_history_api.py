"""Actual HTTP lifecycle and durable history capture using a UDP Trend Log device."""

import os

import httpx
from bms_tool.app import create_app

from tests.test_bacnet_history import link as link
from tests.test_bacnet_history import port


async def test_http_history_read_explicit_save_and_restart_preserve_device_source_timestamps(
    link, tmp_path
):
    server, _, _, target = link
    state = tmp_path / "http-state"
    app = create_app(state)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            session = (await client.get("/api/session")).json()
            headers = {"X-Studio-Token": session["token"]}
            status = (await client.get("/api/bacnet/history/status")).json()
            assert not status["connected"] and status["read_only"] and not status["auto_poll"]
            assert not server.requests
            body = {**target, "mode": "sequence", "reference": 100, "count": 3, "page_size": 2}
            assert (
                await client.post("/api/bacnet/history/read", json=body, headers=headers)
            ).status_code == 422
            assert not server.requests
            opened = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{port()}"},
                headers=headers,
            )
            assert opened.status_code == 200, opened.text
            response = await client.post("/api/bacnet/history/read", json=body, headers=headers)
            assert response.status_code == 200, response.text
            report = response.json()
            assert report["source_kind"] == "device-history" and len(report["records"]) == 3
            assert report["records"][0]["source_clock"] == "2026-01-05T20:00:00.000000+00:00"
            assert report["records"][0]["recorded_at"] != report["records"][0]["source_clock"]
            assert (await client.get("/api/bacnet/history/captures")).json() == []
            saved = await client.post(
                "/api/bacnet/history/save", json={"id": report["id"]}, headers=headers
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["records"] == 3
            assert (
                await client.get("/api/bacnet/history/captures/" + report["id"])
            ).json() == report
            assert (await client.get("/api/observations/trends")).json() == []
            assert (await client.get("/api/field-trends/samples")).json() == []
            assert not (await client.get("/api/bacnet/status")).json()["commands"]
    count = len(server.requests)
    restarted = create_app(state)
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://testserver"
        ) as client:
            assert (
                await client.get("/api/bacnet/history/captures/" + report["id"])
            ).json() == report
            assert len((await client.get("/api/bacnet/history/captures")).json()) == 1
            assert not (await client.get("/api/session")).json()["field_network_open"]
            assert len(server.requests) == count


async def test_http_history_security_strict_bounds_and_no_automatic_network_requests(
    link, tmp_path
):
    server, _, _, target = link
    app = create_app(tmp_path / "http-security")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (await client.post("/api/bacnet/history/read", json=target)).status_code == 403
            for other in ({"Host": "foreign.example"}, {"Origin": "https://foreign.example"}):
                response = await client.post(
                    "/api/bacnet/history/read", json=target, headers={**headers, **other}
                )
                assert response.status_code == 403
            for extra in (
                {"count": True},
                {"count": "2"},
                {"page_size": 101},
                {"fold": True},
                {"device_timezone": "Unknown/Zone"},
                {"mode": "time", "reference_time": "2026-01-01T00:00:00"},
                {"object_id": "analog-input,1"},
                {"source_clock": "invented"},
            ):
                response = await client.post(
                    "/api/bacnet/history/read", json={**target, **extra}, headers=headers
                )
                assert response.status_code == 422, (extra, response.text)
            assert (
                await client.post(
                    "/api/bacnet/history/save", json={"id": "a" * 32, "report": {}}, headers=headers
                )
            ).status_code == 422
            assert (
                await client.post(
                    "/api/bacnet/history/save", json={"id": "a" * 32}, headers=headers
                )
            ).status_code == 422
            assert (await client.get("/api/bacnet/history/captures/" + "a" * 32)).status_code == 422
            assert (
                not server.requests
                and not (await client.get("/api/session")).json()["field_network_open"]
            )


async def test_http_corrupt_and_nonregular_capture_files_are_rejected_without_network_start(
    tmp_path,
):
    app = create_app(tmp_path)
    identifier = "a" * 32
    path = app.state.bacnet_history.directory / ("capture-" + identifier + ".json")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            os.mkfifo(path)
            response = await client.get("/api/bacnet/history/captures/" + identifier)
            assert response.status_code == 422 and "regular file" in response.text
            path.unlink()
            path.write_text("[" * 10000 + "0" + "]" * 10000)
            response = await client.get("/api/bacnet/history/captures/" + identifier)
            assert response.status_code == 422 and "nesting profile" in response.text
            assert not (await client.get("/api/session")).json()["field_network_open"]
