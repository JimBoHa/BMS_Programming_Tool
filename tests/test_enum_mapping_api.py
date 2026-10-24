"""Offline review/export/import cannot silently become native field operations."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.enum_mapping import canonical
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_connections import free_udp
from .test_enum_mapping import plan
from .test_native_enum_domain import make_enum_peer
from .test_point_status import options
from .test_schedule_inventory import verify_hash


def test_offline_api_review_exact_exports_strict_import_and_stale_guards(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        source = plan()
        assert client.post("/api/enum-mapping/review", json=source).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/enum-mapping/review", headers=headers, json=source)
        assert response.status_code == 200, response.text
        review = response.json()
        digest = review.pop("review_sha256")
        assert hashlib.sha256(canonical(review)).hexdigest() == digest
        request = {"plan": source, "expected_review_sha256": digest}
        exported = client.post("/api/enum-mapping/export", headers=headers, json=request)
        assert exported.status_code == 200
        assert exported.content == canonical(review | {"review_sha256": digest})
        exported_plan = client.post("/api/enum-mapping/plan-export", headers=headers, json=request)
        assert exported_plan.status_code == 200 and exported_plan.content == canonical(
            review["source_plan"]
        )
        imported = client.post(
            "/api/enum-mapping/import",
            headers=headers,
            files={"file": ("enum.json", exported_plan.content, "application/json")},
        )
        assert imported.status_code == 200, imported.text
        assert (
            imported.json()["review_required"]
            and imported.json()["source_plan"] == review["source_plan"]
        )
        assert imported.json()["input_sha256"] == hashlib.sha256(exported_plan.content).hexdigest()
        source["mappings"][0]["target_code"] = 3
        assert (
            client.post("/api/enum-mapping/export", headers=headers, json=request).status_code
            == 422
        )
        source["source"]["states"][0]["code"] = False
        assert (
            client.post("/api/enum-mapping/review", headers=headers, json=source).status_code == 422
        )
        bad = client.post(
            "/api/enum-mapping/import",
            headers=headers,
            files={"file": ("bad.json", b'{"source":{},"source":{}}', "application/json")},
        )
        assert bad.status_code == 422 and "Duplicate" in bad.json()["detail"]
        assert not client.get("/api/session").json()["field_network_open"]
        assert app.state.bacnet.app is None and not app.state.bacnet.commands


@pytest.mark.parametrize("routed", [False, True])
async def test_native_api_metadata_opt_in_preserves_exact_code_and_property_status(
    tmp_path, routed
):
    app = create_app(tmp_path)
    peer = await make_enum_peer(routed=routed)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            response = await client.post(
                "/api/bacnet/point-status/read",
                headers=headers,
                json=options(
                    peer,
                    object_ids=["binary-input,1", "multi-state-value,2"],
                    include_enum_metadata=True,
                ),
            )
            assert response.status_code == 200, response.text
            report = response.json()
            assert report["complete"]
            binary, multistate = report["objects"]
            assert binary["enum_domain"]["states"][0]["label"] == "On"
            assert binary["enum_domain"]["value_validation"]["code"] == 1
            assert multistate["enum_domain"]["number_of_states"] == 3
            assert [s["code"] for s in multistate["enum_domain"]["states"]] == [1, 2, 3]
            verify_hash(report)
            count = len(peer.requests)
            exact = await client.post(
                "/api/bacnet/point-status/export", headers=headers, json={"id": report["id"]}
            )
            assert (
                exact.status_code == 200
                and exact.content
                == json.dumps(
                    report, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            assert len(peer.requests) == count and not app.state.bacnet.commands
    finally:
        await app.state.point_status.close()
        app.state.bacnet.close()
        peer.close()
