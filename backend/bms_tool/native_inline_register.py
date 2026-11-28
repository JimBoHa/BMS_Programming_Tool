"""Build one output-independent sample register from the captured release's own primitives."""

from collections import defaultdict

from bacpypes3.primitivedata import Boolean, CharacterString, Enumerated, ObjectIdentifier, Real

from .moi_application import _list
from .native_inline_sequence import released_prototype
from .native_inputs import encoded, raw_property


def append_clock_register(app, root, add, first, timer_index):
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
        (timer_index, 1081, compare, 50083),
        (compare, 85, switch, 961),
        (memory, 85, switch, 7000),
        (timer_index, 1081, switch, 7001),
        (switch, 85, memory, 513),
    ]
    return wires, {
        "gate": gate,
        "memory": previous,
        "output": output,
        "threshold_seconds": 30.0,
        "period_seconds": 60,
    }
