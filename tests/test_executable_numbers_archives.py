"""Published legacy source bytes remain archival even when execution is refused."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from bms_tool import iec, sedona
from bms_tool.engine import Engine
from bms_tool.formats import export_program, import_program

FIXTURES = Path(__file__).parent / "fixtures/legacy-numeric"


@pytest.mark.parametrize(
    "name", ["legacy.st", "legacy.xml", "legacy.graphml", "legacy.sedona.zip", "legacy.bog"]
)
def test_untouched_legacy_source_preserves_original_integer_and_digest_without_execution(
    name, monkeypatch
):
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance["fixture_sha256"][name]

    def forbidden(*args, **kwargs):
        pytest.fail("Archival source comparison must not execute or invoke native tools")

    with monkeypatch.context() as guard:
        guard.setattr(Engine, "__init__", forbidden)
        guard.setattr(sedona, "toolchain", forbidden)
        guard.setattr(iec, "toolchain", forbidden)
        restored = import_program(raw, name)
    assert restored.digest() == provenance["program_sha256"]
    assert restored.nodes[0].params["value"] == 9007199254740993
    with pytest.raises(ValueError, match="binary64"):
        Engine(restored)
    for format in ("st", "plcopen", "sedona"):
        with pytest.raises(ValueError, match="binary64"):
            export_program(restored, format)
    assert restored.digest() == provenance["program_sha256"]


@pytest.mark.parametrize("name", ["legacy.st", "legacy.xml"])
def test_edited_legacy_executable_source_is_still_rejected(name):
    raw = (FIXTURES / name).read_bytes()
    assert b"9.00719925474099E+15" in raw
    edited = raw.replace(b"9.00719925474099E+15", b"42.0", 1)
    with pytest.raises(ValueError, match="edited|differs"):
        import_program(edited, name)


def test_edited_sedona_source_is_rejected_even_with_an_updated_payload_manifest():
    with zipfile.ZipFile(FIXTURES / "legacy.sedona.zip") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["Graph.sedona"] = files["Graph.sedona"].replace(b"9.00719925474099E+15f", b"42.0f", 1)
    manifest = json.loads(files["manifest.json"])
    manifest["files"]["Graph.sedona"] = hashlib.sha256(files["Graph.sedona"]).hexdigest()
    files["manifest.json"] = json.dumps(manifest).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="source differs"):
        import_program(output.getvalue(), "edited.sedona.zip")


def test_legacy_embedded_program_tampering_does_not_become_an_archival_bypass():
    raw = (FIXTURES / "legacy.graphml").read_bytes()
    edited = raw.replace(b'"id": "source"', b'"id": "other"', 1)
    assert edited != raw
    with pytest.raises(ValueError, match="missing|differs"):
        import_program(edited, "edited.graphml")


def test_edited_native_bog_source_does_not_match_its_embedded_original_program():
    with zipfile.ZipFile(FIXTURES / "legacy.bog") as archive:
        raw = archive.read("file.xml")
    assert b"9007199254740992.0" in raw
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("file.xml", raw.replace(b"9007199254740992.0", b"42.0", 1))
    with pytest.raises(ValueError, match="edited"):
        import_program(output.getvalue(), "edited.bog")
