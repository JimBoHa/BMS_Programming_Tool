"""Authored unknown-model point names, opaque records, saved values and owned UDP."""

import copy
import gzip
import struct
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_point_names import (
    PointNameCompiler,
    PointNameEdit,
    verify_point_name_preservation,
)

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401


def point_files(*, compressed=True, encoding=0, padding=0, duplicate=False):
    archive, static, dynamic = parameters_source(compressed=False)
    records = []
    for instance, name in [(101, "Authored input"), (102, "Other point")]:
        records.append(
            native_record(
                240,
                instance,
                [
                    (32527, encoded(CharacterString(f"controller/0-{instance}"))),
                    (75, encoded(ObjectIdentifier((0, 101 if duplicate else instance)))),
                    (2390, encoded(CharacterString(name, _encoding=encoding))),
                    (518, encoded(Unsigned(3))),
                    (65000, encoded(CharacterString("x" * padding))),
                ],
            )
        )
    data = bytearray(archive)
    struct.pack_into("<I", data, 10, struct.unpack_from("<I", data, 10)[0] + len(records))
    data.extend(b"".join(struct.pack("<H", len(r) + 2) + r for r in records))
    return {
        3: gzip.compress(bytes(data), mtime=0) if compressed else bytes(data),
        11: static,
        12: dynamic,
    }


def edit_for(files, *, name="Changed input"):
    field = next(
        f for f in PointNameCompiler(files).fields() if f["object_id"] == "analog-input,101"
    )
    return {k: field[k] for k in ("object_id", "record_ref", "encoded_sha256")} | {"new_name": name}


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("encoding", [0, 3, 4, 5])
@pytest.mark.parametrize("name", ["Short", "A much longer reviewed input name"])
def test_name_preserves_all_other_record_bytes_and_effective_settings(compressed, encoding, name):
    files = point_files(compressed=compressed, encoding=encoding)
    edit = edit_for(files, name=name)
    output, report = PointNameCompiler(files).compile(edit)
    assert report["selected_edit"]["before"] == "Authored input"
    assert report["selected_edit"]["after"] == name
    assert report["parameter_merge"]["matched_parameters"] == 7
    after = {**files, 3: output}
    proof = verify_point_name_preservation(files, after, edit)
    assert proof["application_identical_except_point_name"]
    assert proof["saved_application_parameters_verified"] == 7
    fields = PointNameCompiler(after).fields()
    assert fields[0]["name"] == name and fields[1]["name"] == "Other point"
    assert MoiIdentity(output).instance == 5136
    # A subsequent, fresh review can restore just the old name while keeping
    # the previously merged saved settings current.
    restored, _ = PointNameCompiler(after).compile(edit_for(after, name="Authored input"))
    assert PointNameCompiler({**after, 3: restored}).fields()[0]["name"] == "Authored input"


def test_unicode_name_and_record_growth_to_extended_framing():
    files = point_files(padding=65400)
    edit = edit_for(files, name="Témperature " + "z" * 110)
    output, report = PointNameCompiler(files).compile(edit)
    assert report["other_merged_bytes_preserved"]
    assert len(MoiIdentity(output).records) == len(MoiIdentity(files[3]).records)
    assert PointNameCompiler({**files, 3: output}).fields()[0]["name"] == edit["new_name"]


@pytest.mark.parametrize("replacement", ["", " padded ", "bad\nname", "x" * 129])
def test_invalid_names_are_rejected(replacement):
    with pytest.raises(ValueError):
        PointNameEdit(**edit_for(point_files(), name=replacement))


def test_stale_name_reference_wrong_point_and_duplicates_are_rejected():
    files = point_files()
    edit = edit_for(files)
    for updates in [
        {"encoded_sha256": "f" * 64},
        {"record_ref": "other/ref"},
        {"object_id": "analog-input,999"},
        {"new_name": "Other point"},
        {"object_id": "device,5136"},
    ]:
        with pytest.raises(ValueError):
            PointNameCompiler(files).compile({**edit, **updates})
    with pytest.raises(ValueError, match="Duplicate"):
        PointNameCompiler(point_files(duplicate=True))


def test_other_bytes_or_live_saved_settings_cannot_hide_in_name_verification():
    files = point_files()
    edit = edit_for(files)
    output, _ = PointNameCompiler(files).compile(edit)
    after = {
        **files,
        3: gzip.compress(
            gzip.decompress(output).replace(b"opaque footer", b"unsafe footer"), mtime=0
        ),
    }
    with pytest.raises(ValueError, match="readback differs"):
        verify_point_name_preservation(files, after, edit)
    after = {**files, 3: output, 11: files[11].replace(b"saved", b"other")}
    with pytest.raises(ValueError, match="saved parameter differs"):
        verify_point_name_preservation(files, after, edit)


def attach_point_reads(peer, *, published_old=False):
    original = peer.do_ReadPropertyRequest

    async def read(self, request):
        if (
            int(request.objectIdentifier[0]) == 0
            and str(request.propertyIdentifier) == "object-name"
        ):
            field = next(
                p
                for p in PointNameCompiler(self.files).fields()
                if p["object_id"] == str(request.objectIdentifier)
            )
            await self.response(
                ReadPropertyACK(
                    context=request,
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(
                        CharacterString("Authored input" if published_old else field["name"])
                    ),
                )
            )
        else:
            await original(request)

    peer.do_ReadPropertyRequest = types.MethodType(read, peer)


async def name_review(native_link, *, published_old=False):
    peer, _, _, service, target = native_link
    peer.files = point_files()
    attach_point_reads(peer, published_old=published_old)
    capture = await service.capture(**target, operation_id="point-name-capture")
    source_args = {
        **target,
        "capture_id": capture["id"],
        "snapshot_sha256": capture["snapshot_evidence_sha256"],
    }
    source = service.point_name_source(**source_args)
    assert source["controller_queries"] is False
    plan = await service.preview_point_name(
        **source_args, **edit_for(peer.files), operation_id="point-name-preview"
    )
    return capture, plan


def apply_args(plan):
    return {
        "operation_id": "point-name-apply",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "point_name_confirmed": True,
        "application_transfer_confirmed": True,
    }


async def test_point_name_transfer_readback_and_identity_preservation_use_owned_udp(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await name_review(native_link)
    original = copy.deepcopy(peer.files)
    result = await service.apply_point_name(**apply_args(plan))
    assert result["result"]["status"] == "verified", result
    assert result["result"]["published_point_name"] == "Changed input"
    assert not result["pending"] and result["result"]["preservation"]["identity_unchanged"]
    assert peer.instance == 5136 and peer.metadata["object-name"] == "Authored controller"
    assert peer.files[11] == original[11] and peer.files[12] == original[12]
    count = peer.events.count(("state", "start-restore"))
    read = await service.reconcile(
        operation_id="point-name-readback", receipt_id=result["intent"]["id"]
    )
    assert read["latest_readback"]["status"] == "verified"
    assert peer.events.count(("state", "start-restore")) == count == 1
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_point_name(**apply_args(plan))


async def test_published_point_name_must_match_even_when_native_bytes_match(native_link):
    _, _, _, service, _ = native_link
    _, plan = await name_review(native_link, published_old=True)
    result = await service.apply_point_name(**apply_args(plan))
    assert result["pending"] and result["result"]["status"] == "unknown"
    assert result["result"]["published_point_name"] == "Authored input"
    assert "published point name" in result["result"]["error"]


async def test_point_name_review_cannot_be_applied_through_identity_endpoint(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await name_review(native_link)
    with pytest.raises(ValueError, match="different native transfer"):
        await service.apply(
            **{k: v for k, v in apply_args(plan).items() if k != "point_name_confirmed"},
            allocation_confirmed=True,
        )
    assert not any(e[0] == "write" for e in peer.events)


async def test_unconfirmed_point_name_change_is_never_sent(native_link):
    peer, _, _, service, _ = native_link
    _, plan = await name_review(native_link)
    with pytest.raises(ValueError, match="Confirm"):
        await service.apply_point_name(**{**apply_args(plan), "point_name_confirmed": False})
    assert not any(e[0] == "write" for e in peer.events)


def test_point_name_api_rejects_untrusted_requests_without_opening_field_network(tmp_path):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    base = "/api/bacnet/controller/native-application/point-name"
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = {
            "operation_id": "authored-point-name",
            "address": "127.0.0.1:47808",
            "device": "device,5136",
            "capture_id": "a" * 32,
            "snapshot_sha256": "b" * 64,
            **edit_for(point_files()),
        }
        assert client.post(base + "/preview", json=body).status_code == 403
        assert (
            client.post(
                base + "/preview", headers=headers, json={**body, "object_id": "device,5136"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/apply",
                headers=headers,
                json={
                    "operation_id": "authored-name-apply",
                    "token": "a" * 32,
                    "review_sha256": "b" * 64,
                    "point_name_confirmed": 1,
                    "application_transfer_confirmed": True,
                },
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False
