"""Authenticated local copy and native route registration with no field interface."""

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_sensor_trial_transfer import SensorSource
from fastapi.testclient import TestClient

from .test_native_sensor_trial import edit_for, sensor_source


def test_local_copies_are_source_bound_and_do_not_open_a_field_interface(tmp_path):
    app = create_app(tmp_path)
    native = app.state.native_applications
    files = sensor_source()
    actual = MoiIdentity(files[3]).summary()
    capture = native.storage.save(
        {
            "target": {"address": "192.0.2.44", "router": None, "dnet": None},
            "device": "device,5136",
            "identity": {
                "device": "device,5136",
                "object-name": actual["name"],
                "model-name": actual["model"],
                "vendor-identifier": 5,
            },
            "source_identity_matches": True,
            "connector_config": {},
            "read_only": True,
        },
        files,
    )
    base = "/api/bacnet/controller/native-application/sensor-trial"
    body = {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    with TestClient(app) as client:
        assert client.post(base + "/source", json=body).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        source = client.post(base + "/source", json=body, headers=headers)
        assert source.status_code == 200, source.text
        assert source.json()["sensors"][0]["address"] == 201
        review = client.post(
            base + "/copy-review", json={**body, "edit": edit_for(files)}, headers=headers
        )
        assert review.status_code == 200, review.text
        assert review.json()["controller_writes"] is False and review.json()["can_apply"] is False
        export = client.post(
            base + "/copy-export",
            json={
                **body,
                "edit": edit_for(files),
                "expected_review_sha256": review.json()["review_sha256"],
            },
            headers=headers,
        )
        assert export.status_code == 200, export.text
        assert sha(export.content) == review.json()["output_sha256"]
        rejected = client.post(
            base + "/copy-export",
            json={
                **body,
                "edit": {**edit_for(files), "addresses": [205]},
                "expected_review_sha256": review.json()["review_sha256"],
            },
            headers=headers,
        )
        assert rejected.status_code == 422 and "changed" in rejected.text
        assert client.get(base + "/status").json()["receipts"] == []
        assert not app.state.bacnet.app
    with pytest.raises(ValueError):
        app.state.native_sensor_trials.source(SensorSource(**{**body, "snapshot_sha256": "0" * 64}))
