"""Authored factory saved identities, local I/O copies and an owned UDP peer."""

import gzip
import struct
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, TagList, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_inputs import raw_property
from bms_tool.native_runtime_io import compile_io, effective_source
from bms_tool.native_runtime_io_transfer import IOApply, IOReadback, IOReview, RuntimeIOOperations

from .test_controller_application import encoded, native_record
from .test_native_applications import native_link as native_link


def source(*, compressed=False, saved_id=5136, input_slot=1, output_slot=4):
    def record(cid, instance, props):
        return native_record(cid, instance, [(k, encoded(v)) for k, v in props])

    root = record(
        194,
        1,
        [
            (32527, CharacterString("8-1")),
            (75, ObjectIdentifier((8, 1))),
            (2390, CharacterString("CVM")),
            (70, CharacterString("M4-CVM03050-0")),
            (4128, Unsigned(66)),
            (4129, Unsigned(65)),
        ],
    )
    inp = record(
        240,
        1019,
        [
            (32527, CharacterString("8-1/0_1019")),
            (75, ObjectIdentifier((0, 1019))),
            (2390, CharacterString("DA-T")),
            (31, CharacterString(f"UI IN{input_slot}")),
            (519, Unsigned(input_slot)),
        ],
    )
    out = record(
        239,
        2045,
        [
            (32527, CharacterString("8-1/4_2045")),
            (75, ObjectIdentifier((4, 2045))),
            (2390, CharacterString("SF-C")),
            (
                31,
                CharacterString(
                    f"CO OUT{output_slot - 3}" if output_slot > 3 else f"BO OUT{output_slot}"
                ),
            ),
            (990, Unsigned(output_slot)),
            (518, Enumerated(0)),
            (65001, CharacterString("keep opaque output field")),
        ],
    )
    footer = record(127, 1, [(65000, CharacterString("preserve complete unknown graph"))])
    records = [root, inp, out, footer]
    app = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, len(records))
    app += b"".join(struct.pack("<H", len(r) + 2) + r for r in records)
    dynamic = ((8 << 22) | saved_id).to_bytes(4, "big")
    dynamic += bytes([header_crc(dynamic) ^ 255])

    def row(pid, datatype, payload, flags):
        body = (
            ((8 << 22) | 1).to_bytes(4, "big")
            + pid.to_bytes(2, "big")
            + bytes([flags, datatype])
            + (194).to_bytes(2, "big")
            + payload
            + b"\x12\x34"
        )
        return (len(body) + 2).to_bytes(2, "big") + body

    static = row(75, 12, b"\x00\x00", 0x6F)
    for pid, text in [(2390, "Authored controller"), (70, "M4-CVM03050-0")]:
        static += row(
            pid, 7, b"\x1e" + encoded(CharacterString(text)) + b"\x1f" + b"\x00" * 5, 0x4F
        )
    return {3: gzip.compress(app, mtime=0) if compressed else app, 11: static, 12: dynamic}


def identity():
    return {
        "device": "device,5136",
        "vendor-identifier": 5,
        "object-name": "Authored controller",
        "model-name": "M4-CVM03050-0",
    }


def allocation():
    return dict(action="allocate-binary", object_instance=3000002, slot=2, name="SF-S")


def movement():
    return dict(action="binary-output-terminal", object_instance=2045, slot=1, expected_slot=4)


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("edit", [allocation(), movement()])
def test_saved_effective_identity_and_exact_unrelated_record_preservation(compressed, edit):
    files = source(compressed=compressed)
    before, proof = effective_source(files, identity())
    assert proof["factory_identity_materialized"] is True
    assert before.instance == 5136 and before.summary()["name"] == "Authored controller"
    output, report = compile_io(files, identity(), edit)
    after = MoiIdentity(output)
    assert report["all_other_effective_records_preserved"] and not report["graph_wires_changed"]
    if edit["action"] == "allocate-binary":
        assert len(after.records) == 5
        added = after.records[-1]
        assert added["class_id"] == 242
        assert after.reader.scalar(added, 75) == "binary-input,3000002"
        assert after.reader.scalar(added, 519) == 2 and after.reader.scalar(added, 84) == 0
        assert after.reader.scalar(added, 2390) == "SF-S"
    else:
        assert len(after.records) == 4
        changed = after.records[2]
        assert (
            after.reader.scalar(changed, 990) == 1 and after.reader.scalar(changed, 31) == "BO OUT1"
        )
        assert after.reader.scalar(changed, 65001) == "keep opaque output field"
    assert files[3] == source(compressed=compressed)[3]


@pytest.mark.parametrize(
    "kind",
    [
        "crc",
        "identity",
        "name",
        "missing-saved-identity",
        "occupied-input",
        "occupied-output",
        "wrong-old-slot",
        "unknown-model",
    ],
)
def test_unsupported_or_stale_sources_have_no_copy_authority(kind):
    files = source()
    actual = identity()
    edit = allocation()
    if kind == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif kind == "identity":
        actual["device"] = "device,5137"
    elif kind == "name":
        actual["object-name"] = "Different"
    elif kind == "missing-saved-identity":
        files[11] = files[11][16:]
        files[12] = b"\x00"
    elif kind == "occupied-input":
        edit["slot"] = 1
    elif kind == "occupied-output":
        files = source(output_slot=1)
        edit = movement()
    elif kind == "wrong-old-slot":
        edit = movement()
        edit["expected_slot"] = 5
    elif kind == "unknown-model":
        actual["model-name"] = "OTHER"
    with pytest.raises(ValueError):
        compile_io(files, actual, edit)


def test_object_identifier_storage_does_not_relax_ordinary_identity_preservation():
    files = source()
    with pytest.raises(ValueError, match="header|identity"):
        ParameterApplication(files[3], files[11], files[12]).compile()
    effective, _ = effective_source(files, identity())
    output, _ = ParameterApplication(effective.source, files[11], files[12]).compile()
    assert MoiIdentity(output).instance == 5136


@pytest.fixture
async def io_link(native_link, monkeypatch):
    peer, _, _, native, target = native_link
    files = source()
    app, _ = effective_source(files, identity())
    peer.files = {**files, 3: app.source}
    peer.selector_value = 1
    peer.selector_label = "Custom Application"
    peer.metadata["model-name"] = "M4-CVM03050-0"
    peer.metadata["firmware-revision"] = "10.0.0.2125"
    peer.next_input = 3000002
    peer.io_fault = ""
    original = peer.do_ReadPropertyRequest

    async def read(self, request):
        oid, pid = request.objectIdentifier, int(request.propertyIdentifier)
        if int(oid[0]) == 8 and pid == 32527:
            value = Any(CharacterString("8-1"))
        elif oid == ObjectIdentifier("multi-state-value,1000"):
            if pid == 77:
                value = Any(CharacterString("8-1/Preloaded App Loader.App Selector"))
            elif pid == 85:
                value = Any(Unsigned(self.selector_value))
            elif pid == 110 and request.propertyArrayIndex == 1:
                value = Any(CharacterString(self.selector_label))
            else:
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
        elif int(oid[0]) == 8 and pid == 787:
            value = Any(Unsigned(self.next_input))
        elif int(oid[0]) in (3, 4):
            app, _ = effective_source(
                self.files, {"device": f"device,{self.instance}", **self.metadata}
            )
            record = next((r for r in app.records if app.reader.scalar(r, 75) == str(oid)), None)
            if record is None:
                if self.io_fault == "silent-absence":
                    return
                if self.io_fault == "property-error":
                    raise ExecutionError(errorClass="property", errorCode="unknown-property")
                raise ExecutionError(errorClass="object", errorCode="unknown-object")
            raw = raw_property(app, record, 2390 if pid == 77 else pid)
            if raw is None:
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
            value = Any(TagList.decode(PDUData(raw[:-1])))
            if self.io_fault == "wrong-publication" and pid in (519, 990):
                value = Any(Unsigned(3))
        else:
            return await original(request)
        await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=oid,
                propertyIdentifier=request.propertyIdentifier,
                propertyArrayIndex=request.propertyArrayIndex,
                propertyValue=value,
            )
        )

    peer.do_ReadPropertyRequest = types.MethodType(read, peer)
    monkeypatch.setattr("bms_tool.native_runtime_io_transfer.RESTORE_PREPARATION_SECONDS", 0.03)
    yield peer, native, target, RuntimeIOOperations(native)


async def review(link, edit=None):
    peer, native, target, service = link
    capture = await native.capture(**target, operation_id="capture-runtime-io")
    request = IOReview(
        **target,
        operation_id="review-runtime-io",
        capture_id=capture["id"],
        snapshot_sha256=capture["snapshot_evidence_sha256"],
        edit=edit or allocation(),
    )
    return request, await service.preview(request)


def confirm(plan, **changes):
    return IOApply(
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        local_io_testing_confirmed=True,
        application_transfer_confirmed=True,
        **changes,
    )


@pytest.mark.parametrize("edit", [allocation(), movement()])
async def test_owned_udp_transfer_saved_identity_and_independent_io_publication(io_link, edit):
    peer, native, target, service = io_link
    _, plan = await review(io_link, edit)
    result = await service.apply(confirm(plan))
    assert result["result"]["status"] == "verified", result["result"]
    assert not result["pending"]
    assert len([e for e in peer.events if e == ("state", "start-restore")]) == 1
    with pytest.raises(ValueError, match="consumed"):
        await service.apply(confirm(plan))


@pytest.mark.parametrize("fault", ["silent-absence", "property-error"])
async def test_non_object_error_does_not_prove_absence(io_link, fault):
    peer, _, _, _ = io_link
    peer.io_fault = fault
    with pytest.raises(ValueError, match="presence/absence"):
        await review(io_link)
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_saved_setting_change_rejects_stale_review_before_restore(io_link):
    peer, _, _, service = io_link
    _, plan = await review(io_link)
    peer.files[12] = bytes([peer.files[12][0] ^ 1]) + peer.files[12][1:]
    result = await service.apply(confirm(plan))
    assert result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_wrong_publication_retains_uncertainty_readback_never_replays(io_link):
    peer, native, target, service = io_link
    _, plan = await review(io_link)
    peer.io_fault = "wrong-publication"
    result = await service.apply(confirm(plan))
    assert result["result"]["status"] == "unknown" and result["pending"], result
    count = len([e for e in peer.events if e[0] == "write"])
    peer.io_fault = ""
    checked = await service.readback(
        IOReadback(**target, operation_id="readback-runtime-io", receipt_id=result["intent"]["id"])
    )
    assert not checked["pending"] and checked["latest_readback"]["status"] == "verified"
    assert len([e for e in peer.events if e[0] == "write"]) == count


async def test_insufficient_file_capacity_cannot_start_restore(io_link):
    peer, _, _, service = io_link
    _, plan = await review(io_link)
    peer.application_capacity = 100
    result = await service.apply(confirm(plan))
    assert result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


def test_runtime_io_http_source_is_local_and_apply_requires_strict_confirmations(tmp_path):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path)
    native = app.state.native_applications
    target = {"address": "127.0.0.1:47999", "router": None, "dnet": None}
    capture = native.storage.save(
        {
            "target": target,
            "device": "device,5136",
            "identity": identity(),
            "connector_config": {},
            "source_identity_matches": False,
        },
        source(),
    )
    body = {
        **target,
        "device": "device,5136",
        "operation_id": "authored-io-source",
        "capture_id": capture["id"],
        "snapshot_sha256": capture["evidence_sha256"],
        "edit": allocation(),
    }
    base = "/api/bacnet/controller/native-application/runtime-io"
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(base + "/source", json=body).status_code == 403
        response = client.post(base + "/source", json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert (
            response.json()["controller_queries"] is response.json()["controller_writes"] is False
        )
        assert "token" not in response.json()
        r = client.post(
            base + "/apply",
            headers=headers,
            json={
                "token": "a" * 32,
                "review_sha256": "a" * 64,
                "local_io_testing_confirmed": "true",
                "application_transfer_confirmed": True,
            },
        )
        assert r.status_code == 422
        assert not native.storage.receipts()
        assert client.get("/api/session").json()["field_network_open"] is False


def with_sa_mapping(files, *, local_kind=2, duplicate=False):
    from bacpypes3.primitivedata import ClosingTag, OpeningTag, TagList
    from bms_tool.native_inputs import archive

    app = MoiIdentity(files[3])
    mapped = ObjectIdentifier((local_kind, 777))
    owner = native_record(
        527, 777, [(32527, encoded(CharacterString("8-1/network-value"))), (75, encoded(mapped))]
    )
    group = [
        OpeningTag(3),
        *mapped.encode(),
        OpeningTag(4),
        *ObjectIdentifier((0, 0)).encode(),
        ClosingTag(4),
        ClosingTag(3),
    ]
    packed = bytes(TagList(group + (group if duplicate else [])).encode().pduData)
    device = native_record(
        910,
        999,
        [
            (32527, encoded(CharacterString("8-1/307_2.910_999"))),
            (75, encoded(ObjectIdentifier((910, 999)))),
            (1248, packed),
        ],
    )
    records = [app.data[r["offset"] : r["end_offset"]] for r in app.records] + [owner, device]
    return {**files, 3: archive(app, records)}


def test_network_sensor_maps_preserve_remote_ai_references_without_claiming_physical_io():
    files = with_sa_mapping(source())
    out, proof = compile_io(files, identity(), allocation())
    assert len(MoiIdentity(out).records) == 7
    assert proof["network_only_sa_devices"][0]["mapped_network_values"] == ["analog-value,777"]


@pytest.mark.parametrize("options", [{"local_kind": 0}, {"local_kind": 3}, {"duplicate": True}])
def test_sa_physical_or_ambiguous_maps_have_no_local_io_authority(options):
    with pytest.raises(ValueError, match="SA map"):
        compile_io(with_sa_mapping(source(), **options), identity(), allocation())


def test_runtime_configuration_guard_ignores_only_documented_typed_outputs():
    from bacpypes3.primitivedata import Real
    from bms_tool.native_inputs import archive, replace_properties
    from bms_tool.native_runtime_io import configuration_guard

    app, _ = effective_source(source(), identity())
    flow = native_record(
        570,
        599,
        [
            (32527, encoded(CharacterString("8-1/570_599"))),
            (75, encoded(ObjectIdentifier((570, 599)))),
            (3506, encoded(Real(0.1))),
            (65000, encoded(Real(2.5))),
        ],
    )
    original = MoiIdentity(
        archive(app, [app.data[r["offset"] : r["end_offset"]] for r in app.records] + [flow])
    )
    record = original.records[-1]

    def changed(pid, value):
        raw = replace_properties(original, record, {pid: bytes(value.encode().encode().pduData)})
        return MoiIdentity(
            archive(
                original,
                [original.data[r["offset"] : r["end_offset"]] for r in original.records[:-1]]
                + [raw],
            )
        )

    assert configuration_guard(original) == configuration_guard(changed(3506, Real(0.2)))
    assert configuration_guard(original) != configuration_guard(changed(65000, Real(3.5)))
    with pytest.raises(ValueError, match="finite Real"):
        configuration_guard(changed(3506, Unsigned(3)))


@pytest.mark.parametrize("change", ["selector", "custom-label", "firmware", "factory-source"])
async def test_unqualified_or_factory_bank_cannot_gain_live_review(io_link, change):
    peer, _, _, _ = io_link
    if change == "selector":
        peer.selector_value = 15
    elif change == "custom-label":
        peer.selector_label = "Different application"
    elif change == "firmware":
        peer.metadata["firmware-revision"] = "unqualified"
    else:
        peer.files = source()
    with pytest.raises(ValueError, match="custom|firmware|offline"):
        await review(io_link)
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_bank_change_after_review_cannot_start_restore(io_link):
    peer, _, _, service = io_link
    _, plan = await review(io_link)
    peer.selector_value = 15
    result = await service.apply(confirm(plan))
    assert result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize("change", ["expired", "interface", "credentials", "digest"])
async def test_invalidated_io_reviews_cannot_start_restore(io_link, change):
    peer, native, _, service = io_link
    _, plan = await review(io_link)
    if change == "expired":
        service.plans[plan["token"]]["expires"] = 0
    elif change == "interface":
        native.bacnet.config["router"] = "127.0.0.2"
    elif change == "credentials":
        native.credentials.set(backup="different", restore="different")
    else:
        plan["review_sha256"] = "0" * 64
    if change in ("expired", "digest"):
        with pytest.raises(ValueError, match="expired|changed|consumed"):
            await service.apply(confirm(plan))
    else:
        result = await service.apply(confirm(plan))
        assert result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


def test_new_input_description_is_caller_supplied_and_not_equipment_specific():
    edit = {**allocation(), "name": "Pump-Proof", "description": "Independent current contact"}
    output, _ = compile_io(source(), identity(), edit)
    app = MoiIdentity(output)
    assert app.reader.scalar(app.records[-1], 28) == edit["description"]
    default, _ = compile_io(source(), identity(), allocation())
    app = MoiIdentity(default)
    assert app.reader.scalar(app.records[-1], 28) == ""
