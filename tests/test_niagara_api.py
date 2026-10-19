"""Archive inspection preserves unknown/protected native content without execution."""

import hashlib

from bms_tool.app import create_app
from fastapi.testclient import TestClient

from tests.test_niagara import archive


def opaque_archive():
    xml = b"""<bajaObjectGraph version="4.0" reversibleEncodingKeySource="keyring"><p h="0" n="Root" m="b=baja" t="b:Folder"><p h="1" n="PrivateLogic" t="vendor:CustomProgram"/><p n="HiddenLogic" t="vendor:HiddenProgram"/><p h="2" n="Result" t="control:NumericWritable"><p n="fallback"><p n="value" v="0"/></p><p n="Link" t="b:Link"><p n="sourceOrd" v="h:1"/><p n="sourceSlotName" v="out"/><p n="targetSlotName" v="in16"/></p></p></p></bajaObjectGraph>"""
    return archive(xml, extra=b"\x00opaque resource, preserved exactly\xff")


def test_niagara_inspector_preserves_unknown_protected_archive_bytes_and_never_opens_field_network(
    tmp_path,
):
    original = opaque_archive()
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            "/api/niagara/open", files={"file": ("opaque.bog", original)}, headers=headers
        )
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary["sha256"] == hashlib.sha256(original).hexdigest()
        assert summary["encoding"] == "keyring"
        assert summary["members"] == ["file.xml", "unknown.bin"]
        assert summary["unhandled_typed_records"][0]["type"] == "vendor:HiddenProgram"
        assert summary["links"][0]["resolved"]
        assert client.get(f"/api/niagara/{summary['sha256']}").json() == summary
        exported = client.post(f"/api/niagara/{summary['sha256']}/export", json={}, headers=headers)
        assert exported.status_code == 200 and exported.content == original
        conversion = client.post(
            "/api/import", files={"file": ("opaque.bog", original)}, headers=headers
        )
        assert conversion.status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False


def test_niagara_inspector_rejects_unsafe_input_and_requires_session_token(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/niagara/open", files={"file": ("x.bog", opaque_archive())}
            ).status_code
            == 403
        )
        bad = b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><bajaObjectGraph version="4.0">&a;</bajaObjectGraph>'
        response = client.post(
            "/api/niagara/open", files={"file": ("bad.bog", bad)}, headers=headers
        )
        assert response.status_code == 422


def test_niagara_inspector_cache_evicts_oldest_file_after_sixteen_unique_archives(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        identifiers = []
        for number in range(17):
            xml = f'<bajaObjectGraph version="4.0"><p h="1" n="Value{number}" t="kitControl:NumericConst"><p n="out" v="{number}"/></p></bajaObjectGraph>'.encode()
            response = client.post(
                "/api/niagara/open", files={"file": ("example.xml", xml)}, headers=headers
            )
            assert response.status_code == 200
            identifiers.append(response.json()["sha256"])
        assert client.get(f"/api/niagara/{identifiers[0]}").status_code == 422
        assert client.get(f"/api/niagara/{identifiers[1]}").status_code == 200
        assert client.get(f"/api/niagara/{identifiers[-1]}").status_code == 200
