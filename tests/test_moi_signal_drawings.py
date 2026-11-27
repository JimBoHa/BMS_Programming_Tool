"""Read-only graph resolution with independently authored native signal records."""

import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.controller_application import ControllerApplication
from bms_tool.moi_application import MoiApplication

from .test_bacnet_files import link as link
from .test_controller_application import encoded, native_record

PARENT = "example/575_1"


def member(cid=526, public_type=2, instance=11, leaf="2_88", parent=PARENT, header_instance=None):
    return native_record(
        cid,
        instance if header_instance is None else header_instance,
        [
            (32527, encoded(CharacterString(f"{parent}.{leaf}"))),
            (75, encoded(ObjectIdentifier((public_type, instance)))),
        ],
    )


def application(members, identities=((2, 11), (2, 12)), *, framed=True):
    root = native_record(
        575,
        1,
        [
            (32527, encoded(CharacterString(PARENT))),
            (75, encoded(ObjectIdentifier((575, 1)))),
            (3375, b"".join(encoded(ObjectIdentifier(oid)) for oid in identities)),
            (3117, b"".join(encoded(Unsigned(i)) for i in reversed(range(len(identities))))),
            (3118, b"\x3e" + b"".join(encoded(Unsigned(i)) for i in (0, 85, 1, 7000)) + b"\x3f"),
        ],
    )
    records = [root, *members]
    if not framed:
        return b"\x02\x00MOI\x00" + b"".join(records)
    return struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, len(records)) + b"".join(
        struct.pack("<H", len(record) + 2) + record for record in records
    )


def test_display_uses_sibling_signal_identities_for_all_six_classes():
    classes = [(526, 2), (527, 2), (528, 19), (529, 19), (530, 5), (531, 5)]
    identities = [(kind, i + 11) for i, (_, kind) in enumerate(classes)]
    leaves = [f"{kind}_{88 + i}" for i, (_, kind) in enumerate(classes)]
    source = application(
        [
            member(cid, kind, i + 11, leaf)
            for i, ((cid, kind), leaf) in enumerate(zip(classes, leaves, strict=True))
        ],
        identities,
    )
    app = MoiApplication(source)
    graph = app.display_diagram(PARENT)
    assert app.data == source
    assert graph["read_only"] and graph["execution_order"] == [5, 4, 3, 2, 1, 0]
    assert [row["ref"] for row in graph["blocks"]] == [f"{PARENT}.{leaf}" for leaf in leaves]
    assert [row["object"] for row in graph["blocks"]] == [
        str(ObjectIdentifier(i)) for i in identities
    ]
    assert graph["connections"] == [
        {
            "index": 0,
            "source_ref": f"{PARENT}.{leaves[0]}",
            "source_port": 85,
            "target_ref": f"{PARENT}.{leaves[1]}",
            "target_port": 7000,
        }
    ]
    summary = app.summary()
    assert not summary["errors"] and summary["diagrams"][0]["blocks"] == 6
    with pytest.raises(ValueError, match="Native block reference"):
        app.diagram(PARENT)


@pytest.mark.parametrize(
    "members,framed",
    [
        ([member(header_instance=30)], True),
        ([member(cid=551)], True),
        ([member(cid=528)], True),
        ([member(public_type=19)], True),
        ([member(leaf="19_88")], True),
        ([member(leaf="2_word")], True),
        ([member(leaf="2_4194303")], True),
        ([member(parent=PARENT + ".536_2")], True),
        ([member(), member(leaf="2_89")], True),
        ([member(), member(cid=551, leaf="arbitrary")], True),
        ([member(), member(instance=27, leaf="2_11")], True),
        ([member(), member(leaf="2_88")], True),
        ([member()], False),
    ],
)
def test_invalid_or_ambiguous_identity_does_not_supply_a_missing_member(members, framed):
    source = application([*members, member(527, 2, 12, "2_12")], framed=framed)
    app = MoiApplication(source)
    with pytest.raises(ValueError, match="Native block reference"):
        app.display_diagram(PARENT)
    assert not app.summary()["diagrams"] and app.summary()["errors"]


def test_other_diagram_can_reuse_local_identity_and_exact_members_still_work():
    app = MoiApplication(
        application(
            [
                member(),
                member(parent=PARENT + ".536_2"),
                member(527, 2, 12, "2_12"),
            ]
        )
    )
    assert app.display_diagram(PARENT)["blocks"][0]["ref"] == f"{PARENT}.2_88"
    exact = MoiApplication(application([member(leaf="2_11"), member(527, 2, 12, "2_12")]))
    assert exact.diagram(PARENT)["connections"] == exact.display_diagram(PARENT)["connections"]


async def test_controller_workspace_reopens_the_signal_drawing_from_its_file_capture(link):
    server, connector, files, target = link
    source = application([member(), member(527, 2, 12, "2_12")])
    server.payload = source
    server.stream.fileSize = len(source)
    server.stream.fileType = ".moi"
    service = ControllerApplication(connector, connector.store, files)
    field = await service.read_application(target)
    assert field["identity_verified"] and field["application"]["diagrams"][0]["ref"] == PARENT
    request = {**target, "capture_id": field["receipt"]["id"], "ref": PARENT}
    display = service.diagram(request)
    assert display["read_only"] and display["sha256"] == field["receipt"]["sha256"]
    assert display["diagram"]["connections"][0]["source_ref"] == f"{PARENT}.2_88"
    assert server.payload == source and server.atomic_requests
