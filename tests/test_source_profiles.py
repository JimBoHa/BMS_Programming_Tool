"""Independent literal values and strict versioned source/archive identities."""

import base64
import copy
import hashlib
import io
import json
import math
import struct
import zipfile
from pathlib import Path

import pytest
from bms_tool.formats import BMS, PLC, XML, _literal, export_plcopen, export_st, import_program
from bms_tool.iec_symbols import SymbolTable
from bms_tool.models import canonical
from bms_tool.sedona import application_xml, import_bundle, kit_name, kit_source
from bms_tool.source_profiles import CURRENT, LEGACY, source_profile

from .test_executable_numbers import passthrough
from .test_executable_numbers_archives import FIXTURES


def new_bundle(program):
    # Source/manifest-only fixture: binary members remain the authored opaque
    # nonexecuted placeholders from the frozen published legacy archive.
    with zipfile.ZipFile(FIXTURES / "legacy.sedona.zip") as archive:
        files = {name: archive.read(name) for name in archive.namelist() if name != "manifest.json"}
    files["program.bms.json"] = canonical(program)
    files["Graph.sedona"] = kit_source(program)
    files["app.sax"] = application_xml(kit_name(program), scan_seconds=program.scan_seconds)
    manifest = {
        "schema": "bms-sedona-bundle/2",
        "kit": kit_name(program),
        "source_generator": source_profile(),
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    return files, manifest


def bundle_bytes(files, manifest, *, manifest_raw=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
        archive.writestr(
            "manifest.json", json.dumps(manifest).encode() if manifest_raw is None else manifest_raw
        )
    return output.getvalue()


@pytest.mark.parametrize(
    "value",
    [
        0.12345678901234566,
        math.nextafter(1.0, 2.0),
        math.nextafter(1.0, 0.0),
        -0.0,
        2**53 + 2,
        2**60,
    ],
    ids=[
        "seventeen-digits",
        "next-up",
        "next-down",
        "signed-zero",
        "large-even-int",
        "large-power-int",
    ],
)
def test_current_literal_retains_exact_original_value_before_target_narrowing(value):
    raw = _literal(value)
    assert float(raw) == value
    if value == 0:
        assert math.copysign(1, float(raw)) == math.copysign(1, value)
    assert "." in raw.split("E")[0]
    p = passthrough(value=value, kind="Constant")
    before = p.digest()
    for content, name in ((export_st(p), "new.st"), (export_plcopen(p), "new.xml")):
        assert import_program(content, name).digest() == before
    assert p.digest() == before


def test_midpoint_source_text_selects_intended_binary32_side_and_legacy_stays_frozen():
    value = math.nextafter(1.0 + 2**-24, math.inf)
    assert struct.pack("!f", value).hex() == "3f800001"
    legacy, current = _literal(value, profile=LEGACY), _literal(value)
    assert struct.pack("!f", float(legacy)).hex() == "3f800000"
    assert struct.pack("!f", float(current)).hex() == "3f800001"
    assert source_profile(LEGACY)["rules_sha256"] == (
        "0a090b7203496dd0bd5c20756464e55a491a1be06c3b9647d42776dcc12a8222"
    )
    assert source_profile()["rules_sha256"] == (
        "be014ca51c1d3e42538d607d698b8ddacd164b2e0ddfb821c433329b99050493"
    )


@pytest.mark.parametrize("name", ["legacy.st", "legacy.xml", "legacy.sedona.zip"])
def test_frozen_published_safe_legacy_source_reopens_original_midpoint_without_compiling(
    name, monkeypatch
):
    from bms_tool import iec, sedona
    from bms_tool.engine import Engine

    fixtures = Path(__file__).parent / "fixtures/legacy-literal-safe"
    provenance = json.loads((fixtures / "provenance.json").read_text())
    raw = (fixtures / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance["fixture_sha256"][name]

    def forbidden(*args, **kwargs):
        pytest.fail("Archived source comparison must not execute or invoke native tools")

    with monkeypatch.context() as guard:
        guard.setattr(Engine, "__init__", forbidden)
        guard.setattr(iec, "toolchain", forbidden)
        guard.setattr(sedona, "toolchain", forbidden)
        restored = import_program(raw, name)
    assert restored.digest() == provenance["program_sha256"]
    value = restored.nodes[0].params["value"]
    assert value == math.nextafter(1.0 + 2**-24, math.inf)
    assert struct.pack("!f", value).hex() == "3f800001"
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            source = archive.read("Graph.sedona")
        assert CURRENT.encode() not in source
    else:
        source = raw
    assert b"1.00000005960464" in source
    assert b"1.000000059604645" not in source
    assert (fixtures / name).read_bytes() == raw


def test_new_st_has_exact_profile_binding_and_edited_source_cannot_fall_back():
    p = passthrough(value=0.12345678901234566, kind="Constant")
    raw = export_st(p)
    assert b"BMS_STUDIO_IR_V3" in raw and b"BMS_STUDIO_IR_V2" not in raw
    assert b"0.12345678901234566" in raw
    assert import_program(raw, "new.st").digest() == p.digest()
    name = SymbolTable(p).role("source").encode()
    original = name + b" := 0.12345678901234566;"
    assert raw.count(original) == 1
    with pytest.raises(ValueError, match="edited"):
        import_program(raw.replace(original, name + b" := 0.2;"), "edited.st")
    with pytest.raises(ValueError, match="one supported|Unknown"):
        import_program(raw.replace(b"BMS_STUDIO_IR_V3", b"BMS_STUDIO_IR_V99"), "unknown.st")
    with pytest.raises(ValueError, match="one supported"):
        import_program(raw + (FIXTURES / "legacy.st").read_bytes(), "duplicate.st")


@pytest.mark.parametrize("change", ["unknown-id", "wrong-rules", "legacy-id", "extra-field"])
def test_st_profile_metadata_cannot_be_confused_with_another_generator(change):
    raw = export_st(passthrough(value=1.0, kind="Constant"))
    import re

    encoded = re.search(rb"BMS_STUDIO_IR_V3 ([A-Za-z0-9+/=]+)", raw)[1]
    doc = json.loads(base64.b64decode(encoded))
    if change == "unknown-id":
        doc["source_generator"]["id"] = "unknown/99"
    elif change == "wrong-rules":
        doc["source_generator"]["rules_sha256"] = "0" * 64
    elif change == "legacy-id":
        doc["source_generator"] = source_profile(LEGACY)
    else:
        doc["source_generator"]["extra"] = True
    edited = raw.replace(encoded, base64.b64encode(json.dumps(doc).encode()))
    with pytest.raises(ValueError, match="profile|digest"):
        import_program(edited, "profile.st")


def test_duplicate_st_profile_document_fields_are_refused_before_program_admission():
    raw = export_st(passthrough(value=1.0, kind="Constant"))
    import re

    encoded = re.search(rb"BMS_STUDIO_IR_V3 ([A-Za-z0-9+/=]+)", raw)[1]
    doc = base64.b64decode(encoded)
    duplicate = b'{"source_generator":{},' + doc[1:]
    with pytest.raises(ValueError, match="Duplicate"):
        import_program(raw.replace(encoded, base64.b64encode(duplicate)), "duplicate.st")


@pytest.mark.parametrize(
    "change", ["unknown-id", "wrong-rules", "missing-rules", "extra-marker", "edited-body"]
)
def test_plcopen_profile_and_source_are_checked_together(change):
    p = passthrough(value=0.12345678901234566, kind="Constant")
    raw = export_plcopen(p)
    root = XML.fromstring(raw)
    embedded = root.find(".//{" + BMS + "}program")
    assert embedded.get("sourceProfile") == CURRENT
    assert embedded.get("sourceProfileRules") == source_profile()["rules_sha256"]
    if change == "unknown-id":
        embedded.set("sourceProfile", "unknown/99")
    elif change == "wrong-rules":
        embedded.set("sourceProfileRules", "0" * 64)
    elif change == "missing-rules":
        del embedded.attrib["sourceProfileRules"]
    elif change == "extra-marker":
        embedded.set("otherProfile", CURRENT)
    else:
        body = root.find(".//{" + PLC + "}body/{" + PLC + "}ST/*")
        body.text = body.text.replace("0.12345678901234566", "0.2")
    with pytest.raises(ValueError, match="profile|differs"):
        import_program(XML.tostring(root, encoding="utf-8", xml_declaration=True), "edited.xml")


def test_profile_bound_sedona_identity_and_new_source_archive_preserve_program():
    p = passthrough(value=0.12345678901234566, kind="Constant")
    assert kit_name(p, profile=LEGACY) == "studio" + p.digest()[:10]
    assert kit_name(p) != kit_name(p, profile=LEGACY)
    assert source_profile()["id"].encode() in kit_source(p)
    assert b"0.12345678901234566f" in kit_source(p)
    assert source_profile()["id"].encode() not in kit_source(p, profile=LEGACY)
    files, manifest = new_bundle(p)
    assert import_bundle(bundle_bytes(files, manifest)).digest() == p.digest()
    files["Graph.sedona"] = files["Graph.sedona"].replace(b"0.12345678901234566f", b"0.2f")
    manifest["files"]["Graph.sedona"] = hashlib.sha256(files["Graph.sedona"]).hexdigest()
    with pytest.raises(ValueError, match="source differs"):
        import_bundle(bundle_bytes(files, manifest))


@pytest.mark.parametrize(
    "change", ["unknown-schema", "unknown-profile", "wrong-rules", "legacy-conflict", "legacy-kit"]
)
def test_sedona_manifest_profile_cannot_override_source_or_kit_identity(change):
    p = passthrough(value=1.0, kind="Constant")
    files, manifest = new_bundle(p)
    if change == "unknown-schema":
        manifest["schema"] = "bms-sedona-bundle/99"
    elif change == "unknown-profile":
        manifest["source_generator"]["id"] = "unknown/99"
    elif change == "wrong-rules":
        manifest["source_generator"]["rules_sha256"] = "0" * 64
    elif change == "legacy-conflict":
        manifest["schema"] = "bms-sedona-bundle/1"
    else:
        manifest["kit"] = kit_name(p, profile=LEGACY)
    with pytest.raises(ValueError, match="profile|schema|source differs"):
        import_bundle(bundle_bytes(files, manifest))


def test_duplicate_or_oversized_sedona_profile_manifest_is_refused():
    files, manifest = new_bundle(passthrough(value=1.0, kind="Constant"))
    raw = json.dumps(manifest).encode()
    with pytest.raises(ValueError, match="Duplicate"):
        import_bundle(bundle_bytes(files, manifest, manifest_raw=b'{"schema":"bad",' + raw[1:]))
    with pytest.raises(ValueError, match="byte bound"):
        import_bundle(bundle_bytes(files, manifest, manifest_raw=b" " * (64 * 1024 + 1)))


def test_profile_results_are_copies_and_archival_hashes_stay_unchanged():
    original = source_profile()
    changed = copy.deepcopy(original)
    changed["id"] = "modified"
    assert source_profile() == original
    p = passthrough(value=-0.0, kind="Constant")
    before = canonical(p)
    export_st(p)
    export_plcopen(p)
    kit_source(p)
    assert canonical(p) == before
