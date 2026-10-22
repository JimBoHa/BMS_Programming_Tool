import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from .history_identity_fixture import HIGH_ID, seed


def test_actual_sqlite_high_identity_survives_exact_api_source(tmp_path):
    routes = asyncio.run(seed(tmp_path))
    with TestClient(create_app(tmp_path)) as client:
        deliveries = client.get(
            "/api/notifications/deliveries", params={"route_id": routes["high"]}
        )
        assert f'"id":{HIGH_ID}' in deliveries.text
        assert json.loads(deliveries.text)["rows"][0]["id"] == HIGH_ID
        for source, field, endpoint in (
            ("alarm", "id", "alarms"),
            ("event", "sequence", "events"),
            ("trend", "sequence", "trends"),
        ):
            response = client.get(
                f"/api/observations/{endpoint}",
                params={"source": f"simulation/identity-high-{source}"},
            )
            assert response.status_code == 200
            assert any(row[field] >= HIGH_ID for row in json.loads(response.text))
        assert client.get("/api/session").json()["field_network_open"] is False
        assert client.get("/api/notifications/status").json()["active_routes"] == 0


def test_installed_fixture_refuses_checkout_fallback_before_seeding(tmp_path):
    target = tmp_path / "not-an-installed-package"
    target.mkdir()
    state = tmp_path / "unseeded"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tests/history_identity_fixture.py"), "--port", "1"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(root / "backend"),
            "BMS_STUDIO_DATA": str(state),
            "BMS_TEST_INSTALLED_TARGET": str(target),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "outside installed test target" in result.stderr
    assert not state.exists()
