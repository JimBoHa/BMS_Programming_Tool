"""Authenticated offline library APIs with actual direct/routed source reads."""

import asyncio
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.native_schedule_library import DRAFT_PROFILE, digest, encoded
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_native_schedule_library import request
from .test_schedule_inventory import make_peer, options

PREFIX = "/api/bacnet/schedules/library"


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_exact_exports_draft_import_and_restart_have_no_field_queries(tmp_path, routed):
    application = create_app(tmp_path)
    peer = await make_peer(routed=routed)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            result = await client.post(
                "/api/bacnet/schedules/read", headers=headers, json=options(peer)
            )
            assert result.status_code == 200, result.text
            report = result.json()
            source = (
                await client.post(
                    "/api/bacnet/schedules/export", headers=headers, json={"id": report["id"]}
                )
            ).content
            count = len(peer.requests)
            assert (
                await client.post("/api/bacnet/disconnect", headers=headers, json={})
            ).status_code == 200
            assert not (await client.get("/api/session")).json()["field_network_open"]
            detail_response = await client.post(
                PREFIX + "/save", headers=headers, json={"id": report["id"]}
            )
            assert detail_response.status_code == 200, detail_response.text
            detail = detail_response.json()
            assert detail["id"] == hashlib.sha256(source).hexdigest()
            assert detail["objects"][0]["days"][0]["transitions"][0]["value_text"] == "-0.0"
            authoritative = await client.post(
                PREFIX + "/source-export", headers=headers, json={"id": detail["id"]}
            )
            assert authoritative.content == source
            archive = await client.post(
                PREFIX + "/export", headers=headers, json={"id": detail["id"]}
            )
            assert (
                archive.status_code == 200
                and "attachment;" in archive.headers["content-disposition"]
            )
            assert json.loads(archive.content)["source_json"].encode() == source
            reviewed = await client.post(
                PREFIX + "/drafts/review", headers=headers, json=request(detail)
            )
            assert reviewed.status_code == 200, reviewed.text
            review = reviewed.json()
            export = await client.post(
                PREFIX + "/drafts/export", headers=headers, json={"id": review["id"]}
            )
            assert export.content == encoded(review)
            # Browser serialization would destroy integral floats/sign, so this API
            # download assertion uses original response bytes independently.
            assert b'"value":-0.0' in export.content
            assert len(peer.requests) == count
        restarted = create_app(tmp_path)
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            profile = (await client.get(PREFIX + "/profile")).json()
            assert (
                len(profile["captures"]) == 1
                and not profile["auto_query"]
                and not profile["field_writes"]
            )
            assert (await client.get(PREFIX + "/captures/" + detail["id"])).json()[
                "report"
            ] == report
            copied = await client.post(
                PREFIX + "/import",
                headers=headers,
                files={"file": ("capture.json", archive.content, "application/json")},
            )
            assert copied.status_code == 200
            imported = await client.post(
                PREFIX + "/drafts/import",
                headers=headers,
                files={"file": ("draft.json", export.content, "application/json")},
            )
            assert imported.status_code == 200 and imported.json() == review
            assert (
                await client.post(
                    PREFIX + "/drafts/export", headers=headers, json={"id": review["id"]}
                )
            ).content == export.content
            assert not (await client.get("/api/session")).json()["field_network_open"]
            assert len(peer.requests) == count
            assert not peer.errors
    finally:
        await application.state.schedule_inventory.close()
        application.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


def test_offline_apis_are_token_guarded_and_reject_malformed_without_storage(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        for suffix, body in (
            ("/save", {"id": "a" * 32}),
            ("/export", {"id": "a" * 64}),
            ("/source-export", {"id": "a" * 64}),
            ("/drafts/review", {}),
            ("/drafts/export", {"id": "a" * 64}),
        ):
            assert client.post(PREFIX + suffix, json=body).status_code == 403
        for suffix in ("/import", "/drafts/import"):
            assert (
                client.post(PREFIX + suffix, files={"file": ("x.json", b"{}")}).status_code == 403
            )
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for suffix in ("/import", "/drafts/import"):
            for raw in (b'{"format":1,"format":2}', b'{"x":NaN}', b"{}"):
                assert (
                    client.post(
                        PREFIX + suffix, headers=headers, files={"file": ("x.json", raw)}
                    ).status_code
                    == 422
                )
        assert (
            client.post(
                PREFIX + "/import",
                headers=headers,
                files={"file": ("huge.json", b" " * (4 * 1024 * 1024 + 1))},
            ).status_code
            == 422
        )
        assert (
            client.post(
                PREFIX + "/drafts/import",
                headers=headers,
                files={"file": ("huge.json", b" " * (256 * 1024 + 1))},
            ).status_code
            == 422
        )
        assert client.get(PREFIX + "/captures/invalid").status_code == 422
        assert client.get(PREFIX + "/captures/" + "a" * 64).status_code == 422
        assert client.get(PREFIX + "/profile").json()["captures"] == []
        for request_value in (None, [], "x"):
            body = {"format": DRAFT_PROFILE, "profile": DRAFT_PROFILE, "request": request_value}
            body["id"] = digest(body)
            assert (
                client.post(
                    PREFIX + "/drafts/import",
                    headers=headers,
                    files={"file": ("bad.json", encoded(body))},
                ).status_code
                == 422
            )
        assert not client.app.state.schedule_library.reviews
        assert not list((tmp_path / "native-schedule-captures").glob("capture-*"))
        assert not client.get("/api/session").json()["field_network_open"]
