"""Production HTTP boundaries, exact downloads and zero-network offline operations."""

import asyncio
import csv
import hashlib
import io
import json

import pytest
from bms_tool.accumulator_prescale import PROFILE, SourceRef, canonical, digest
from bms_tool.app import create_app
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_accumulator_prescale import configuration, make_meter_peer
from .test_connections import free_udp
from .test_point_status import options


def test_offline_review_token_strict_source_and_downloads(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        profile = client.get("/api/accumulator-prescale/profile").json()
        assert profile == PROFILE
        body = {"profile_sha256": PROFILE["sha256"], "configuration": configuration()}
        assert client.post("/api/accumulator-prescale/review", json=body).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/accumulator-prescale/review", json=body, headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["native_source"] is None and not report["field_writes"]
        assert report["content_sha256"] == digest(
            {k: v for k, v in report.items() if k != "content_sha256"}
        )
        key = {"id": report["id"], "content_sha256": report["content_sha256"]}
        exported = client.post("/api/accumulator-prescale/export/json", json=key, headers=headers)
        assert exported.content == canonical(report) + b"\n"
        assert exported.headers["x-file-sha256"] == hashlib.sha256(exported.content).hexdigest()
        csv_result = client.post("/api/accumulator-prescale/export/csv", json=key, headers=headers)
        rows = list(csv.DictReader(io.StringIO(csv_result.text)))
        assert [row["retained_pv"] for row in rows] == ["1", "3", "4", "6"]
        assert all(row["review_content_sha256"] == report["content_sha256"] for row in rows)
        imported = client.post(
            "/api/accumulator-prescale/import",
            files={"file": ("pulses.json", exported.content)},
            headers=headers,
        )
        assert imported.status_code == 200 and imported.json()["configuration"] == configuration()
        assert imported.json()["native_source_reused"] is False
        for raw in [
            b'{"profile_sha256":"x","profile_sha256":"y"}',
            b'{"configuration":NaN}',
            b'{"configuration":1e999}',
            b'{"configuration":[]}',
            b'{"configuration":null}',
        ]:
            bad = client.post(
                "/api/accumulator-prescale/review",
                content=raw,
                headers=headers | {"Content-Type": "application/json"},
            )
            assert bad.status_code == 422, bad.text
        bad_key = client.post(
            "/api/accumulator-prescale/export/json",
            json=key | {"content_sha256": "0" * 64},
            headers=headers,
        )
        assert bad_key.status_code == 422
        for raw in [b'{"format":"bms.accumulator-prescale-review/1"}', b"null", b"[]"]:
            assert (
                client.post(
                    "/api/accumulator-prescale/import",
                    files={"file": ("bad.json", raw)},
                    headers=headers,
                ).status_code
                == 422
            )
        assert len(client.app.state.prescale_reviews.reviews) == 1
        for kind in ("float-profile", "bool-batch"):
            altered = json.loads(exported.content)
            if kind == "float-profile":
                altered["profile"]["limits"]["batches"] = 256.0
            else:
                altered["simulation"]["rows"][0]["batch"] = True
            altered["content_sha256"] = digest(
                {k: v for k, v in altered.items() if k != "content_sha256"}
            )
            assert (
                client.post(
                    "/api/accumulator-prescale/import",
                    files={"file": ("typed.json", canonical(altered))},
                    headers=headers,
                ).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.asyncio
@pytest.mark.parametrize("routed", [False, True])
async def test_native_source_binding_uses_stored_evidence_without_further_queries(tmp_path, routed):
    app = create_app(tmp_path)
    peer = await make_meter_peer(routed=routed)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                    headers=headers,
                )
            ).status_code == 200
            native = await client.post(
                "/api/bacnet/point-status/read",
                json=options(peer, object_ids=["accumulator,1"], include_accumulator_metadata=True),
                headers=headers,
            )
            assert native.status_code == 200, native.text
            report = native.json()
            count = len(peer.requests)
            body = {
                "profile_sha256": PROFILE["sha256"],
                "configuration": configuration(),
                "source": {"report_id": report["id"], "object_id": "accumulator,1"},
            }
            response = await client.post(
                "/api/accumulator-prescale/review", json=body, headers=headers
            )
            assert response.status_code == 200, response.text
            review = response.json()
            assert review["native_source"]["target"] == report["target"]
            key = {"id": review["id"], "content_sha256": review["content_sha256"]}
            raw = await client.post(
                "/api/accumulator-prescale/export/json", json=key, headers=headers
            )
            assert b'"value":-0.0' in raw.content
            assert hashlib.sha256(raw.content).hexdigest() == raw.headers["x-file-sha256"]
            assert (
                await client.post(
                    "/api/accumulator-prescale/import",
                    files={"file": ("pulses.json", raw.content)},
                    headers=headers,
                )
            ).json()["native_source_reused"] is False
            bad = body | {"source": body["source"] | {"object_id": "accumulator,2"}}
            assert (
                await client.post("/api/accumulator-prescale/review", json=bad, headers=headers)
            ).status_code == 422
            assert len(peer.requests) == count
            # Reopening a new app cannot resolve previous source identity.
            fresh = create_app(tmp_path)
            with pytest.raises(ValueError, match="not retained"):
                fresh.state.prescale_reviews.native_source(SourceRef(**body["source"]))
            await fresh.state.point_status.close()
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)
