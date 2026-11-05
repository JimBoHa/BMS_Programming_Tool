"""Authored PID graph fixtures and display evidence; no controller files."""

import gzip
import hashlib

from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real, Unsigned
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.logic_display import function_symbol, pin_name
from bms_tool.moi_application import MoiApplication

from .test_caf_graph import pack, prop, record, shorts
from .test_controller_application import encoded, native_record

REF = "authored/575_1"
BLOCKS = [
    (526, 2, 10, "Zone temperature"),
    (526, 2, 11, "Cooling setpoint"),
    (252, 252, 20, "Cooling loop"),
    (527, 2, 12, "Cooling demand"),
]
WIRES = [(0, 663, 2, 695), (1, 663, 2, 108), (2, 85, 3, 513)]


def pid_native():
    root = native_record(
        575,
        1,
        [
            (32527, encoded(CharacterString(REF))),
            (75, encoded(ObjectIdentifier((575, 1)))),
            (2390, encoded(CharacterString("Authored cooling control"))),
            (3375, b"".join(encoded(ObjectIdentifier((typ, inst))) for _, typ, inst, _ in BLOCKS)),
            (3117, b"".join(encoded(Unsigned(i)) for i in range(4))),
            (
                3118,
                b"".join(
                    b"\x3e" + b"".join(encoded(Unsigned(v)) for v in wire) + b"\x3f"
                    for wire in WIRES
                ),
            ),
        ],
    )
    children = []
    for cid, typ, inst, name in BLOCKS:
        fields = [
            (32527, encoded(CharacterString(f"{REF}.{typ}_{inst}"))),
            (75, encoded(ObjectIdentifier((typ, inst)))),
            (2390, encoded(CharacterString(name))),
        ]
        if cid == 252:
            fields += [(1200, encoded(Real(15))), (1201, encoded(Real(300)))]
        else:
            fields += [(3113, encoded(Real(72 if inst == 10 else 74 if inst == 11 else 0)))]
        children.append(native_record(cid, inst, fields))
    children.append(
        native_record(
            526,
            99,
            [
                (32527, encoded(CharacterString(f"{REF}.252_20.2_99"))),
                (75, encoded(ObjectIdentifier((2, 99)))),
                (2390, encoded(CharacterString("Loop setpoint"))),
                (3365, encoded(Enumerated(108))),
            ],
        )
    )
    return gzip.compress(b"\x02\x00MOI\x00" + root + b"".join(children), mtime=0)


def pid_caf():
    def obj(cid, typ, inst, name, parent=REF):
        return (
            f'<object classid="{cid}" classVersion="1.0" objectid="{inst}" ref="{parent}.{typ}_{inst}">'
            + prop(75, f'<BACoid id="{typ}">{inst}</BACoid>')
            + prop(2390, f"<string>{name}</string>")
        )

    root = (
        f'<object classid="575" classVersion="1.0" objectid="1" ref="{REF}">'
        + prop(2390, "<string>Authored cooling control</string>")
        + prop(
            3375,
            "<array>"
            + "".join(f'<BACoid id="{typ}">{inst}</BACoid>' for _, typ, inst, _ in BLOCKS)
            + "</array>",
        )
        + prop(3117, "<array>" + "".join(shorts(0, 1, 2, 3)) + "</array>")
        + prop(3118, "<array>" + "".join(record(*shorts(*w)) for w in WIRES) + "</array>")
        + prop(
            3383,
            "<listof>"
            + record("<float>0</float>", "<float>0</float>", "<unsignedShort>0</unsignedShort>") * 4
            + "</listof>",
        )
        + prop(3384, "<listof>" + record("<boolean>0</boolean>", "<string/>") * 3 + "</listof>")
        + "</object>"
    )
    children = ""
    for cid, typ, inst, name in BLOCKS:
        children += obj(cid, typ, inst, name)
        if cid != 252:
            children += prop(
                3113, f"<float>{72 if inst == 10 else 74 if inst == 11 else 0}</float>"
            )
        children += "</object>"
    children += (
        obj(526, 2, 99, "Loop setpoint", REF + ".252_20")
        + prop(3365, '<enum set="509">108</enum>')
        + "</object>"
    )
    return pack(f'<objects xmlns="{NS}">{root}{children}</objects>'.encode())


def test_native_pid_port_names_and_defaults_come_from_source_and_dictionary():
    source = pid_native()
    app = MoiApplication(source)
    canonical = app.diagram(REF)
    graph = app.display_diagram(REF)
    assert "port_labels" not in canonical
    assert "stored_value" not in canonical["blocks"][0]
    assert "pin_labels" not in canonical["blocks"][2]
    assert app.diagram(REF) == canonical
    assert graph["port_labels"]["252"]["695"] == "Process Variable"
    assert graph["port_labels"]["252"]["108"] == "Setpoint"
    assert graph["blocks"][2]["pin_labels"] == {"108": "Loop setpoint"}
    assert graph["blocks"][0]["stored_value"] == {"text": "72.0", "datatype": "Real"}
    assert "stored_value" not in graph["blocks"][2]
    assert app.summary()["sha256"] == hashlib.sha256(source).hexdigest()
    assert graph["execution_order"] == [0, 1, 2, 3]
    assert [(w["source_port"], w["target_port"]) for w in graph["connections"]] == [
        (663, 695),
        (663, 108),
        (85, 513),
    ]


def test_caf_uses_same_port_names_and_preserves_original_bytes():
    source = pid_caf()
    graph = CafGraph(source)
    data = graph.diagram(REF)
    assert data["port_labels"]["252"]["695"] == "Process Variable"
    assert data["blocks"][2]["pin_labels"] == {"108": "Loop setpoint"}
    assert data["blocks"][0]["stored_value"] == {"text": "72", "datatype": "float"}
    assert [w["raw"] for w in data["connections"]] == [list(w) for w in WIRES]
    assert graph.archive.original == source


def test_unknown_class_ports_and_setup_codes_keep_uncertainty():
    assert pin_name(65000, 65001) == "Property 65001"
    assert pin_name(536, 7003) == "Input 4"
    assert function_symbol(561, 14)["text"] == "+"
    assert function_symbol(560, 3)["text"] == "≥"
    assert function_symbol(559, 1) is None
    assert function_symbol(561, 999) is None


def test_conflicting_native_child_pin_names_do_not_replace_the_dictionary():
    child = native_record(
        526,
        100,
        [
            (32527, encoded(CharacterString(f"{REF}.252_20.2_100"))),
            (75, encoded(ObjectIdentifier((2, 100)))),
            (2390, encoded(CharacterString("Conflicting setpoint"))),
            (3365, encoded(Enumerated(108))),
        ],
    )
    source = gzip.compress(gzip.decompress(pid_native()) + child, mtime=0)
    diagram = MoiApplication(source).display_diagram(REF)
    assert "108" not in diagram["blocks"][2]["pin_labels"]
    assert diagram["port_labels"]["252"]["108"] == "Setpoint"


def test_conflicting_caf_child_pin_names_do_not_replace_the_dictionary():
    xml = CafArchive(pid_caf()).xml
    child = (
        f'<object classid="526" classVersion="1.0" objectid="100" ref="{REF}.252_20.2_100">'
        + prop(75, '<BACoid id="2">100</BACoid>')
        + prop(2390, "<string>Conflicting setpoint</string>")
        + prop(3365, '<enum set="509">108</enum>')
        + "</object>"
    ).encode()
    diagram = CafGraph(pack(xml.replace(b"</objects>", child + b"</objects>"))).diagram(REF)
    assert "108" not in diagram["blocks"][2]["pin_labels"]
    assert diagram["port_labels"]["252"]["108"] == "Setpoint"
