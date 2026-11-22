"""Exercise a primary sequence title on an authored controller and isolated UDP peer."""

import gzip
import struct

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real, Unsigned
from bms_tool.mstp import header_crc
from bms_tool.native_point_names import PRIMARY_SEQUENCE, PointNameCompiler, compile_point_name

from .test_controller_application import encoded, native_record
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_point_names import apply_args
from .test_native_signal_compiler import slot


def sequence_files(*, model="M4-CVM03050-0", refs=("root/575_1",), acs=66):
    def record(cid, instance, properties):
        return native_record(cid, instance, [(p, encoded(v)) for p, v in properties])

    records = [
        record(
            194,
            5136,
            [
                (32527, CharacterString("root")),
                (75, ObjectIdentifier("device,5136")),
                (2390, CharacterString("Authored controller")),
                (70, CharacterString(model)),
                (4128, Unsigned(acs)),
                (4129, Unsigned(65)),
                (900, Real(1)),
            ],
        )
    ]
    for i, ref in enumerate(refs, 1):
        records.append(
            record(
                575,
                i,
                [
                    (75, ObjectIdentifier((575, i))),
                    (32527, CharacterString(ref)),
                    (2390, CharacterString("Authored application")),
                    (65000, Unsigned(123)),
                ],
            )
        )
    data = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 194, 1, len(records))
    data += b"".join(struct.pack("<H", len(r) + 2) + r for r in records)
    saved = struct.pack(">f", 1)
    return {
        3: gzip.compress(data, mtime=0),
        11: slot((8 << 22) + 5136, 194, 900, 4, 0),
        12: saved + bytes([header_crc(saved) ^ 255]),
    }


def edit(files, name):
    compiler = PointNameCompiler(files)
    field = compiler.field(compiler.primary)
    return {k: field[k] for k in ("object_id", "record_ref", "encoded_sha256")} | {"new_name": name}


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "Other"},
        {"acs": 67},
        {"refs": ("root/a.b",)},
        {"refs": ("root/575_1", "root/575_2")},
    ],
)
def test_unsupported_or_ambiguous_sequences_are_never_name_targets(overrides):
    files = sequence_files(**overrides)
    assert PointNameCompiler(files).primary is None
    with pytest.raises(ValueError, match="no supported native name"):
        compile_point_name(files, edit(sequence_files(), "Reviewed sequence"))


def install_title_peer(peer):
    peer.files = sequence_files()
    peer.metadata.update({"model-name": "M4-CVM03050-0", "firmware-revision": "10.0.0.2125"})
    peer.bank = 1
    peer.title_override = None

    def title():
        compiler = PointNameCompiler(peer.files)
        return compiler.field(compiler.primary)["name"]

    peer.application_title = lambda: peer.title_override or title()
    original = peer.do_ReadPropertyRequest

    async def read(req):
        obj, pid = str(req.objectIdentifier), int(req.propertyIdentifier)
        if obj == PRIMARY_SEQUENCE:
            value = {
                75: ObjectIdentifier(PRIMARY_SEQUENCE),
                32527: CharacterString("root/575_1"),
                77: CharacterString(title()),
                2390: CharacterString(title()),
            }[pid]
        elif obj == f"device,{peer.instance}" and pid == 32527:
            value = CharacterString("root")
        elif obj == "multi-state-value,1000":
            value = {
                77: CharacterString("root/Preloaded App Loader.App Selector"),
                85: Unsigned(peer.bank),
                110: CharacterString("Custom Application"),
            }[pid]
        else:
            return await original(req)
        await peer.response(
            ReadPropertyACK(
                context=req,
                objectIdentifier=req.objectIdentifier,
                propertyIdentifier=req.propertyIdentifier,
                propertyArrayIndex=req.propertyArrayIndex,
                propertyValue=Any(value),
            )
        )

    peer.do_ReadPropertyRequest = read


async def setup_peer(link):
    peer, _, _, service, target = link
    install_title_peer(peer)
    capture = await service.capture(**target, operation_id="original-title-snapshot")
    args = {
        **target,
        "capture_id": capture["id"],
        "snapshot_sha256": capture["snapshot_evidence_sha256"],
    }
    source = service.point_name_source(**args)
    assert (
        source["primary_application"]["name"] == "Authored application" and source["points"] == []
    )
    return peer, service, args


async def test_title_is_published_and_recoverable_without_renaming_the_device(native_link):
    peer, service, args = await setup_peer(native_link)
    plan = await service.preview_point_name(
        **args, **edit(peer.files, "Reviewed sequence"), operation_id="review-title"
    )
    result = await service.apply_point_name(**apply_args(plan))
    assert result["result"]["status"] == "verified", result["result"]
    assert (
        result["result"]["published_point_name"] == peer.application_title() == "Reviewed sequence"
    )
    assert peer.metadata["object-name"] == "Authored controller"
    capture = result["result"]["verification_capture_id"]
    meta, _ = service.storage.load(capture)
    prepared = service.point_name_recovery.prepare(
        {
            "capture_id": capture,
            "snapshot_sha256": meta["evidence_sha256"],
            "receipt_id": result["intent"]["id"],
        }
    )
    assert prepared["proposal"]["new_name"] == "Authored application"
    assert peer.events.count(("state", "start-restore")) == 1


@pytest.mark.parametrize("fault", ["bank", "title", "firmware"])
async def test_title_rechecks_publication_and_active_bank_before_transfer(native_link, fault):
    peer, service, args = await setup_peer(native_link)
    plan = await service.preview_point_name(
        **args, **edit(peer.files, "Reviewed sequence"), operation_id="review-title"
    )
    if fault == "bank":
        peer.bank = 2
    elif fault == "title":
        peer.title_override = "Another running program"
    else:
        peer.metadata["firmware-revision"] = "other"
    result = await service.apply_point_name(**apply_args(plan))
    assert result["result"]["status"] == "not_sent"
    assert result["result"]["errors"] and not result["result"]["may_have_applied"]
    assert ("state", "start-restore") not in peer.events
