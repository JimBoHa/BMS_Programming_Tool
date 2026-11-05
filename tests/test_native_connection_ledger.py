"""Recorded connection evidence stays immutable, local and separately attributable."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.native_connection_ledger import PROFILE, connection_reference
from bms_tool.native_connection_transfer import compile_connection
from fastapi.testclient import TestClient

from .test_change_ledger import query
from .test_moi_wire_sources import REF, A, D
from .test_native_applications import native_link
from .test_native_connection_compiler import proposal, setup
from .test_native_connection_transfer import applying, connection_review


def authored_body(tmp_path):
    _, service, files, request = setup(tmp_path)
    edit = proposal(service, request)
    output, compilation = compile_connection(files, edit)
    return {
        "change_kind": "connection",
        "operation_profile": PROFILE,
        "connection_edit": edit,
        "connection_guard": compilation["connection_guard"],
        "compilation": compilation,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "old_instance": 5136,
        "new_instance": 5136,
        "connection_change_confirmed": True,
    }


def test_projection_copies_recorded_tuples_and_never_changes_the_proposal(tmp_path):
    body = authored_body(tmp_path)
    before = copy.deepcopy(body)
    projected = connection_reference(body)
    assert projected["object"] == REF
    meta = projected["native_connection"]
    assert meta["state"] == "recorded" and meta["profile"] == PROFILE
    assert meta["source_ref"] == A and meta["target_ref"] == D
    assert meta["index"] == 1 and meta["connection_count_after"] == 2
    assert meta["connection_confirmation_recorded"] is True
    meta["new"][0] = 99
    meta["prototype_old"][0] = 99
    assert body == before


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "edit",
        "guard",
        "compile",
        "hash",
        "tuple",
        "count",
        "identity",
        "extra",
        "bool-count",
    ],
)
def test_inconsistent_or_future_evidence_withholds_recorded_connection_metadata(tmp_path, case):
    body = authored_body(tmp_path)
    if case == "profile":
        body["operation_profile"] = "future/2"
    elif case == "edit":
        body["connection_edit"]["target_ref"] = A
    elif case == "guard":
        body["connection_guard"]["configuration_sha256"] = "f" * 64
    elif case == "compile":
        body["compilation"]["profile"] = "future/2"
    elif case == "hash":
        body["native_payload_sha256"] = "f" * 64
    elif case == "tuple":
        body["compilation"]["connection_edit"]["new"][3] = 999
    elif case == "count":
        body["compilation"]["connection_edit"]["connection_count_after"] = 3
    elif case == "identity":
        body["new_instance"] += 1
    elif case == "extra":
        body["connection_edit"]["token"] = "forbidden"
    else:
        body["compilation"]["connection_edit"]["connection_count_before"] = True
    assert connection_reference(body)["native_connection"]["state"] == "unavailable"


async def test_actual_receipt_reopens_as_local_searchable_connection_evidence(
    tmp_path, monkeypatch
):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(tmp_path, patch)) as generator:
            link = await anext(generator)
            _, plan = await connection_review(link)
            result = await link[3].apply_connection(**applying(plan))
            assert result["result"]["status"] == "verified", result
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Ledger attempted a field operation or reopened an original backup")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    storage = app.state.native_applications.storage
    monkeypatch.setattr(storage, "load", forbidden)
    report = await query(app, source="native")
    row = next(r for r in report["rows"] if r["id"] == result["intent"]["id"])
    assert (
        row["label"] == "Native matching connection transfer"
        and row["native_change_kind"] == "connection"
    )
    assert row["object"] == REF and row["native_connection"]["target_ref"] == D
    assert row["state"] == "verified" and report["read_only"] and report["field_requests"] == 0
    assert (await query(app, source="native", text=D))["rows"][0]["id"] == row["id"]
    assert storage.receipt(row["id"]) == result
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/changes/query", headers=headers, json={"source": "native"})
        assert response.status_code == 200 and response.json()["field_requests"] == 0
