"""Build a source-bound airflow permissive in a local CV native application copy."""

import math
import struct

from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)

from .moi_application import MAX_SOURCE, _list
from .moi_identity import MoiIdentity, seal, sha
from .moi_parameters import ParameterApplication
from .native_inputs import archive, encoded, raw_property, record_instance, replace_properties

# Class, standard logic function, native setup, exposed pins, and child class by bound port.
RELIABLE = (539, 21, None, (513, 85), {513: 526, 85: 531})
AT_LEAST = (560, 32, 3, (85, 50083, 50084), {50083: 526, 50084: 526, 637: 526, 85: 531})
AND_2 = (559, 24, 1, (7000, 7001, 85), {7000: 530, 7001: 530, 85: 531})
FLOAT_SWITCH = (562, 14, None, (961, 7000, 7001, 85), {961: 530, 7000: 526, 7001: 526, 85: 527})
GATE_LABEL = "Inline reheat airflow permissive"


def _wire(source, pin, dest, port):
    return b"\x3e" + b"".join(encoded(Unsigned(v)) for v in (source, pin, dest, port)) + b"\x3f"


def _prototypes(app, spec):
    cid, function, setup, pins, children = spec
    read = app.reader.scalar
    for parent in app.records:
        if (
            parent["class_id"] != cid
            or read(parent, 3670) != function
            or read(parent, 518) != setup
        ):
            continue
        expected = {32527, 75, 3184, 3670} | ({518} if setup is not None else set())
        if spec == FLOAT_SWITCH:
            expected.update({2381, 3122})
            paths = parent["properties"].get(2381)
            if (
                paths is None
                or tuple(map(int, _list(paths["tags"], Unsigned))) != (0, 2)
                or read(parent, 3122) != 1
            ):
                continue
        if set(parent["properties"]) != expected:
            continue
        if tuple(map(int, _list(parent["properties"][3184]["tags"], Enumerated))) != pins:
            continue
        prefix = read(parent, 32527) + "."
        ports = {}
        for child in app.records:
            ref = read(child, 32527)
            if not isinstance(ref, str) or not ref.startswith(prefix):
                continue
            port = read(child, 3365)
            properties = child["properties"]
            if (
                "." in ref[len(prefix) :]
                or port in ports
                or child["class_id"] != children.get(port)
                or not {75, 32527, 3365} <= properties.keys() <= {75, 32527, 3365, 3113, 3670}
                or (3670 in properties and read(child, 3670) != 0)
            ):
                break
            ports[port] = child
        else:
            if ports.keys() == children.keys():
                return parent, ports
    raise ValueError(f"Missing compatible native prototype for class {cid}, function {function}.")


def compile_permissive(
    source,
    *,
    source_sha256,
    diagram_ref,
    pressure_ref,
    flow_ref,
    enable_ref,
    passthrough_ref,
    valve_ref,
    threshold_cfm,
    first_instance=3_000_000,
):
    """Return a local candidate and the logical edit. The source must already include saved settings."""
    if len(source) > MAX_SOURCE or sha(source) != source_sha256:
        raise ValueError("Select the exact reviewed application source.")
    if type(threshold_cfm) not in (float, int) or not 0 < threshold_cfm <= 100_000:
        raise ValueError("Choose a finite positive commissioned proof threshold in CFM.")
    threshold = struct.unpack(">f", struct.pack(">f", threshold_cfm))[0]
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("The proof threshold must remain positive at native Real precision.")
    app = MoiIdentity(source)
    rd = app.reader
    if rd.errors or app.summary()["format_versions"] != {"acs": 66, "dmcs": 65}:
        raise ValueError("This editor requires a fully readable ACS 66 / DMCS 65 source.")
    graph = rd.diagram(diagram_ref)
    root = rd.records[diagram_ref]
    if (
        [rd.scalar(record, 32527) for record in app.records if record["class_id"] == 575]
        != [diagram_ref]
        or diagram_ref.rpartition("/")[0] != app.ref
        or root["class_id"] != 575
        or {3162, 3461, 3383, 3384} & root["properties"].keys()
    ):
        raise ValueError(
            "Select a supported root control sequence without stored layout or continuation tables."
        )
    read = rd.scalar
    block = {item["ref"]: item for item in graph["blocks"]}
    selected = (pressure_ref, flow_ref, enable_ref, passthrough_ref, valve_ref)
    if len(set(selected)) != len(selected) or any(ref not in block for ref in selected):
        raise ValueError("Select distinct members of the same active diagram.")
    pressure, flow, enable, through, valve = (block[ref] for ref in selected)
    if (
        [p["class_id"] for p in (pressure, flow, enable, through, valve)]
        != [556, 570, 530, 592, 555]
        or read(rd.records[flow_ref], 117) != 58  # BACnet cubic feet per minute
        or enable["name"] != "HTG-EN"
        or read(rd.records[passthrough_ref], 3670) != 711  # Boolean passthrough
    ):
        raise ValueError(
            "Expected measured CFM, a physical input, and the existing Boolean heat-enable path."
        )
    pid = record_instance(app, rd.records[pressure_ref])
    physical = [r for r in app.records if r["class_id"] == 240 and record_instance(app, r) == pid]
    if len(physical) != 1 or any(
        read(physical[0], k) != v for k, v in ((31, "AI1-Int"), (518, 9), (519, 4))
    ):
        raise ValueError(
            "The selected pressure control point must be the local integral differential sensor."
        )
    vid = record_instance(app, rd.records[valve_ref])
    outputs = [r for r in app.records if r["class_id"] == 241 and record_instance(app, r) == vid]
    if (
        valve["name"] != "HTG-O"
        or len(outputs) != 1
        or read(outputs[0], 2390) != "HTG-O"
        or read(outputs[0], 990) not in (4, 5)
        or read(outputs[0], 117) != 98
        or str(ObjectIdentifier((1, vid))) != read(outputs[0], 75)
    ):
        raise ValueError("Select the single physical percentage reheat valve control point.")
    if any(read(r, 2390) == GATE_LABEL for r in app.records):
        raise ValueError("This application already contains an inline airflow permissive.")
    members = list(graph["blocks"])
    order = list(graph["execution_order"])
    connections = [
        (
            block[w["source_ref"]]["index"],
            w["source_port"],
            block[w["target_ref"]]["index"],
            w["target_port"],
        )
        for w in graph["connections"]
    ]
    original = (enable["index"], 663, through["index"], 513)
    if (
        sum(row[2:] == original[2:] for row in connections) != 1
        or original not in connections
        or (pressure["index"], 8000, flow["index"], 3504) not in connections
        or not any(
            s == through["index"] and sp == 85 and members[t]["class_id"] == 540
            for s, sp, t, _ in connections
        )
    ):
        raise ValueError(
            "The recorded differential, flow and state-selection wiring does not match."
        )
    insertion = order.index(through["index"])
    if any(order.index(i["index"]) >= insertion for i in (pressure, flow, enable)):
        raise ValueError("The existing scan order cannot evaluate all signals before heat enable.")
    valve_links = [row for row in connections if row[2] == valve["index"]]
    if (
        len(valve_links) != 1
        or valve_links[0][3] != 7000
        or members[valve_links[0][0]]["class_id"] != 536
        or not insertion < order.index(valve_links[0][0]) < order.index(valve["index"])
    ):
        raise ValueError(
            "Expected one ordered heating activity driving the physical valve command."
        )
    demand = valve_links[0]
    demand_ref = members[demand[0]]["ref"]
    bound_source = [
        r
        for r in app.records
        if (read(r, 32527) or "").rpartition(".")[0] == demand_ref
        and read(r, 3365) == demand[1]
        and r["class_id"] == 527
    ]
    if len(bound_source) != 1:
        raise ValueError("The heating activity must expose a single Float demand output.")

    # Reserve instances globally across both native headers and exposed aliases.
    occupied = {record_instance(app, r) for r in app.records}
    occupied.update(ObjectIdentifier(read(r, 75))[1] for r in app.records if read(r, 75))
    if type(first_instance) is not int or not 1 <= first_instance <= 4_194_302:
        raise ValueError("Specify a valid first free native object instance.")
    identifiers = []
    for n in range(first_instance, 4_194_303):
        if n not in occupied:
            identifiers.append(n)
            if len(identifiers) == 29:
                break
    if len(identifiers) < 29:
        raise ValueError("Insufficient free object identifiers for the airflow permissive.")
    free = iter(identifiers)
    additions, member_ids, names = [], [], {}
    orig_size = len(members)
    if orig_size + 7 > 512 or len(connections) + 11 > 4096:
        raise ValueError("The edited diagram exceeds supported native graph limits.")

    def clone(record, identifier, public_type, ref, overrides):
        changes = {
            75: encoded(ObjectIdentifier((public_type, identifier))),
            32527: encoded(CharacterString(ref)),
            **overrides,
        }
        body = bytearray(replace_properties(app, record, changes))
        body[6:10] = ((record["class_id"] << 22) | identifier).to_bytes(4, "big")
        additions.append(bytes(body))

    def add(spec, name, defaults):
        source_block, ports = _prototypes(app, spec)
        cid = spec[0]
        identifier = next(free)
        ref = f"{diagram_ref}.{cid}_{identifier}"
        index = orig_size + len(member_ids)
        clone(source_block, identifier, cid, ref, {2390: encoded(CharacterString(name))})
        member_ids.append(ObjectIdentifier((cid, identifier)))
        names[name] = ref
        for port, child in ports.items():
            local = next(free)
            typ = int(ObjectIdentifier(read(child, 75))[0])
            # Rebind only captured numeric or Boolean port objects. Clear donor defaults,
            # especially the reliability block's previously true output.
            value = defaults.get(port, False if typ == 5 else 0.0)
            atom = Boolean(value) if typ == 5 else Real(value)
            if typ not in (2, 5):
                raise ValueError("Unsupported prototype child type.")
            clone(child, local, typ, f"{ref}.{typ}_{local}", {3113: encoded(atom)})
        return index

    pressure_ok = add(RELIABLE, "Integral pressure signal reliable", {})
    flow_ok = add(RELIABLE, "Measured airflow signal reliable", {})
    sensors_ok = add(AND_2, "Both local airflow signals reliable", {})
    safe_flow = add(FLOAT_SWITCH, "Zero airflow on invalid sensor", {})
    above = add(AT_LEAST, "Measured airflow above proof threshold", {50084: threshold})
    permitted = add(AND_2, GATE_LABEL, {})
    valve_command = add(FLOAT_SWITCH, "Proven airflow valve command", {})
    new_wires = [
        (pressure["index"], 8000, pressure_ok, 513),
        (flow["index"], 3505, flow_ok, 513),
        (pressure_ok, 85, sensors_ok, 7000),
        (flow_ok, 85, sensors_ok, 7001),
        (sensors_ok, 85, safe_flow, 961),
        (flow["index"], 3505, safe_flow, 7001),
        (safe_flow, 85, above, 50083),
        (enable["index"], 663, permitted, 7000),
        (above, 85, permitted, 7001),
        (above, 85, valve_command, 961),
        (demand[0], demand[1], valve_command, 7001),
    ]
    original_index = connections.index(original)
    valve_wire_index = connections.index(demand)
    connections[original_index] = (permitted, 85, through["index"], 513)
    connections[valve_wire_index] = (valve_command, 85, valve["index"], 7000)
    connections.extend(new_wires)
    order[insertion:insertion] = list(range(orig_size, valve_command))
    order.insert(order.index(valve["index"]), valve_command)
    roots = {
        3375: raw_property(app, root, 3375)[:-1] + b"".join(encoded(m) for m in member_ids),
        3117: b"".join(encoded(Unsigned(i)) for i in order),
        3118: b"".join(_wire(*row) for row in connections),
    }
    repaired = replace_properties(app, root, roots)
    records = [
        repaired if r["offset"] == root["offset"] else app.data[r["offset"] : r["end_offset"]]
        for r in app.records
    ]
    out = archive(app, records + additions)
    # Independently reparse all members, links and order; every other original record is byte-identical.
    rebuilt = MoiIdentity(out)
    verified = rebuilt.reader.diagram(diagram_ref)
    indices = {z["ref"]: z["index"] for z in verified["blocks"]}
    actual_wires = [
        (indices[z["source_ref"]], z["source_port"], indices[z["target_ref"]], z["target_port"])
        for z in verified["connections"]
    ]
    if (
        rebuilt.reader.errors
        or rebuilt.instance != app.instance
        or verified["execution_order"] != order
        or actual_wires != connections
        or len(rebuilt.records) != len(records) + len(additions)
        or [z["ref"] for z in verified["blocks"][:orig_size]] != [z["ref"] for z in members]
    ):
        raise ValueError("Reparsed application differs from the reviewed interlock.")
    for left, right in zip(app.records, rebuilt.records[: len(records)], strict=True):
        if left["offset"] != root["offset"] and left["sha256"] != right["sha256"]:
            raise ValueError("An unrelated native record changed.")
    return out, {
        "profile": "native-inline-airflow-permissive/1",
        "source_sha256": sha(source),
        "candidate_sha256": sha(out),
        "threshold_cfm": threshold,
        "diagram": diagram_ref,
        "blocks": names,
        "new_records": len(additions),
        "added_connections": len(new_wires),
        "changed_enable_connection": original_index,
        "changed_valve_connection": valve_wire_index,
        "valve": read(outputs[0], 75),
        "valve_terminal": read(outputs[0], 990),
        "verified_graph": True,
        "field_verified": False,
    }


def local_copy(options):
    paths = (options.application, options.static, options.dynamic)
    limits = (MAX_SOURCE, 128 * 1024, 128 * 1024)
    if len({p.resolve() for p in paths}) != 3 or any(
        not 0 < p.stat().st_size <= cap for p, cap in zip(paths, limits, strict=True)
    ):
        raise ValueError("Supply three distinct bounded native backup files.")
    files = [path.read_bytes() for path in paths]
    effective, _ = ParameterApplication(*files).compile()
    candidate, report = compile_permissive(
        effective,
        source_sha256=sha(effective),
        diagram_ref=options.diagram,
        pressure_ref=options.pressure,
        flow_ref=options.flow,
        enable_ref=options.enable,
        passthrough_ref=options.passthrough,
        valve_ref=options.valve,
        threshold_cfm=options.threshold_cfm,
        first_instance=options.first_instance,
    )
    report["original_files_sha256"] = [sha(data) for data in files]
    digest = seal(report)
    if options.output is not None:
        if options.review_sha256 != digest:
            raise ValueError(
                "Review these backup files, signal bindings and threshold before saving the candidate."
            )
        with options.output.open("xb") as stream:
            stream.write(candidate)
    return {**report, "review_sha256": digest, "local_copy_saved": options.output is not None}
