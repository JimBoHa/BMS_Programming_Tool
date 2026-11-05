"""Authored observed binary schemas and literal encoding-preserving local exports."""

import gzip

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_terminal_copies import MoiTerminalCopies
from bms_tool.moi_terminal_labels import PROFILE, EncodedTerminalCopies
from bms_tool.native_terminal_labels import (
    EncodedEffectiveNativeTerminalCopies,
    EncodedNativeTerminalCopies,
)
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed, property_bytes
from .test_moi_terminal_copies import authored, proposal
from .test_moi_terminal_output_namespace import with_output
from .test_native_connection_copies import filesystem
from .test_native_terminal_copies import literal_effective, setup
from .test_native_terminal_copies import proposal as service_proposal


def observed_shape(*, encoding=4, binary=True, compressed=False, wide=False, slot_width=1):
    files = authored(binary=binary, wide=wide, slot_width=slot_width)
    rows = []
    for width, body in frames(files[3]):
        if int.from_bytes(body[:2], "little") == (242 if binary else 240) and b"UI IN1" in body:
            if binary:
                # The retained class-242 schema has state labels, not analog scaling fields.
                body = native_record(
                    242,
                    101,
                    [
                        (32527, encoded(CharacterString("controller/3_101"))),
                        (4, encoded(CharacterString("Closed"))),
                        (28, encoded(CharacterString("Authored binary input"))),
                        (31, encoded(CharacterString("UI IN1", _encoding=encoding))),
                        (46, encoded(CharacterString("Open"))),
                        (75, encoded(ObjectIdentifier((3, 101)))),
                        (519, bytes([0x20 + slot_width]) + (1).to_bytes(slot_width, "big")),
                        (931, encoded(Enumerated(14))),
                        (2390, encoded(CharacterString("Authored input"))),
                        (15, encoded(Unsigned(77))),
                        (33, encoded(Unsigned(90000))),
                        (84, encoded(Enumerated(1))),
                    ],
                )
            else:
                before = property_bytes(31, b"\x75\x07\x00UI IN1")
                assert body.count(before) == 1
                body = body.replace(
                    before,
                    property_bytes(31, encoded(CharacterString("UI IN1", _encoding=encoding))),
                )
        rows.append((width, body))
    data = packed(files[3][:14], rows)
    return {**files, 3: gzip.compress(data, mtime=54321) if compressed else data}


def literal(raw, *, binary=True, encoding=4, slot_width=1):
    # Independent expected whole image. These literal tag bytes are not compiler output.
    before_label = b"\x75\x0d\x04\x00U\x00I\x00 \x00I\x00N\x001"
    after_label = b"\x75\x0d\x04\x00U\x00I\x00 \x00I\x00N\x003"
    if encoding == 0:
        before_label, after_label = b"\x75\x07\x00UI IN1", b"\x75\x07\x00UI IN3"
    rows = []
    for width, body in frames(raw):
        if int.from_bytes(body[:2], "little") == (242 if binary else 240):
            before = property_bytes(31, before_label)
            if before in body:
                old = property_bytes(
                    519, bytes([0x20 + slot_width]) + (1).to_bytes(slot_width, "big")
                )
                new = property_bytes(
                    519, bytes([0x20 + slot_width]) + (3).to_bytes(slot_width, "big")
                )
                assert body.count(before) == body.count(old) == 1
                body = body.replace(before, property_bytes(31, after_label)).replace(old, new)
        rows.append((width, body))
    return packed(raw[:14], rows)


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("slot_width", [1, 2, 3, 4])
def test_literal_whole_image_retains_label_encoding_and_every_other_byte(
    encoding, binary, compressed, wide, slot_width
):
    raw = observed_shape(
        encoding=encoding, binary=binary, compressed=compressed, wide=wide, slot_width=slot_width
    )[3]
    compiler = EncodedTerminalCopies(raw)
    output, review = compiler.compile(**proposal(compiler))
    result = MoiIdentity(output)
    assert result.data == literal(
        compiler.editor.data, binary=binary, encoding=encoding, slot_width=slot_width
    )
    assert review["profile"] == PROFILE and review["device_type_character_encoding"] == encoding
    assert review["device_type_encoding_preserved"] and review["other_expanded_bytes_preserved"]
    assert not review["controller_write"] and not review["field_transfer_enabled"]
    assert review["compilation_sha256"] == seal(
        {k: v for k, v in review.items() if k != "compilation_sha256"}
    )
    assert EncodedTerminalCopies(output).inspect()["unassigned_slots"] == [1, 2]
    assert compiler.compile(**proposal(compiler, destination_slot=1))[0] == raw
    if compressed:
        assert output[:10] == raw[:10]
    if binary:
        before = compiler.editor.reader.records["controller/3_101"]
        after = result.reader.records["controller/3_101"]
        assert not {518, 2180, 1293, 1294, 1295, 1296}.intersection(before["properties"])
        for pid in (4, 28, 46, 931, 15, 33, 84):
            assert (
                before["properties"][pid]["encoded_sha256"]
                == after["properties"][pid]["encoded_sha256"]
            )


@pytest.mark.parametrize("output_namespace", [False, True])
def test_old_compiler_profiles_still_refuse_ucs2_without_promoting_field_authority(
    output_namespace,
):
    with pytest.raises(ValueError, match="ASCII universal-terminal"):
        MoiTerminalCopies(observed_shape()[3], output_namespace=output_namespace)


@pytest.mark.parametrize("cid,label", [(239, "BO OUT1"), (241, "CO OUT4")])
def test_output_namespace_and_opaque_output_record_remain_independent(cid, label):
    files = with_output(observed_shape(), cid=cid, label=label, slot=3)
    compiler = EncodedTerminalCopies(files[3])
    output, _ = compiler.compile(**proposal(compiler))
    assert MoiIdentity(output).data == literal(compiler.editor.data)
    assert EncodedTerminalCopies(output).inspect()["unassigned_slots"] == [1, 2]


@pytest.mark.parametrize(
    "updates",
    [
        {"label": "UI IN2"},
        {"ref": "controller/sa/1_501"},
        {"extra": [(2577, encoded(Unsigned(0)))]},
    ],
)
def test_encoding_profile_does_not_relax_output_host_or_occupancy_admission(updates):
    with pytest.raises(ValueError):
        EncodedTerminalCopies(with_output(observed_shape(), **updates)[3])


@pytest.mark.parametrize("encoding", [1, 2, 3, 5, 6, 255])
def test_unqualified_character_encodings_are_not_guessed(encoding):
    # Replace the ASCII encoding byte only; no BACnet library encoder can normalize it.
    files = observed_shape(encoding=0)
    before = property_bytes(31, b"\x75\x07\x00UI IN1")
    assert files[3].count(before) == 1
    candidate = files[3].replace(
        before, property_bytes(31, b"\x75\x07" + bytes([encoding]) + b"UI IN1")
    )
    with pytest.raises(ValueError):
        EncodedTerminalCopies(candidate)


@pytest.mark.parametrize("effective", [False, True])
def test_saved_effective_and_archive_paths_are_sealed_local_copies(tmp_path, effective):
    storage, old, files, query = setup(tmp_path, files=observed_shape(compressed=True))
    service = (EncodedEffectiveNativeTerminalCopies if effective else EncodedNativeTerminalCopies)(
        old.records
    )
    before = filesystem(storage.directory)
    request = service_proposal(service, query)
    output, review = service.preview(request)
    basis = MoiIdentity(files[3]).data
    assert MoiIdentity(output).data == literal(literal_effective(basis) if effective else basis)
    assert review["saved_settings_merged"] is effective
    assert review["compiler_profile"] == PROFILE and review["profile"].endswith("/2")
    assert service.export({**request, "review_sha256": review["review_sha256"]}) == (output, review)
    with pytest.raises(ValueError):
        service.export({**request, "review_sha256": "0" * 64})
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize("effective", [False, True])
def test_encoded_http_routes_keep_csrf_guards_headers_and_zero_field_access(
    tmp_path, monkeypatch, effective
):
    app = create_app(tmp_path)
    native = app.state.native_applications
    _, fixture, files, query = setup(tmp_path / "fixture", files=observed_shape())
    snapshot, _ = fixture.records.storage.load(query["capture_id"])
    saved = native.storage.save(
        {
            k: snapshot[k]
            for k in (
                "target",
                "device",
                "identity",
                "source_identity_matches",
                "connector_config",
                "read_only",
            )
        },
        files,
    )
    query.update(capture_id=saved["id"], snapshot_sha256=saved["evidence_sha256"])

    def forbidden(*args, **kwargs):
        pytest.fail("Encoding-preserving local copies entered a field/mutation path")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden, raising=False)
    monkeypatch.setattr(native.storage, "intent", forbidden)
    before = filesystem(native.storage.directory)
    service = (EncodedEffectiveNativeTerminalCopies if effective else EncodedNativeTerminalCopies)(
        fixture.records
    )
    # The fixture and application use separate immutable captures; proposals bind the new IDs.
    fixture_query = {
        **query,
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
    }
    request = {**service_proposal(service, fixture_query), **query}
    route = (
        "/api/bacnet/controller/native-application/inputs/encoded-labels/"
        + ("effective-" if effective else "")
        + "terminal-copy"
    )
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(route + "/source", json=query).status_code == 403
        response = client.post(route + "/source", headers=headers, json=query)
        assert response.status_code == 200, response.text
        assert response.json()["inventory"]["inputs"][-1]["device_type_character_encoding"] == 4
        response = client.post(route + "/preview", headers=headers, json=request)
        assert response.status_code == 200, response.text
        review = response.json()
        export = {**request, "review_sha256": review["review_sha256"]}
        response = client.post(route + "/export", headers=headers, json=export)
        assert response.status_code == 200, response.text
        for key, value in [
            ("Artifact", sha(response.content)),
            ("Review", review["review_sha256"]),
            ("Snapshot", query["snapshot_sha256"]),
            ("Source", query["source_sha256"]),
            ("Compilation", review["compilation"]["compilation_sha256"]),
        ]:
            assert response.headers[f"X-Studio-{key}-Sha256"] == value
        for change in (
            {"destination_slot": True},
            {"destination_slot": 3.0},
            {"ref": "controller/missing"},
            {"record_sha256": "0" * 64},
            {"source_sha256": "0" * 64},
            {"controller_write": True},
            {"host": "sa"},
            {"review_sha256": "0" * 64},
        ):
            assert (
                client.post(route + "/export", headers=headers, json=export | change).status_code
                == 422
            )
        old_route = route.replace("/encoded-labels", "")
        assert client.post(old_route + "/source", headers=headers, json=query).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
    assert (
        filesystem(native.storage.directory) == before
        and not native.storage.receipts()
        and not native.plans
    )
