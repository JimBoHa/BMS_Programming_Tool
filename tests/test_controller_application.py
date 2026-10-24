"""Authored native application bytes and actual UDP File transfers; no site data."""

import gzip

import pytest
from bacpypes3.errors import ExecutionError
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real, Unsigned
from bms_tool.controller_application import ControllerApplication
from bms_tool.moi_application import MoiApplication

from .test_bacnet_files import link as link


def encoded(value):
    return bytes(value.encode().encode().pduData)


def native_record(cid, instance, props):
    body = bytearray()
    for pid, value in props:
        raw = pid.to_bytes(max(1, (pid.bit_length() + 7) // 8), "big")
        body.extend(bytes([8 | len(raw)]) + raw + b"\x2e" + value + b"\x2f")
    return (
        cid.to_bytes(2, "little")
        + b"\x02\x00\x0e\x1c"
        + ((cid << 22) | instance).to_bytes(4, "big")
        + b"\x0f\x1e"
        + body
        + b"\x1f"
    )


def authored_application(*, root="site/575_1", target=1, order=(0, 1), identities=True):
    blocks = [(526, "analog-value", 10), (527, "analog-value", 11)]
    root_record = native_record(
        575,
        1,
        [
            (32527, encoded(CharacterString(root))),
            (75, encoded(ObjectIdentifier((575, 1)))),
            (2390, encoded(CharacterString("Authored field sequence"))),
            (
                3375,
                b"".join(
                    encoded(ObjectIdentifier((kind, instance))) for _, kind, instance in blocks
                ),
            ),
            (3117, b"".join(encoded(Unsigned(index)) for index in order)),
            (
                3118,
                b"\x3e"
                + b"".join(encoded(Unsigned(value)) for value in [0, 85, target, 7000])
                + b"\x3f",
            ),
        ],
    )
    records = [root_record]
    for index, (cid, kind, instance) in enumerate(blocks):
        records.append(
            native_record(
                cid,
                instance,
                [
                    (32527, encoded(CharacterString(f"{root}.2_{instance}"))),
                    (
                        75,
                        encoded(ObjectIdentifier((kind, instance if identities else instance + 3))),
                    ),
                    (2390, encoded(CharacterString(f"Actual native block {index + 1}"))),
                    (3113, encoded(Real(23.5 + index))),
                    (65000, b"\x4e\x21\x01\x4f"),
                ],
            )
        )
    return gzip.compress(b"\x02\x00MOI\x00" + b"".join(records), mtime=0)


@pytest.mark.parametrize("root", ["alpha/575_1", "unlisted-family/575_1", "other-site/575_1"])
def test_real_recorded_fields_supply_graph_without_controller_model(root):
    app = MoiApplication(authored_application(root=root))
    summary = app.summary()
    assert summary["record_count"] == 3 and not summary["errors"]
    assert summary["capabilities"] == {
        "logic_read": True,
        "logic_write": False,
        "native_compile": False,
    }
    graph = app.diagram(root)
    assert graph["read_only"] and not graph["native_layout"]
    assert [block["object"] for block in graph["blocks"]] == ["analog-value,10", "analog-value,11"]
    assert graph["connections"] == [
        {
            "index": 0,
            "source_ref": root + ".2_10",
            "source_port": 85,
            "target_ref": root + ".2_11",
            "target_port": 7000,
        }
    ]
    props = {prop["id"]: prop for prop in graph["blocks"][0]["properties"]}
    assert props[3113]["scalar"]["value"] == 23.5
    assert props[65000]["scalar"] is None and len(props[65000]["encoded_sha256"]) == 64


@pytest.mark.parametrize("changes", [{"target": 8}, {"order": (0, 0)}, {"identities": False}])
def test_unrecognized_graph_identity_or_structure_never_becomes_a_guessed_diagram(changes):
    app = MoiApplication(authored_application(**changes))
    assert app.summary()["diagrams"] == []
    assert app.summary()["errors"] and not app.summary()["capabilities"]["logic_read"]


@pytest.mark.parametrize(
    "raw",
    [
        b"not an application",
        gzip.compress(b"wrong format"),
        authored_application() + b"trailing",
        gzip.compress(b"x" * (8 * 1024 * 1024 + 1)),
    ],
)
def test_bad_or_excessive_native_files_are_rejected(raw):
    with pytest.raises(ValueError):
        MoiApplication(raw)


async def test_application_is_acquired_from_actual_file_and_cannot_be_reused_for_another_target(
    link,
):
    server, connector, files, target = link
    server.payload = authored_application()
    server.stream.fileSize = len(server.payload)
    server.stream.fileType = ".moi"
    server.stream.objectName = "Controller/Archive"
    service = ControllerApplication(connector, connector.store, files)
    result = await service.read_application(target)
    assert result["status"] == "read" and result["identity_verified"]
    assert result["application"]["diagrams"][0]["name"] == "Authored field sequence"
    capture = result["receipt"]["id"]
    assert service.captures(target)[0]["id"] == capture
    graph = service.diagram({**target, "capture_id": capture, "ref": "site/575_1"})
    assert graph["diagram"]["blocks"][0]["name"] == "Actual native block 1"
    assert service.capture({**target, "capture_id": capture})["identity_verified"] is False
    wrong = {**target, "address": "127.0.0.1:49999", "capture_id": capture}
    with pytest.raises(ValueError, match="different controller"):
        service.capture(wrong)
    with pytest.raises(ValueError, match="different controller"):
        service.diagram({**wrong, "ref": "site/575_1"})
    assert server.atomic_requests and not connector.app._requests


async def test_application_file_discovery_works_when_optional_configuration_files_is_absent(link):
    server, connector, files, target = link
    server.payload = authored_application()
    server.stream.fileSize = len(server.payload)
    server.stream.fileType = ".moi"
    original = server.do_ReadPropertyRequest

    async def without_optional_property(request):
        if str(request.propertyIdentifier) == "configuration-files":
            raise ExecutionError(errorClass="property", errorCode="unknown-property")
        await original(request)

    server.do_ReadPropertyRequest = without_optional_property
    service = ControllerApplication(connector, connector.store, files)
    result = await service.read_application(target)
    assert result["application"]["capabilities"]["logic_read"]
    assert result["receipt"]["discovery_source"] == "object-list"
    assert result["receipt"]["configuration_files_supported"] is False
    assert result["receipt"]["advertised_files"] == ["file,31", "file,32"]
