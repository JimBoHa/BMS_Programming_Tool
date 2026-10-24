"""Guarded reviewed administration, history and restart against raw UDP only."""

import httpx
from bms_tool.app import create_app

from .test_bbmd_admin import admin_wire as admin_wire
from .test_bbmd_admin import body
from .test_bbmd_tables import endpoint
from .test_connections import free_udp
from .test_foreign_bacnet import wait_until


async def test_corrupt_optional_admin_journal_keeps_session_and_readonly_tools_available(tmp_path):
    directory = tmp_path / "corrupt-optional-admin"
    journal = directory / "bbmd-administration"
    journal.mkdir(parents=True)
    (journal / "receipts.sqlite3").write_bytes(b"authored invalid SQLite fixture")
    app = create_app(directory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/session")).status_code == 200
            status = (await client.get("/api/bacnet/bbmd-admin/status")).json()
            assert status["available"] is False and "unavailable" in status["reason"]
            assert (await client.get("/api/bacnet/bbmd-tables/status")).status_code == 200
            assert (await client.get("/api/bacnet/bbmd-admin/history")).status_code == 422
            assert not app.state.bacnet.status()["connected"]


async def test_api_review_apply_hash_one_use_guarded_history_export_and_restore_proposal(
    admin_wire, tmp_path
):
    peer, _, _, _, _ = admin_wire
    app = create_app(tmp_path / "http")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            assert (await client.get("/api/bacnet/bbmd-admin/history")).json() == []
            assert not peer.frames
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            proposal = {
                "endpoint": endpoint(peer.address),
                "operation": "write-bdt",
                "rows": [],
                "timeout_seconds": 0.1,
            }
            assert (
                await client.post("/api/bacnet/bbmd-admin/preview", json=proposal)
            ).status_code == 403
            assert (
                await client.post("/api/bacnet/bbmd-admin/preview", json=proposal, headers=headers)
            ).status_code == 422
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            preview = (
                await client.post("/api/bacnet/bbmd-admin/preview", json=proposal, headers=headers)
            ).json()
            assert preview["apply_available"] and not peer.writes()
            action = body(preview)
            assert (
                await client.post("/api/bacnet/bbmd-admin/apply", json=action)
            ).status_code == 403
            assert (
                await client.post(
                    "/api/bacnet/bbmd-admin/apply",
                    json=action | {"acknowledge_limits": False},
                    headers=headers,
                )
            ).status_code == 422
            response = await client.post(
                "/api/bacnet/bbmd-admin/apply", json=action, headers=headers
            )
            assert response.status_code == 200, response.text
            await wait_until(lambda: app.state.bbmd_admin.tasks[preview["id"]].done())
            exported = (await client.get(f"/api/bacnet/bbmd-admin/receipts/{preview['id']}")).json()
            assert (
                exported["outcome"] == "desired-state-observed"
                and exported["write_outcome"] == "unknown"
            )
            assert "apply_token" not in exported and not exported["apply_available"]
            history = (await client.get("/api/bacnet/bbmd-admin/history")).json()
            assert history[0]["id"] == preview["id"]
            assert (
                await client.post("/api/bacnet/bbmd-admin/apply", json=action, headers=headers)
            ).status_code == 422
            restored = await client.post(
                "/api/bacnet/bbmd-admin/restore-preview",
                json={"id": preview["id"], "timeout_seconds": 0.1},
                headers=headers,
            )
            assert restored.status_code == 200 and restored.json()["restored_from"] == preview["id"]
            assert len(peer.writes()) == 1  # restoring is another preview, never automatic


async def test_api_shutdown_post_dispatch_unknown_and_restart_has_no_action_or_token(
    admin_wire, tmp_path
):
    peer, _, _, _, _ = admin_wire
    directory = tmp_path / "shutdown"
    app = create_app(directory)
    peer.drop_result = True
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            preview = (
                await client.post(
                    "/api/bacnet/bbmd-admin/preview",
                    json={
                        "endpoint": endpoint(peer.address),
                        "operation": "write-bdt",
                        "rows": [],
                        "timeout_seconds": 3.0,
                    },
                    headers=headers,
                )
            ).json()
            await client.post("/api/bacnet/bbmd-admin/apply", json=body(preview), headers=headers)
            await wait_until(lambda: bool(peer.writes()))
    assert app.state.bbmd_admin.detail(preview["id"])["outcome"] == "unknown"
    assert not app.state.bacnet.lock.locked() and not app.state.bacnet.status()["connected"]
    count = len(peer.frames)
    reopened = create_app(directory)
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened), base_url="http://testserver"
        ) as client:
            saved = (await client.get(f"/api/bacnet/bbmd-admin/receipts/{preview['id']}")).json()
            assert saved["outcome"] == "unknown" and not saved["apply_available"]
            assert (
                not saved["active_in_this_process"]
                and not reopened.state.bacnet.status()["connected"]
            )
            assert len(peer.frames) == count and reopened.state.bbmd_admin.tasks == {}


async def test_api_storage_failure_consumes_review_without_dispatch_and_returns_explicit_error(
    admin_wire, tmp_path, monkeypatch
):
    peer, _, _, _, _ = admin_wire
    app = create_app(tmp_path / "failed-admission")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{free_udp()}"},
                headers=headers,
            )
            preview = (
                await client.post(
                    "/api/bacnet/bbmd-admin/preview",
                    json={"endpoint": endpoint(peer.address), "operation": "write-bdt", "rows": []},
                    headers=headers,
                )
            ).json()
            original = app.state.bbmd_admin.journal.save

            def broken(row):
                if row["state"] == "apply-queued":
                    raise OSError("authored admission disk failure")
                original(row)

            monkeypatch.setattr(app.state.bbmd_admin.journal, "save", broken)
            response = await client.post(
                "/api/bacnet/bbmd-admin/apply", json=body(preview), headers=headers
            )
            assert response.status_code == 422 and "storage failed" in response.text
            assert not peer.writes() and app.state.bbmd_admin.tasks == {}
            repeated = await client.post(
                "/api/bacnet/bbmd-admin/apply", json=body(preview), headers=headers
            )
            assert repeated.status_code == 422 and "used" in repeated.text
