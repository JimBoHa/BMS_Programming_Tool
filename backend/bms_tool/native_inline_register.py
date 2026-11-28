"""Build one output-independent sample register from the captured release's own primitives."""

from collections import defaultdict

from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)

from .moi_application import _list, _structs
from .native_inline_monitor import atoms
from .native_inline_sequence import _wire, released_prototype
from .native_inputs import encoded, raw_property
from .native_root_layout import CONTINUATION, POSITION, _row


def append_clock_activity(root, add):
    """Route an internal float between the two declared ports of a native activity."""
    ports = {}

    def contents(reference):
        for name, cid, attribute, element in (
            ("input", 526, 7000, 230),
            ("output", 527, 8000, 233),
        ):
            _, ports[name] = add(
                cid,
                2,
                reference,
                {
                    2390: encoded(CharacterString("Elapsed seconds")),
                    3365: encoded(Enumerated(attribute)),
                    3670: encoded(Enumerated(element)),
                },
            )
        return {
            2390: encoded(CharacterString("Register timing input")),
            3117: atoms(Unsigned, [0, 1]),
            3118: _wire(0, 663, 1, 513),
            3184: atoms(Enumerated, [7000, 8000]),
            3373: encoded(Boolean(True)),
            3375: atoms(ObjectIdentifier, [ports["input"], ports["output"]]),
            3383: _row(Real(0), Real(0), Unsigned(0)) + _row(Real(200), Real(0), Unsigned(0)),
            3384: _row(Boolean(False), CharacterString("")),
            3670: encoded(Enumerated(0)),
        }

    reference, object_id = add(536, 536, root, contents, member=True)
    return {"reference": reference, "object": object_id, **ports}


def verify_clock_activity(app, expected):
    reader = app.reader
    reference = expected["reference"]
    item = reader.records[reference]
    graph = reader.diagram(reference, retained_activity_refs=True)
    blocks = graph["blocks"]
    if (
        item["class_id"] != 536
        or reader.scalar(item, 75) != expected["object"]
        or reader.scalar(item, 3670) != 0
        or list(_list(item["properties"][3184]["tags"], Enumerated)) != [7000, 8000]
        or [b["object"] for b in blocks] != [expected["input"], expected["output"]]
        or graph["execution_order"] != [0, 1]
        or len(_structs(item["properties"][3383]["tags"], POSITION)) != 2
        or len(_structs(item["properties"][3384]["tags"], CONTINUATION)) != 1
    ):
        raise ValueError(
            "The serialized timing activity differs from its declared members or order."
        )
    for block, (cid, aid, code) in zip(blocks, [(526, 7000, 230), (527, 8000, 233)], strict=True):
        pin = reader.records[block["ref"]]
        if (
            pin["class_id"] != cid
            or reader.scalar(pin, 3365) != aid
            or reader.scalar(pin, 3670) != code
        ):
            raise ValueError("The serialized Float activity pin differs from its declared type.")
    if graph["connections"] != [
        {
            "index": 0,
            "source_ref": blocks[0]["ref"],
            "source_port": 663,
            "target_ref": blocks[1]["ref"],
            "target_port": 513,
        }
    ]:
        raise ValueError("The serialized timing activity does not connect its input to its output.")


def append_clock_register(app, root, add, first, clock_source):
    children = defaultdict(list)
    read = app.reader.scalar
    for item in app.records:
        reference = read(item, 32527) or ""
        children[reference.rpartition(".")[0]].append(item)

    def original_properties(record):
        fields = {}
        for pid in record["properties"].keys() - {75, 32527}:
            value = raw_property(app, record, pid)
            if not value or value[-1:] != b"\x2f":
                raise ValueError("Invalid source primitive property boundary.")
            fields[pid] = value[:-1]
        return fields

    def primitive(kind, label, defaults):
        _, record, ports = released_prototype(kind, [(app, children)])
        cid = record["class_id"]
        if 3184 not in record["properties"]:
            raise ValueError("The sampling register requires a declared connection port list.")
        pins = [int(pin) for pin in _list(record["properties"][3184]["tags"], Enumerated)]
        if len(set(pins)) != len(pins) or set(ports) - {637} - set(pins):
            raise ValueError("The sampled register needs the source primitive's connection ports.")
        fields = original_properties(record)
        fields[2390] = encoded(CharacterString(label))
        parent, _ = add(cid, cid, root, fields, member=True)
        created = {}
        for number, port in ports.items():
            typ = int(ObjectIdentifier(read(port, 75))[0])
            expected = 5 if port["class_id"] in (530, 531) else 2
            if typ != expected:
                raise ValueError("A sampled register port has an incompatible object identity.")
            fields = original_properties(port)
            data_type = Boolean if typ == 5 else Real
            fields[3113] = encoded(data_type(defaults.get(number, False if typ == 5 else 0.0)))
            _, created[number] = add(port["class_id"], typ, parent, fields)
        return created[85]

    # The independent timer is the changing test signal. During the high half
    # of its countdown the register tracks it. In the low half it retains a sample.
    gate = primitive("ge", "Register high half of countdown", {50084: 30.0})
    previous = primitive("prevF", "Previous gated countdown", {})
    output = primitive("select", "Gated countdown sample", {})
    compare, memory, switch = range(first, first + 3)
    wires = [
        (*clock_source, compare, 50083),
        (compare, 85, switch, 961),
        (memory, 85, switch, 7000),
        (*clock_source, switch, 7001),
        (switch, 85, memory, 513),
    ]
    return wires, {
        "gate": gate,
        "memory": previous,
        "output": output,
        "threshold_seconds": 30.0,
        "period_seconds": 60,
    }
