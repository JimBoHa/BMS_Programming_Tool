"""Explicit interchange formats. Vendor extensions are never silently discarded."""

from __future__ import annotations

import base64
import hashlib
import re
import struct
import xml.etree.ElementTree as XML

from defusedxml import ElementTree as SafeXML

from .blocks import BLOCKS
from .engine import execution_order, output_type, validate
from .models import Program, canonical

PLC = "http://www.plcopen.org/xml/tc6_0201"
XHTML = "http://www.w3.org/1999/xhtml"
BMS = "urn:bms-studio:program:1"


class ConversionError(ValueError):
    pass


def _check(program):
    if "native_sedona" in program.metadata:
        raise ConversionError(
            "This project contains additional native Sedona components. Export JSON or native Sedona; portable export would omit native logic."
        )
    errors = [d.message for d in validate(program) if d.level == "error"]
    if errors:
        raise ConversionError("; ".join(errors))


def _literal(v):
    if type(v) is bool:
        return "TRUE" if v else "FALSE"
    if type(v) not in (int, float):
        raise ConversionError("Cannot export nonnumeric/nonboolean literal.")
    try:
        encoded = struct.unpack(">f", struct.pack(">f", v))[0]
    except (OverflowError, struct.error) as exc:
        raise ConversionError("Literal exceeds the IEC REAL 32-bit range.") from exc
    if v != 0 and encoded == 0:
        raise ConversionError("Literal underflows the IEC REAL 32-bit range.")
    s = format(v, ".15g")
    return s if any(c in s.lower() for c in ".e") else s + ".0"


def structured_text_parts(program):
    from .macros import expand_macros

    program = expand_macros(program)
    _check(program)
    nodes = {n.id: n for n in program.nodes}
    links = {(e.target, e.target_port): e.source for e in program.edges}
    # Prefix every name; preserve a reversible map without colliding with IEC keywords.
    names = {n.id: "n_" + re.sub("[^A-Za-z0-9_]", "_", n.id) for n in program.nodes}
    if len(set(x.casefold() for x in names.values())) != len(names):
        raise ConversionError("Node identifiers collide under case-insensitive IEC naming.")
    declarations = {"inputVars": [], "outputVars": [], "localVars": []}
    declarations["inputVars"] += [
        ("StudioScanSeconds", "REAL", _literal(program.scan_seconds)),
        ("StudioDayOfWeek", "INT", "0"),
        ("StudioMinuteOfDay", "INT", "0"),
    ]
    declarations["outputVars"].append(("StudioFault", "BOOL", "FALSE"))
    for n in program.nodes:
        group = (
            "inputVars"
            if n.kind == "Input"
            else "outputVars"
            if n.kind == "Output"
            else "localVars"
        )
        initial = (
            _literal(n.params.get("default", False if output_type(n) == "boolean" else 0))
            if n.kind == "Input"
            else None
        )
        declarations[group].append(
            (names[n.id], "BOOL" if output_type(n) == "boolean" else "REAL", initial)
        )
        if n.kind == "Output":
            names[n.id] += "_stage"
            declarations["localVars"].append(
                (names[n.id], "BOOL" if output_type(n) == "boolean" else "REAL", None)
            )
        if n.kind == "Input":
            declarations["inputVars"].append((names[n.id] + "_valid", "BOOL", "TRUE"))
        if n.kind == "Schedule" and (n.params.get("timezone") or n.params.get("exceptions")):
            # Full calendar evaluation belongs to the destination host. A false
            # default validity flag prevents an unbound calendar publishing output.
            declarations["inputVars"] += [
                (names[n.id] + "_calendar", "BOOL", "FALSE"),
                (names[n.id] + "_calendar_valid", "BOOL", "FALSE"),
            ]
    lines = [
        "(* BMS Studio scan. Inputs and clock are supplied by the target runtime. *)",
        "StudioFault := FALSE;",
        "IF (StudioScanSeconds <= 0.0) OR (StudioScanSeconds > 60.0) THEN StudioFault := TRUE; RETURN; END_IF;",
    ]
    for n in program.nodes:
        if n.kind == "Schedule" and (n.params.get("timezone") or n.params.get("exceptions")):
            lines.append(
                f"IF NOT {names[n.id]}_calendar_valid THEN StudioFault := TRUE; RETURN; END_IF;"
            )
        if n.kind == "Input":
            test = "NOT " + names[n.id] + "_valid"
            if output_type(n) == "number":
                test += (
                    " OR ("
                    + names[n.id]
                    + " <> "
                    + names[n.id]
                    + ") OR (ABS("
                    + names[n.id]
                    + ") > 3.0E+38)"
                )
            lines.append(f"IF {test} THEN StudioFault := TRUE; RETURN; END_IF;")
    outputs = []
    commits = []

    def declare(name, kind="REAL", initial="0.0"):
        declarations["localVars"].append((name, kind, initial))

    for id in execution_order(program):
        n = nodes[id]
        k = n.kind
        name = names[id]
        p = {**BLOCKS[k].parameters, **n.params}

        def a(port, current_node=id):
            return names[links[(current_node, port)]]

        def lit(key, parameters=p):
            return _literal(parameters[key])

        expression = None
        if k == "Input":
            continue
        elif k == "Output":
            expression = a("in")
            outputs.append(f"{name.removesuffix('_stage')} := {name};")
        elif k == "Constant":
            expression = lit("value")
        elif k in (
            "Add",
            "Subtract",
            "Multiply",
            "Divide",
            "Greater",
            "Less",
            "Equal",
            "And",
            "Or",
        ):
            op = {
                "Add": "+",
                "Subtract": "-",
                "Multiply": "*",
                "Divide": "/",
                "Greater": ">",
                "Less": "<",
                "Equal": "=",
                "And": "AND",
                "Or": "OR",
            }[k]
            if k == "Divide":
                lines.append(f"IF {a('b')} = 0.0 THEN StudioFault := TRUE; RETURN; END_IF;")
            expression = f"{a('a')} {op} {a('b')}"
        elif k in ("Min", "Max"):
            expression = f"{k.upper()}({a('a')}, {a('b')})"
        elif k == "Abs":
            expression = f"ABS({a('in')})"
        elif k == "Not":
            expression = f"NOT {a('in')}"
        elif k == "Clamp":
            expression = f"MAX({lit('min')}, MIN({lit('max')}, {a('in')}))"
        elif k == "Scale":
            ratio = f"(({a('in')} - {lit('in_min')}) / ({lit('in_max')} - {lit('in_min')}))"
            if p["clamp"]:
                ratio = f"MAX(0.0, MIN(1.0, {ratio}))"
            expression = f"{lit('out_min')} + {ratio} * ({lit('out_max')} - {lit('out_min')})"
        elif k == "Convert":
            c = (
                f"(({a('in')} - 32.0) * 5.0 / 9.0)"
                if p["from"] == "degF"
                else f"({a('in')} - 273.15)"
                if p["from"] == "K"
                else a("in")
            )
            expression = (
                f"({c} * 9.0 / 5.0 + 32.0)"
                if p["to"] == "degF"
                else f"({c} + 273.15)"
                if p["to"] == "K"
                else c
            )
        elif k == "Switch":
            lines.append(
                f"IF {a('select')} THEN {name} := {a('on')}; ELSE {name} := {a('off')}; END_IF;"
            )
        elif k == "Delay":
            declare(
                name + "_memory",
                "BOOL" if output_type(n) == "boolean" else "REAL",
                lit("initial"),
            )
            expression = name + "_memory"
            commits.append(f"{name}_memory := {a('in')};")
        elif k == "PI":
            for suffix in ("integral", "candidate", "error", "raw"):
                declare(name + "_" + suffix)
            lines.extend(
                [
                    f"{name}_error := ({a('setpoint')} - {a('measured')}) * {'-1.0' if p['reverse'] else '1.0'};",
                    f"{name}_candidate := {name}_integral + {lit('ki')} * {name}_error * StudioScanSeconds;",
                    f"{name}_raw := {lit('kp')} * {name}_error + {name}_candidate;",
                    f"IF (({name}_raw >= {lit('min')}) AND ({name}_raw <= {lit('max')})) OR (({name}_raw > {lit('max')}) AND ({name}_error * {lit('ki')} < 0.0)) OR (({name}_raw < {lit('min')}) AND ({name}_error * {lit('ki')} > 0.0)) THEN",
                    f"  {name} := MAX({lit('min')}, MIN({lit('max')}, {lit('kp')} * {name}_error + {name}_candidate));",
                    "ELSE",
                    f"  {name}_candidate := {name}_integral;",
                    f"  {name} := MAX({lit('min')}, MIN({lit('max')}, {lit('kp')} * {name}_error + {name}_integral));",
                    "END_IF;",
                ]
            )
            commits.append(f"{name}_integral := {name}_candidate;")
        elif k == "Deadband":
            declare(name + "_memory", "BOOL", lit("initial"))
            lines.extend(
                [
                    f"{name} := {name}_memory;",
                    f"IF {a('in')} >= {lit('on')} THEN {name} := TRUE; ELSIF {a('in')} <= {lit('off')} THEN {name} := FALSE; END_IF;",
                ]
            )
            commits.append(f"{name}_memory := {name};")
        elif k in ("TimerOn", "Alarm"):
            declare(name + "_elapsed")
            declare(name + "_next")
            condition = a("in") if k == "TimerOn" else f"{a('in')} > {lit('limit')}"
            duration = lit("seconds" if k == "TimerOn" else "delay")
            lines.extend(
                [
                    f"IF {condition} THEN {name}_next := {name}_elapsed + StudioScanSeconds; ELSE {name}_next := 0.0; END_IF;",
                    f"{name} := ({condition}) AND ({name}_next >= {duration});",
                ]
            )
            commits.append(f"{name}_elapsed := {name}_next;")
        elif k == "Slew":
            declare(name + "_memory", "REAL", lit("initial"))
            expression = f"{name}_memory + MAX(-({lit('rate')} * StudioScanSeconds), MIN({lit('rate')} * StudioScanSeconds, {a('in')} - {name}_memory))"
            commits.append(f"{name}_memory := {name};")
        elif k == "Schedule":
            if p["timezone"] or p["exceptions"]:
                expression = name + "_calendar"
                lines.append(
                    "(* Host evaluates the project's IANA timezone and dated exceptions; mark valid only for the current scan. *)"
                )
                lines.append(f"{name} := {expression};")
                continue
            start = sum(int(v) * m for v, m in zip(p["start"].split(":"), (60, 1), strict=True))
            end = sum(int(v) * m for v, m in zip(p["end"].split(":"), (60, 1), strict=True))
            days = " OR ".join(f"(StudioDayOfWeek = {d})" for d in p["days"]) or "FALSE"
            prior = " OR ".join(f"(StudioDayOfWeek = {(d + 1) % 7})" for d in p["days"]) or "FALSE"
            expression = (
                f"({days}) AND (StudioMinuteOfDay >= {start}) AND (StudioMinuteOfDay < {end})"
                if start <= end
                else f"(({days}) AND (StudioMinuteOfDay >= {start})) OR (({prior}) AND (StudioMinuteOfDay < {end}))"
            )
        else:
            raise ConversionError("No ST code generator for " + k)
        if expression is not None:
            lines.append(f"{name} := {expression};")
        if output_type(n) == "number":
            lines.append(
                f"IF ({name} <> {name}) OR (ABS({name}) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;"
            )
    lines += ["(* Commit state and outputs only after every block succeeds. *)"] + commits + outputs
    return declarations, "\n".join(lines)


def export_st(program, embedded=True):
    declarations, body = structured_text_parts(program)
    text = "PROGRAM MAIN\n"
    for category, keyword in [
        ("inputVars", "VAR_INPUT"),
        ("outputVars", "VAR_OUTPUT"),
        ("localVars", "VAR"),
    ]:
        text += keyword + "\n"
        for name, kind, initial in declarations[category]:
            text += f"  {name} : {kind}" + (" := " + initial if initial is not None else "") + ";\n"
        text += "END_VAR\n"
    text += body + "\nEND_PROGRAM\n"
    if embedded:
        text += "(* BMS_STUDIO_IR_V1 " + base64.b64encode(canonical(program)).decode() + " *)\n"
    return text.encode()


def export_plcopen(program):
    declarations, body = structured_text_parts(program)
    XML.register_namespace("", PLC)
    XML.register_namespace("xhtml", XHTML)
    XML.register_namespace("bms", BMS)

    def child(parent, tag, attributes=None):
        return XML.SubElement(parent, "{" + PLC + "}" + tag, attributes or {})

    root = XML.Element("{" + PLC + "}project")
    child(
        root,
        "fileHeader",
        {
            "companyName": "BMS Studio",
            "productName": "BMS Studio",
            "productVersion": "0.1.0",
            "creationDateTime": "2026-10-18T00:00:00Z",
        },
    )
    header = child(root, "contentHeader", {"name": program.name})
    coords = child(header, "coordinateInfo")
    for language in ("fbd", "ld", "sfc"):
        child(child(coords, language), "scaling", {"x": "1", "y": "1"})
    types = child(root, "types")
    child(types, "dataTypes")
    pous = child(types, "pous")
    pou = child(pous, "pou", {"name": "MAIN", "pouType": "program"})
    interface = child(pou, "interface")
    for category, variables in declarations.items():
        group = child(interface, category)
        for name, kind, initial in variables:
            var = child(group, "variable", {"name": name})
            child(child(var, "type"), kind)
            if initial is not None:
                child(child(var, "initialValue"), "simpleValue", {"value": initial})
    p = XML.SubElement(child(child(pou, "body"), "ST"), "{" + XHTML + "}p")
    p.text = body
    child(child(root, "instances"), "configurations")
    data = child(child(root, "addData"), "data", {"name": BMS, "handleUnknown": "implementation"})
    ir = XML.SubElement(
        data,
        "{" + BMS + "}program",
        {"sha256": hashlib.sha256(canonical(program)).hexdigest()},
    )
    ir.text = base64.b64encode(canonical(program)).decode()
    return XML.tostring(root, encoding="utf-8", xml_declaration=True)


def export_graphml(program):
    _check(program)
    namespace = "http://graphml.graphdrawing.org/xmlns"
    root = XML.Element("graphml", {"xmlns": namespace})
    XML.SubElement(
        root,
        "key",
        {"id": "ir", "for": "graph", "attr.name": "bms_program", "attr.type": "string"},
    )
    graph = XML.SubElement(root, "graph", {"id": program.id, "edgedefault": "directed"})
    XML.SubElement(graph, "data", {"key": "ir"}).text = canonical(program).decode()
    for n in program.nodes:
        XML.SubElement(graph, "node", {"id": n.id})
    for e in program.edges:
        XML.SubElement(graph, "edge", {"id": e.id, "source": e.source, "target": e.target})
    return XML.tostring(root, encoding="utf-8", xml_declaration=True)


def export_program(program, format):
    if format == "sedona":
        from .sedona import export_bundle

        return export_bundle(program), "application/zip", "sedona.zip"
    if format in ("sedona-sax", "sedona-sab"):
        import tempfile
        from pathlib import Path

        from .sedona import compile_program

        with tempfile.TemporaryDirectory(prefix="bms-sedona-export-") as tmp:
            compile_program(program, tmp)
            extension = format.removeprefix("sedona-")
            return (
                (Path(tmp) / ("app." + extension)).read_bytes(),
                "application/octet-stream",
                extension,
            )
    if format == "json":
        return canonical(program), "application/json", "bms.json"
    if format == "st":
        return export_st(program), "text/plain", "st"
    if format == "plcopen":
        return export_plcopen(program), "application/xml", "xml"
    if format == "graphml":
        return export_graphml(program), "application/xml", "graphml"
    raise ConversionError(
        f"Export format {format!r} has no verified encoder. Native CAF, ALC, Spyder and Niagara compilation require separate adapters."
    )


def import_program(content, filename):
    if len(content) > 8 * 1024 * 1024:
        raise ConversionError("Import exceeds 8 MiB.")
    name = filename.lower()
    if name.endswith(".sedona.zip"):
        from .sedona import import_bundle

        return import_bundle(content)
    if name.endswith((".sax", ".sab")):
        from .sedona_import import decode_sab, import_sax

        return (
            import_sax(decode_sab(content), source_kind="SAB")
            if name.endswith(".sab")
            else import_sax(content)
        )
    if name.endswith(".json"):
        return Program.model_validate_json(content)
    if name.endswith(".st"):
        match = re.search(rb"\(\* BMS_STUDIO_IR_V1 ([A-Za-z0-9+/=]+) \*\)", content)
        if not match:
            raise ConversionError(
                "ST import currently supports BMS Studio generated files, not arbitrary IEC source."
            )
        program = Program.model_validate_json(base64.b64decode(match.group(1), validate=True))
        if export_st(program) != content:
            raise ConversionError(
                "ST source was edited outside Studio. Embedded graph no longer matches; import refused."
            )
        return program
    if name.endswith((".xml", ".graphml")):
        root = SafeXML.fromstring(content)
        if root.tag == "{" + PLC + "}project":
            ir = root.find(".//{" + BMS + "}program")
            if ir is None:
                raise ConversionError(
                    "PLCopen import currently supports Studio-generated projects with graph metadata. Arbitrary vendor PLCopen requires a schema/semantic adapter."
                )
            program = Program.model_validate_json(base64.b64decode(ir.text or "", validate=True))
            if export_plcopen(program) != content:
                raise ConversionError(
                    "PLCopen source or metadata differs from the embedded graph; import refused."
                )
            return program
        if root.tag == "{http://graphml.graphdrawing.org/xmlns}graphml":
            graph = root.find("{http://graphml.graphdrawing.org/xmlns}graph")
            ir = (
                graph.find("{http://graphml.graphdrawing.org/xmlns}data")
                if graph is not None
                else None
            )
            if ir is None:
                raise ConversionError("GraphML lacks BMS graph metadata.")
            program = Program.model_validate_json(ir.text or "")
            if export_graphml(program) != content:
                raise ConversionError(
                    "GraphML structure differs from embedded graph; import refused."
                )
            return program
    raise ConversionError(
        "Unrecognized import format. CAF inspection uses the separate loss-preserving CAF adapter."
    )
