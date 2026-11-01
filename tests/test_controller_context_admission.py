"""Inherited profiles must not accept selected-controller intent they ignore."""

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_event_log import EventLogHistoryRequest
from bms_tool.bacnet_history_multiple import MultipleHistoryRequest


def request(kind):
    return {
        "address": "127.0.0.1:49999",
        "device": "device,42",
        "object_id": f"{kind},1",
        "operation_id": "owned-operation",
        "controller_target": {
            "address": "127.0.0.1:49999",
            "device": "device,42",
            "router": None,
            "dnet": None,
        },
        "expected_connector_config": {"local_address": "127.0.0.1:49998"},
    }


@pytest.mark.parametrize(
    "kind,model",
    [
        ("trend-log-multiple", MultipleHistoryRequest),
        ("event-log", EventLogHistoryRequest),
    ],
)
def test_unsupported_inherited_profiles_refuse_nested_context_but_keep_old_shape(kind, model):
    body = request(kind)
    with pytest.raises(ValueError, match="nested controller context is unsupported"):
        model(**body)
    body.pop("controller_target")
    body.pop("expected_connector_config")
    legacy = model(**body).model_dump()
    assert legacy["address"] == body["address"] and legacy["device"] == "device,42"
    assert "controller_target" not in legacy and "expected_connector_config" not in legacy


@pytest.mark.parametrize(
    "kind,state,route",
    [
        ("trend-log-multiple", "multiple_history", "history-multiple"),
        ("event-log", "event_log", "event-log"),
    ],
)
async def test_unsupported_context_is_refused_before_history_service_dispatch(
    tmp_path,
    monkeypatch,
    kind,
    state,
    route,
):
    app = create_app(tmp_path)
    calls = []

    async def observe(**kwargs):
        calls.append(kwargs)
        return {"unexpected_dispatch": True}

    async with app.router.lifespan_context(app):
        monkeypatch.setattr(getattr(app.state, state), "read", observe)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            response = await client.post(
                f"/api/bacnet/{route}/read", headers=headers, json=request(kind)
            )
            assert response.status_code == 422, response.text
            assert "nested controller context is unsupported" in response.text
            assert not calls
