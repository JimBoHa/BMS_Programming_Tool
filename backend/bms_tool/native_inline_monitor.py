"""Compile a fixed, output-independent timing and input monitor for a legacy VAV."""

import math

from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    TagClass,
    Unsigned,
)

from .moi_application import _atomic, _expect
from .moi_identity import MoiIdentity, sha
from .moi_parameters import ParameterApplication
from .native_inputs import archive, encoded, raw_property, record_instance, replace_properties
from .native_io_records import scalar_bytes
from .native_parameter_qualification import qualify_parameter_additions
from .native_root_layout import assemble_root, verify_layout

PROFILE = "native-inline-input-and-clock-monitor/1"
MODELS = {"MS-VMA1630-0", "FX-PCV1630-0"}
FIRMWARE = "6.2.0.1054"
LIMIT = 4_194_302
CLOCK = "Sampling interval clock"
PREVIOUS = "Sampling interval witness"


def atoms(cls, values):
    return b"".join(encoded(cls(v)) for v in values)


def record(cid, instance, public_type, reference, properties):
    ident = (cid << 22) | instance
    out = bytearray(
        cid.to_bytes(2, "little") + b"\x02\x00\x0e\x1c" + ident.to_bytes(4, "big") + b"\x0f\x1e"
    )
    fields = {
        75: encoded(ObjectIdentifier((public_type, instance))),
        32527: encoded(CharacterString(reference)),
        **properties,
    }
    for pid, data in sorted(fields.items()):
        size = max(1, (pid.bit_length() + 7) // 8)
        out.extend(bytes([8 + size]) + pid.to_bytes(size, "big") + b"\x2e" + data + b"\x2f")
    return bytes(out) + b"\x1f"


def single(items, reason):
    items = list(items)
    if len(items) != 1:
        raise ValueError(reason)
    return items[0]


def floating_valve_configuration(app, valve):
    read = app.reader.scalar
    for pid, datatype in (
        (75, "ObjectIdentifier"),
        (31, "CharacterString"),
        (32527, "CharacterString"),
        (117, "Enumerated"),
        (990, "Unsigned"),
        (991, "Unsigned"),
        (3478, "Real"),
    ):
        scalar_bytes(app, valve, pid, datatype)
    first, second = read(valve, 990), read(valve, 991)
    if 519 in valve["properties"]:
        scalar_bytes(app, valve, 519, "Unsigned")
    expected_object = f"analog-output,{record_instance(app, valve)}"
    stroke = read(valve, 3478)
    if (
        first not in (1, 2, 3)
        or second not in (1, 2, 3)
        or first == second
        or read(valve, 31) != f"BO OUT{first},BO OUT{second}"
        or read(valve, 75) != expected_object
        or read(valve, 117) != 98
        or read(valve, 32527).rpartition("/")[0] != app.ref
        or read(valve, 519) not in (None, first)
        or not math.isfinite(stroke)
        or stroke <= 0
    ):
        raise ValueError(
            "The captured floating valve needs two distinct external binary terminals, a percentage command and a positive stroke time."
        )
    return {"terminals": [first, second], "stroke_seconds": stroke}


def sources(app, graph, *, allow_floating=False):
    read = app.reader.scalar
    rows = app.records
    outputs = [r for r in rows if r["class_id"] in (239, 241, 251)]
    valve = single(
        (
            r
            for r in outputs
            if read(r, 2390) == "HTG-O"
            and (r["class_id"] == 241 or (allow_floating and r["class_id"] == 251))
        ),
        "Expected one configured inline valve."
        if allow_floating
        else "Expected one proportional inline valve.",
    )
    damper = single(
        (r for r in outputs if r["class_id"] == 251 and read(r, 2390) == "DPR-O"),
        "Expected the integral damper.",
    )
    if (
        len(outputs) != 2
        or (read(damper, 990), read(damper, 991)) != (6, 7)
        or (
            valve["class_id"] == 241
            and (read(valve, 31), read(valve, 990), read(valve, 117)) != ("CO OUT4", 4, 98)
        )
        or read(damper, 31) != "BO1-Int,BO2-Int"
    ):
        raise ValueError(
            "The monitor requires an inline valve and integral damper with verified terminals."
        )
    pressure = single(
        (
            r
            for r in rows
            if r["class_id"] == 240
            and read(r, 31) == "AI1-Int"
            and read(r, 117) == 58
            and read(r, 2390) == "DA-VP"
        ),
        "A unique integral differential-pressure input is required.",
    )
    duct = single(
        (
            r
            for r in rows
            if r["class_id"] == 240
            and read(r, 2390) == "DA-T"
            and read(r, 117) == 64
            and str(read(r, 31)).startswith("UI IN")
        ),
        "A local discharge sensor in degrees Fahrenheit is required.",
    )
    flow = single(
        (
            r
            for r in rows
            if r["class_id"] == 527
            and read(r, 2390) == "SA-F"
            and read(r, 117) == 84
            and read(r, 3365) == 3505
        ),
        "A unique calculated airflow output in CFM is required.",
    )
    blocks = graph["blocks"]
    calc = single(
        (
            b
            for b in blocks
            if b["class_id"] == 570
            and read(app.reader.records[b["ref"]], 3670) == 681
            and read(flow, 32527).rpartition(".")[0] == b["ref"]
        ),
        "The airflow value must belong to the root supply-flow calculation.",
    )
    pickup = single(
        (b for b in blocks if b["class_id"] == 556 and b["name"] == "DA-VP"),
        "Missing root pickup source.",
    )
    for hardware in (pressure, duct):
        if not read(hardware, 32527).startswith(app.ref + "/"):
            raise ValueError("A sensor does not belong to the selected local controller.")
    parent = app.reader.records[pickup["ref"]]
    reference = parent["properties"].get(3399, {}).get("tags", [])
    if len(reference) != 6:
        raise ValueError("The existing pickup has no single local attribute reference.")
    for idx, kind, number in (
        (0, TagClass.opening, 3),
        (2, TagClass.opening, 4),
        (3, TagClass.closing, 4),
        (5, TagClass.closing, 3),
    ):
        _expect(reference[idx], kind, number)
    if (
        str(_atomic(reference[1], CharacterString)) != read(pressure, 32527)
        or int(_atomic(reference[4], Enumerated)) != 85
    ):
        raise ValueError("The existing pickup does not reference the selected pressure input.")
    supply = [
        e
        for e in graph["connections"]
        if e["target_ref"] == calc["ref"] and e["target_port"] == 3504
    ]
    if len(supply) != 1 or (supply[0]["source_ref"], supply[0]["source_port"]) != (
        pickup["ref"],
        8000,
    ):
        raise ValueError("The airflow calculation must read the selected pickup.")
    return dict(
        pressure=pressure,
        duct=duct,
        flow=flow,
        valve=valve,
        damper=damper,
        calculation=app.reader.records[calc["ref"]],
    )


def compile_monitor(
    files,
    first_instance,
    *,
    preserve_root_layout=True,
    allow_floating=False,
    sample_register=False,
    activity_input=False,
    register_source="countdown",
):
    if type(first_instance) is not int or not 1 <= first_instance <= LIMIT:
        raise ValueError("Select a valid first native object instance.")
    if type(sample_register) is not bool:
        raise ValueError("Select a Boolean sampling register option.")
    if type(activity_input) is not bool or (activity_input and not sample_register):
        raise ValueError("The activity input requires an enabled sample register.")
    if register_source not in ("countdown", "supply-airflow"):
        raise ValueError("Select the countdown or the verified supply airflow.")
    if register_source == "supply-airflow" and not sample_register:
        raise ValueError("An airflow source requires an enabled sample register.")
    effective, merge = ParameterApplication(files[3], files[11], files[12]).compile()
    qualification = qualify_parameter_additions(effective, merge)
    app = MoiIdentity(effective)
    info = app.summary()
    if (
        app.reader.errors
        or info["format_versions"] != {"acs": 62, "dmcs": 62}
        or info["model"] not in MODELS
    ):
        raise ValueError(
            "This monitor supports complete native 62/62 applications for the 1630 VMA/PCV family."
        )
    read = app.reader.scalar
    root = single(
        (r for r in app.records if r["class_id"] == 575), "Expected a single root control sequence."
    )
    ref = read(root, 32527)
    if ref.rpartition("/")[0] != app.ref or {3162, 3461, 3383, 3384} & root["properties"].keys():
        raise ValueError("Unsupported root layout or continuation records.")
    g = app.reader.diagram(ref, retained_activity_refs=True)
    if any(read(r, 2390) in (CLOCK, PREVIOUS) for r in app.records):
        raise ValueError("This application already includes the sampling monitor.")
    physical = sources(app, g, allow_floating=allow_floating)
    valve = physical["valve"]
    floating = floating_valve_configuration(app, valve) if valve["class_id"] == 251 else None
    taken = {
        int.from_bytes(app.data[r["offset"] + 6 : r["offset"] + 10], "big") & 0x3FFFFF
        for r in app.records
    }
    taken.update(int(ObjectIdentifier(read(r, 75))[1]) for r in app.records if read(r, 75))
    numbers = (i for i in range(first_instance, LIMIT + 1) if i not in taken)
    additions = []
    members = []
    identifiers = []
    observations = {}

    def add(cid, typ, parent, props, *, member=False):
        num = next(numbers, None)
        if num is None:
            raise ValueError("Insufficient free identifiers for the monitor.")
        oid = ObjectIdentifier((typ, num))
        item = f"{parent}.{typ}_{num}"
        identifiers.append(str(oid))
        if member:
            members.append(oid)
        # An activity declares its child identities in its own record. Reserve
        # its place before allocating those children, retaining source order.
        slot = len(additions)
        additions.append(b"")
        fields = props(item) if callable(props) else props
        additions[slot] = record(cid, num, typ, item, fields)
        return item, str(oid)

    def port(parent, cid, typ, attribute, default=None, **metadata):
        props = {3365: encoded(Enumerated(attribute))}
        if default is not None:
            props[3113] = encoded(default)
        for key, value in metadata.items():
            props[int(key[1:])] = encoded(value)
        return add(cid, typ, parent, props)[1]

    for key, pid, boolean, label in (
        ("pressure", 1433, False, "Monitor raw pickup"),
        ("duct", 85, False, "Monitor discharge temperature"),
        ("pressure", 81, True, "Monitor pickup service flag"),
        ("duct", 81, True, "Monitor discharge service flag"),
        ("flow", 3368, True, "Monitor airflow test flag"),
    ):
        physical_record = physical[key]
        reference = read(physical_record, 32527)
        source = (
            b"\x3e"
            + encoded(CharacterString(reference))
            + b"\x4e\x4f"
            + encoded(Enumerated(pid))
            + b"\x3f"
        )
        parent, _ = add(
            556,
            556,
            ref,
            {
                2390: encoded(CharacterString(label)),
                3114: encoded(Boolean(False)),
                3184: atoms(Enumerated, [8000, 86]),
                3399: source,
                3579: encoded(Unsigned(int(boolean))),
                3670: encoded(Enumerated(91 if boolean else 89)),
            },
            member=True,
        )
        if boolean:
            out = port(parent, 531, 5, 8000, Boolean(True))
        else:
            out = port(
                parent,
                527,
                2,
                8000,
                Real(250 if key == "duct" else 0),
                p22=Real(0),
                p117=Enumerated(read(physical_record, 117)),
                p661=Enumerated(4),
                p3930=Boolean(False),
            )
        port(parent, 527, 2, 86, p661=Enumerated(6))
        observations[label] = {
            "object": out,
            "source": read(physical_record, 75),
            "property": pid,
            "boolean": boolean,
        }

    clock, _ = add(
        558,
        558,
        ref,
        {
            2390: encoded(CharacterString(CLOCK)),
            3184: atoms(Enumerated, [513, 1080, 85, 1081]),
            3670: encoded(Enumerated(62)),
            1184: encoded(Unsigned(1)),
        },
        member=True,
    )
    port(clock, 531, 5, 85, Boolean(False))
    port(clock, 530, 5, 513, Boolean(False))
    port(clock, 530, 5, 1082, Boolean(False))
    port(clock, 528, 19, 518, Enumerated(5), p74=Unsigned(9), p931=Enumerated(21))
    port(clock, 526, 2, 1080, Real(60), p117=Enumerated(73), p661=Enumerated(6))
    port(clock, 528, 19, 1083, Enumerated(0), p74=Unsigned(2), p931=Enumerated(22))
    port(clock, 527, 2, 1081, Real(0), p117=Enumerated(73), p661=Enumerated(6))
    witness, _ = add(
        538,
        538,
        ref,
        {
            2390: encoded(CharacterString(PREVIOUS)),
            3184: atoms(Enumerated, [513, 85]),
            3670: encoded(Enumerated(79)),
        },
        member=True,
    )
    clock_output = port(witness, 527, 2, 85, Real(0))
    port(witness, 526, 2, 513, Real(0))
    n = len(g["blocks"])
    added_wires = [(n + 5, 1081, n + 6, 513)]
    register = None
    activity = None
    if sample_register:
        from .native_inline_register import append_clock_activity, append_clock_register

        clock_source = (n + 5, 1081)
        if activity_input:
            activity_index = n + len(members)
            activity = append_clock_activity(ref, add)
            added_wires.append((*clock_source, activity_index, 7000))
            clock_source = (activity_index, 8000)
        airflow_source = None
        if register_source == "supply-airflow":
            flow_ref = read(physical["calculation"], 32527)
            flow_index = next(b["index"] for b in g["blocks"] if b["ref"] == flow_ref)
            flow_port = read(physical["flow"], 3365)
            airflow_source = (flow_index, flow_port)
        links, register = append_clock_register(
            app, ref, add, n + len(members), clock_source, airflow_source=airflow_source
        )
        if airflow_source is not None:
            register["airflow_source"] = {
                "object": read(physical["flow"], 75),
                "reference": read(physical["flow"], 32527),
                "parent": flow_ref,
                "port": flow_port,
                "units": read(physical["flow"], 117),
            }
        added_wires.extend(links)
    if n + len(members) > 512 or len(g["connections"]) + len(added_wires) > 4096:
        raise ValueError("Insufficient graph capacity for the timing monitor.")
    new_wire = b"".join(b"\x3e" + atoms(Unsigned, link) + b"\x3f" for link in added_wires)
    root_bytes = replace_properties(
        app,
        root,
        {
            3375: raw_property(app, root, 3375)[:-1] + b"".join(encoded(m) for m in members),
            3117: raw_property(app, root, 3117)[:-1] + atoms(Unsigned, range(n, n + len(members))),
            3118: raw_property(app, root, 3118)[:-1] + new_wire,
        },
    )
    originals = [
        root_bytes if r is root else app.data[r["offset"] : r["end_offset"]] for r in app.records
    ]
    ordered, added_at, footer = originals + additions, len(originals), None
    if preserve_root_layout:
        ordered, added_at, footer = assemble_root(
            app, root, originals, additions, g, members, len(added_wires)
        )
    output = archive(app, ordered)
    actual = MoiIdentity(output)
    parsed = actual.reader.diagram(ref, retained_activity_refs=True)
    verify_layout(app, actual, footer, parsed)
    if activity is not None:
        from .native_inline_register import verify_clock_activity

        verify_clock_activity(actual, activity)
    retained = actual.records[:added_at] + actual.records[added_at + len(additions) :]
    if (
        actual.reader.errors
        or actual.instance != app.instance
        or len(actual.records) != len(originals) + len(additions)
        or any(
            a["sha256"] != b["sha256"]
            for i, (a, b) in enumerate(zip(app.records, retained, strict=True))
            if a is not root and i != footer
        )
        or [b["ref"] for b in parsed["blocks"][:n]] != [b["ref"] for b in g["blocks"]]
        or parsed["execution_order"] != g["execution_order"] + list(range(n, n + len(members)))
        or parsed["connections"]
        != g["connections"]
        + [
            {
                "index": len(g["connections"]) + i,
                "source_ref": parsed["blocks"][start]["ref"],
                "source_port": source_port,
                "target_ref": parsed["blocks"][end]["ref"],
                "target_port": target_port,
            }
            for i, (start, source_port, end, target_port) in enumerate(added_wires)
        ]
        or any(
            actual.reader.scalar(r, 3807) is True
            for r in actual.records[added_at : added_at + len(additions)]
        )
    ):
        raise ValueError("The decoded monitoring graph does not preserve the original application.")
    return output, {
        "profile": PROFILE,
        **(
            {"root_layout_version": 2, "separate_root_layout_updated": footer is not None}
            if preserve_root_layout
            else {}
        ),
        "source_sha256": sha(files[3]),
        "native_edited_sha256": sha(actual.data),
        "root": ref,
        "first_instance": first_instance,
        "new_records": len(additions),
        "new_blocks": len(members),
        "original_wires": len(g["connections"]),
        "observations": observations,
        "clock_witness": clock_output,
        **({"sampling_register": register} if register is not None else {}),
        **({"register_input_activity": activity} if activity is not None else {}),
        "added_objects": identifiers,
        "points": {k: read(v, 75) for k, v in physical.items()},
        **({"floating_valve": floating} if floating is not None else {}),
        "saved_settings": merge["matched_parameters"],
        "parameter_qualification": qualification,
    }
