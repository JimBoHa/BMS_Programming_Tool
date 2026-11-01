"""Authored full records, independent expected bytes and actual UDP acquisition."""

import gzip
import hashlib
import struct

import httpx
import pytest
from bacpypes3.primitivedata import CharacterString, Double, ObjectIdentifier, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.controller_application import ControllerApplication
from bms_tool.moi_application import MoiApplication
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_signal_defaults import MoiSignalDefaults

from .test_bacnet_files import link as link
from .test_controller_application import authored_application, encoded, native_record


def source(*, compressed=False, extended=False, cid=526, default=None, duplicate=False):
    # The existing independently authored graph supplies two signal records and
    # opaque structured properties. Add a Device root and actual length framing.
    legacy = MoiApplication(authored_application())
    records = [
        native_record(
            194,
            4190090,
            [
                (32527, encoded(CharacterString("site"))),
                (75, encoded(ObjectIdentifier((8, 4190090)))),
                (70, encoded(CharacterString("UNLISTED-DEFAULT-COPY-FAMILY"))),
                (2390, encoded(CharacterString("Authored default controller"))),
            ],
        )
    ]
    for record in legacy.records.values():
        if record["class_id"] == 526:
            records.append(
                native_record(
                    cid,
                    10,
                    [
                        (32527, encoded(CharacterString("site/575_1.2_10"))),
                        (75, encoded(ObjectIdentifier(("analog-value", 10)))),
                        (2390, encoded(CharacterString("Actual native block 1"))),
                        (3113, encoded(Real(23.5) if default is None else default)),
                        (65000, b"\x4e\x21\x01\x4f"),
                    ],
                )
            )
        else:
            records.append(legacy.data[record["offset"] : record["end_offset"]])
    if duplicate:
        records.append(records[2])
    records.append(native_record(127, 1, [(65001, b"\x4e\x21\x01\x4f")]))
    data = bytearray(struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, len(records)))
    for index, record in enumerate(records):
        data.extend(
            b"\x00\x00" + struct.pack("<I", len(record) + 6)
            if extended or index == len(records) - 1
            else struct.pack("<H", len(record) + 2)
        )
        data.extend(record)
    return gzip.compress(data, mtime=0) if compressed else bytes(data)


def request(editor, value="31.25", ref="site/575_1.2_10"):
    _, prop = editor.candidates[ref]
    return {
        "source_sha256": editor.editor.source_sha256,
        "record_ref": ref,
        "encoded_sha256": prop["encoded_sha256"],
        "value_text": value,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("ref", ["site/575_1.2_10", "site/575_1.2_11"])
def test_only_existing_four_real_bytes_change(compressed, extended, ref):
    original = source(compressed=compressed, extended=extended)
    editor = MoiSignalDefaults(original)
    q = request(editor, ref=ref)
    plan = editor.preview(**q)
    output, report = editor.export(**q, plan_sha256=plan["plan_sha256"])
    parsed = MoiIdentity(output)
    offset = plan["native_byte_offset"]
    # Independent BACnet encoder supplies the expected Real payload.
    expected = bytearray(editor.editor.data)
    expected[offset : offset + 4] = encoded(Real(31.25))[1:]
    assert parsed.data == bytes(expected)
    assert parsed.instance == 4190090 and len(parsed.records) == 5
    assert parsed.reader.scalar(parsed.root, 70) == "UNLISTED-DEFAULT-COPY-FAMILY"
    assert parsed.reader.records[ref]["properties"][3113]["scalar"]["value"] == 31.25
    assert (
        not report["controller_write"]
        and report["output_sha256"] == hashlib.sha256(output).hexdigest()
    )
    assert editor.editor.source == original
    for old, new in zip(editor.editor.records, parsed.records, strict=True):
        for pid, prop in old["properties"].items():
            if old is editor.candidates[ref][0] and pid == 3113:
                continue
            assert prop["encoded_sha256"] == new["properties"][pid]["encoded_sha256"]
    if compressed:
        assert output[:10] == original[:10] and gzip.decompress(output) == bytes(expected)


def test_noop_gzip_is_exact_and_review_is_source_property_and_value_bound():
    editor = MoiSignalDefaults(source(compressed=True))
    q = request(editor, "23.5")
    plan = editor.preview(**q)
    assert editor.export(**q, plan_sha256=plan["plan_sha256"])[0] == editor.editor.source
    for field, changed in [
        ("source_sha256", "0" * 64),
        ("encoded_sha256", "0" * 64),
        ("record_ref", "site/575_1"),
    ]:
        with pytest.raises(ValueError):
            editor.preview(**{**q, field: changed})
    with pytest.raises(ValueError, match="review changed"):
        editor.export(**{**q, "value_text": "25"}, plan_sha256=plan["plan_sha256"])


@pytest.mark.parametrize(
    "text",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        "1e400",
        "3.5e38",
        "1e-400",
        "1e-46",
        "1e-99999999999999999999999999",
        "0e99999999999999999999999999",
        "",
        "0x10",
        "1_000",
        "1/2",
        "1" * 129,
    ],
)
def test_bad_nonfinite_overflow_and_nonzero_underflow_rejected(text):
    editor = MoiSignalDefaults(source())
    with pytest.raises(ValueError):
        editor.preview(**request(editor, text))


def test_rounding_and_signed_zero_have_explicit_review_bits():
    editor = MoiSignalDefaults(source())
    plan = editor.preview(**request(editor, "0.1"))
    assert plan["after_bits"] == "3dcccccd" and plan["stored_value"] == 0.10000000149011612
    assert plan["decimal_precision_changed"]
    assert not editor.preview(**request(editor, "31.25"))["decimal_precision_changed"]
    negative = editor.preview(**request(editor, "-0"))
    assert negative["after_bits"] == "80000000"
    output, _ = editor.export(**request(editor, "-0"), plan_sha256=negative["plan_sha256"])
    assert (
        output[negative["native_byte_offset"] : negative["native_byte_offset"] + 4]
        == b"\x80\x00\x00\x00"
    )


@pytest.mark.parametrize(
    "changes", [{"cid": 530}, {"default": Unsigned(23)}, {"default": Double(23.5)}]
)
def test_other_class_or_datatype_not_editable(changes):
    editor = MoiSignalDefaults(source(**changes))
    assert "site/575_1.2_10" not in editor.candidates
    assert editor.capabilities()["candidate_count"] == 1


@pytest.mark.parametrize(
    "raw", [authored_application(), source(duplicate=True), source() + b"trailing"]
)
def test_legacy_ambiguous_and_unframed_sources_rejected(raw):
    with pytest.raises(ValueError):
        MoiSignalDefaults(raw)


async def test_actual_udp_capture_review_and_http_copy_never_dispatch_field_requests(
    link, tmp_path
):
    peer, connector, files, target = link
    observed_apdus = []
    original_indication = peer.indication

    async def observe_every_request(apdu):
        observed_apdus.append(type(apdu).__name__)
        await original_indication(apdu)

    peer.indication = observe_every_request
    peer.payload = source(compressed=True)
    peer.stream.fileSize, peer.stream.fileType = len(peer.payload), ".moi"
    service = ControllerApplication(connector, connector.store, files)
    captured = await service.read_application(target)
    assert captured["signal_default_copy"]["candidate_count"] == 2
    capture = captured["receipt"]["id"]
    q = {**target, "capture_id": capture, **request(MoiSignalDefaults(peer.payload))}
    original_requests = list(peer.all_requests)
    original_apdus = list(observed_apdus)
    assert "AtomicReadFileRequest" in original_apdus
    app = create_app(tmp_path)
    app.state.controller_application.bacnet = connector
    app.state.controller_application.files = files
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://localhost"
    ) as client:
        base = "/api/bacnet/controller/application/signal-default/"
        headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
        assert (await client.post(base + "preview", json=q)).status_code == 403
        reviewed = await client.post(base + "preview", json=q, headers=headers)
        assert reviewed.status_code == 200, reviewed.text
        review = reviewed.json()
        assert not review["field_actions"] and not review["controller_write"]
        body = {**q, "review_sha256": review["review_sha256"]}
        for changes in [
            {"address": "127.0.0.1:49999"},
            {"source_sha256": "0" * 64},
            {"review_sha256": "0" * 64},
            {"value_text": "22"},
        ]:
            assert (
                await client.post(base + "export", json={**body, **changes}, headers=headers)
            ).status_code == 422
        assert (
            await client.post(
                base + "preview", json={**q, "value_text": "1" * 129}, headers=headers
            )
        ).status_code == 422
        saved = await client.post(base + "export", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.headers["x-source-sha256"] == q["source_sha256"]
        assert saved.headers["x-output-sha256"] == hashlib.sha256(saved.content).hexdigest()
        assert saved.headers["x-edit-review-sha256"] == body["review_sha256"]
        assert (
            MoiSignalDefaults(saved.content).candidates[q["record_ref"]][1]["scalar"]["value"]
            == 31.25
        )
        connector.config = {**connector.config, "router": "127.0.0.1:49999", "dnet": 42}
        assert (await client.post(base + "export", json=body, headers=headers)).status_code == 422
    assert files.capture_data(capture)[1] == peer.payload
    assert peer.all_requests == original_requests and not connector.app._requests
    assert observed_apdus == original_apdus
