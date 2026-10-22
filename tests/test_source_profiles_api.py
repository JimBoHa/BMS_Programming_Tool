"""Actual HTTP source downloads/imports and native-report profile provenance."""

import math

from bms_tool.app import create_app
from bms_tool.models import Program
from bms_tool.source_profiles import source_profile
from fastapi.testclient import TestClient

from .test_executable_numbers import passthrough


def test_profile_bound_source_downloads_reopen_original_program_without_field_access(tmp_path):
    p = passthrough(value=math.nextafter(1.0 + 2**-24, math.inf), kind="Constant")
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for format, name in (("st", "new.st"), ("plcopen", "new.xml")):
            downloaded = client.post(
                "/api/export", headers=headers, json={"program": p.model_dump(), "format": format}
            )
            assert (
                downloaded.status_code == 200
                and "attachment" in downloaded.headers["content-disposition"]
            )
            assert b"1.000000059604645" in downloaded.content
            reopened = client.post(
                "/api/import",
                headers=headers,
                files={"file": (name, downloaded.content, "application/octet-stream")},
            )
            assert reopened.status_code == 200, reopened.text
            assert Program.model_validate(reopened.json()).digest() == p.digest()
        preview = client.post(
            "/api/conversion/preview", headers=headers, json={"program": p.model_dump()}
        )
        assert preview.status_code == 200
        rows = {row["format"]: row for row in preview.json()["targets"]}
        for format in ("st", "plcopen", "sedona"):
            assert rows[format]["source_generator"] == source_profile()
        for format in ("json", "graphml", "bog"):
            assert "source_generator" not in rows[format]
        assert client.get("/api/iec/status").json()["source_generator"] == source_profile()
        assert not client.get("/api/session").json()["field_network_open"]
