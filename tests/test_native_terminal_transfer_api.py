"""New local transfer-family copies keep exact review guards and no field authority."""

from bms_tool.app import create_app
from bms_tool.native_inputs import NativeInputCompiler
from fastapi.testclient import TestClient

from .test_native_inputs import source
from .test_native_signal_compiler import retained
from .test_native_terminal_input import terminal_edit

BASE = "/api/bacnet/controller/native-application"


def test_profile_two_local_http_export_cannot_be_promoted_to_apply(tmp_path):
    app = create_app(tmp_path)
    native = app.state.native_applications
    files = source(existing=True)
    capture = retained(
        native.storage,
        files,
        identity={
            "object-name": "Authored controller",
            "model-name": "M4-CVM03050-0",
            "vendor-identifier": 5,
        },
    )
    body = {
        "capture_id": capture["id"],
        "snapshot_sha256": capture["evidence_sha256"],
        "edit": terminal_edit(NativeInputCompiler(files)),
    }
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/input/copy/preview", json=body).status_code == 403
        response = client.post(BASE + "/input/copy/preview", headers=headers, json=body)
        assert response.status_code == 200, response.text
        review = response.json()
        assert (
            review["profile"]
            == review["compilation"]["profile"]
            == "native-local-universal-input-transfer/2"
        )
        assert (
            not review["controller_queries"]
            and not review["controller_writes"]
            and "token" not in review
        )
        exported = client.post(
            BASE + "/input/copy/export",
            headers=headers,
            json=body | {"expected_review_sha256": review["review_sha256"]},
        )
        assert exported.status_code == 200, exported.text
        assert (
            NativeInputCompiler({**files, 3: exported.content}).source()["inputs"][0]["slot"] == 3
        )
        assert (
            client.post(
                BASE + "/input/copy/export",
                headers=headers,
                json=body | {"expected_review_sha256": "0" * 64},
            ).status_code
            == 422
        )
        assert (
            client.post(
                BASE + "/input/apply",
                headers=headers,
                json=body | {"review_sha256": review["review_sha256"]},
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False
    assert (
        native.storage.load(capture["id"])[1] == files
        and not native.plans
        and not native.storage.receipts()
    )
