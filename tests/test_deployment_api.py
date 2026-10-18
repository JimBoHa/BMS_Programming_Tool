import pytest
from bms_tool.app import create_app
from bms_tool.deployment import Runtime
from bms_tool.models import Node
from bms_tool.storage import Conflict, Store
from bms_tool.templates import vav
from fastapi.testclient import TestClient


def test_revision_conflicts_prevent_overwrite(tmp_path):
    store = Store(tmp_path)
    p = vav()
    saved = store.save(p, 0)
    assert saved.revision == 1
    with pytest.raises(Conflict):
        store.save(p, 0)
    assert store.load(p.id).revision == 1 and len(store.versions(p.id)) == 1


def test_online_change_and_rollback_restore_program_and_state(tmp_path):
    runtime = Runtime(Store(tmp_path))
    p = vav()
    runtime.apply(runtime.plan(p)["token"])
    runtime.engine.step({"zone": 80})
    before = runtime.engine.snapshot()
    edited = p.model_copy(deep=True)
    edited.nodes.append(
        Node(id="unused_sensor", kind="Input", label="Test input", params={"default": 0})
    )
    plan = runtime.plan(edited)
    assert plan["diff"]["added"] == ["unused_sensor"]
    runtime.apply(plan["token"])
    assert "unused_sensor" in runtime.engine.nodes
    old = runtime.backups[-1]["id"]
    runtime.rollback(old, runtime.generation)
    assert runtime.engine.snapshot() == before
    assert "unused_sensor" not in runtime.engine.nodes


def test_deployment_plan_is_single_use_and_generation_bound(tmp_path):
    runtime = Runtime(Store(tmp_path))
    p = vav()
    a = runtime.plan(p)
    b = runtime.plan(p)
    runtime.apply(a["token"])
    with pytest.raises(ValueError, match="already consumed"):
        runtime.apply(a["token"])
    with pytest.raises(ValueError, match="changed since"):
        runtime.apply(b["token"])


def test_native_hardware_target_cannot_be_sent_to_our_runtime(tmp_path):
    with pytest.raises(ValueError, match="cannot install"):
        Runtime(Store(tmp_path)).plan(vav(family="johnson-fx"))


def test_api_local_session_origin_and_project_round_trip(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        program = vav().model_dump()
        assert client.post("/api/validate", json=program).status_code == 403
        token = client.get("/api/session").json()["token"]
        headers = {"X-Studio-Token": token}
        assert (
            client.post(
                "/api/validate",
                json=program,
                headers={**headers, "Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )
        assert client.get("/api/session", headers={"Host": "attacker.invalid"}).status_code == 403
        assert client.post("/api/validate", json=program, headers=headers).status_code == 200
        result = client.post(
            "/api/projects",
            json={"program": program, "expected_revision": 0},
            headers=headers,
        )
        assert result.status_code == 200, result.text
        assert result.json()["revision"] == 1
        assert (
            client.post(
                "/api/projects",
                json={"program": program, "expected_revision": 0},
                headers=headers,
            ).status_code
            == 409
        )
        result = client.post(
            "/api/simulation/step",
            json={"program": program, "inputs": {"zone": 80}},
            headers=headers,
        )
        assert result.status_code == 200, result.text
        assert result.json()["last"]["outputs"]["damper"] > 50
        assert not client.get("/api/bacnet/status").json()["connected"]
        assert len(client.get("/api/requirements").json()) >= 40
        assert client.get("/api/library/unknown/anything").status_code == 422
        assert client.get("/api/library/jci/not-in-catalog").status_code == 422
