"""HTTP file inspection/capture/export with a real loopback UDP File peer."""

import hashlib
import io
import json
import zipfile

import httpx
from bms_tool.app import create_app

from .test_bacnet_files import link as link
from .test_bacnet_files import port


async def test_http_file_capture_stream_records_and_offline_restart(link, tmp_path):
    server, _, _, target = link
    directory = tmp_path / "http-files"
    app = create_app(directory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            profile = await client.get("/api/bacnet/files/status")
            assert profile.status_code == 200 and not profile.json()["native_caf"]
            assert (await client.get("/api/bacnet/files/captures")).json() == []
            assert not server.all_requests
            unopened = await client.post("/api/bacnet/files/inspect", json=target, headers=headers)
            assert unopened.status_code == 422 and not server.all_requests
            opened = await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{port()}"},
                headers=headers,
            )
            assert opened.status_code == 200, opened.text
            inspected = await client.post("/api/bacnet/files/inspect", json=target, headers=headers)
            assert inspected.status_code == 200, inspected.text
            inspection = inspected.json()
            assert not server.atomic_requests
            receipts = []
            for row in inspection["files"]:
                response = await client.post(
                    "/api/bacnet/files/read",
                    json={
                        "inspection_id": inspection["id"],
                        "object_id": row["object_id"],
                        "metadata_sha256": row["metadata_sha256"],
                    },
                    headers=headers,
                )
                assert response.status_code == 200, response.text
                receipt = response.json()
                assert receipt["complete"] and not receipt["native_caf"]
                receipts.append(receipt)
            await client.post("/api/bacnet/disconnect", json={}, headers=headers)
            traffic = len(server.all_requests)
            captures = (await client.get("/api/bacnet/files/captures")).json()
            assert {row["id"] for row in captures} == {row["id"] for row in receipts}
            for index, receipt in enumerate(receipts):
                uri = "/api/bacnet/files/captures/" + receipt["id"]
                assert (await client.get(uri)).json() == receipt
                exported = await client.get(uri + "/export")
                assert exported.status_code == 200
                if index == 0:
                    assert exported.content == server.payload
                    assert exported.headers["content-type"] == "application/octet-stream"
                    assert hashlib.sha256(exported.content).hexdigest() == receipt["sha256"]
                    assert exported.headers["content-disposition"].endswith('.bin"')
                else:
                    assert exported.headers["content-type"] == "application/zip"
                    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                        assert [
                            archive.read(f"records/{number:08d}.bin") for number in range(3)
                        ] == server.records
                        assert json.loads(archive.read("receipt.json")) == receipt
            assert len(server.all_requests) == traffic
    reopened = create_app(directory)
    async with reopened.router.lifespan_context(reopened):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reopened), base_url="http://testserver"
        ) as client:
            assert not (await client.get("/api/bacnet/status")).json()["connected"]
            assert len((await client.get("/api/bacnet/files/captures")).json()) == 2
            assert len(server.all_requests) == traffic
    assert set(server.all_requests) == {"ReadPropertyRequest", "AtomicReadFileRequest"}


async def test_http_file_guards_refuse_untrusted_missing_or_changed_requests(link, tmp_path):
    server, _, _, target = link
    app = create_app(tmp_path / "http-file-guards")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            for bad_headers in (
                {},
                headers | {"Host": "untrusted.example"},
                headers | {"Origin": "https://untrusted.example"},
            ):
                response = await client.post(
                    "/api/bacnet/files/inspect", json=target, headers=bad_headers
                )
                assert response.status_code == 403
            assert not server.all_requests
            await client.post(
                "/api/bacnet/connect",
                json={"local_address": f"127.0.0.1:{port()}"},
                headers=headers,
            )
            inspected = await client.post("/api/bacnet/files/inspect", json=target, headers=headers)
            assert inspected.status_code == 200, inspected.text
            inspection = inspected.json()
            row = inspection["files"][0]
            body = {
                "inspection_id": inspection["id"],
                "object_id": row["object_id"],
                "metadata_sha256": row["metadata_sha256"],
            }
            for altered in (
                body | {"metadata_sha256": "0" * 64},
                body | {"object_id": "file,999"},
                body | {"inspection_id": "0" * 32},
                body | {"write": True},
            ):
                response = await client.post(
                    "/api/bacnet/files/read", json=altered, headers=headers
                )
                assert response.status_code == 422
            assert not server.atomic_requests
            server.stream.fileSize += 1
            changed = await client.post("/api/bacnet/files/read", json=body, headers=headers)
            assert changed.status_code == 422 and "metadata" in changed.text
            assert not server.atomic_requests
            assert (await client.get("/api/bacnet/files/captures")).json() == []
            for suffix in ("", "/export"):
                invalid = await client.get("/api/bacnet/files/captures/not-a-capture" + suffix)
                assert invalid.status_code == 422
