"""Niagara BOG archive preservation and bounded native kitControl interchange.

The encoding follows Tridium's BOG documentation and the public MIT pybog
reference at 0248d941bf230aad2f19f9805be67c0e64bd51ef. No Niagara SDK is bundled.
Native BOG is event-driven: neither import nor export claims atomic scan or
fault equivalence. Unknown executable components stop semantic conversion.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException

from .blocks import BLOCKS
from .engine import input_type, output_type, validate
from .formats import ConversionError
from .macros import expand_macros
from .models import Edge, Node, Program, canonical
from .temperature import ABSOLUTE_UNITS, DELTA_FOR_ABSOLUTE, DELTA_UNITS

NATIVE = {
    "Add": ("kitControl:Add", {"a": "inA", "b": "inB"}),
    "Subtract": ("kitControl:Subtract", {"a": "inA", "b": "inB"}),
    "Multiply": ("kitControl:Multiply", {"a": "inA", "b": "inB"}),
    "Divide": ("kitControl:Divide", {"a": "inA", "b": "inB"}),
    "Min": ("kitControl:Minimum", {"a": "inA", "b": "inB"}),
    "Max": ("kitControl:Maximum", {"a": "inA", "b": "inB"}),
    "Abs": ("kitControl:AbsValue", {"in": "inA"}),
    "Greater": ("kitControl:GreaterThan", {"a": "inA", "b": "inB"}),
    "Less": ("kitControl:LessThan", {"a": "inA", "b": "inB"}),
    "Equal": ("kitControl:Equal", {"a": "inA", "b": "inB"}),
    "And": ("kitControl:And", {"a": "inA", "b": "inB"}),
    "Or": ("kitControl:Or", {"a": "inA", "b": "inB"}),
    "Not": ("kitControl:Not", {"in": "in"}),
    "Scale": ("kitControl:Reset", {"in": "inA"}),
    "Convert": ("kitControl:NumericUnitConverter", {"in": "in"}),
    "DeltaConvert": ("kitControl:NumericUnitConverter", {"in": "in"}),
}
REVERSE = {
    typ: (kind, {v: k for k, v in ports.items()})
    for kind, (typ, ports) in NATIVE.items()
    if kind != "DeltaConvert"
}
SUPPORTED = {
    *NATIVE,
    "Input",
    "Output",
    "Constant",
    "Switch",
    "Clamp",
    "TemperatureDifference",
    "TemperatureOffset",
}
RESET_LIMITS = {
    "in_min": "inputLowLimit",
    "in_max": "inputHighLimit",
    "out_min": "outputLowLimit",
    "out_max": "outputHighLimit",
}
REDUCTIONS = {"Add", "Multiply", "Min", "Max", "And", "Or"}
FOLDERS = {
    f"{module}:{name}" for module in ("baja", "b") for name in ("Folder", "UnrestrictedFolder")
}
VALUE_TYPES = {
    f"{module}:{name}"
    for module in ("baja", "b")
    for name in (
        "String",
        "Boolean",
        "Double",
        "Float",
        "Integer",
        "Long",
        "StatusNumeric",
        "StatusBoolean",
        "Status",
        "Facets",
        "WsAnnotation",
        "Ord",
    )
}
UNITS = {
    "": "null;;;;",
    "degF": "fahrenheit;\N{DEGREE SIGN}F;(K);*0.5555555555555556+255.37222222222223;",
    "degC": "celsius;\N{DEGREE SIGN}C;(K);+273.15;",
    "K": "kelvin;K;(K);;",
    "delta-degF": "fahrenheit degrees;Δ°F;(K);*0.5555555555555556;",
    "delta-degC": "celsius degrees;Δ°C;(K);;",
    "delta-K": "kelvin degrees;Δ°K;(K);;",
    "%": "percent;%;;;",
    "cfm": "cubic feet per minute;cfm;(m3)(s-1);*4.719474432E-4;",
}
SOURCE = re.compile(rb"<!-- BMS_STUDIO_BOG_V1 ([A-Za-z0-9+/=]+) -->")
DIFFERENCES = [
    "Niagara links update on events; Studio uses deterministic complete scans. Intermediate native values can be visible.",
    "Native status/null/priority and bad-quality behavior differs from Studio's finite values and failed-scan output hold.",
    "Writable outputs bind at native priority 16; existing higher-priority commands can take precedence.",
    "This conversion does not configure physical I/O, alarms, histories, drivers or station credentials.",
    "Native station/Workbench acceptance and execution have not been verified in this environment.",
]
EXTENDED_DIFFERENCES = [
    "Reset scaling and unit conversions can round differently from Studio; finite steady-state comparisons do not establish event/status or overflow equivalence.",
]


def _scalar(value, boolean=False):
    if boolean:
        if type(value) is bool:
            return value
        if value in ("true", "false"):
            return value == "true"
        raise ConversionError(
            "Native Boolean value must be true or false, without null/status coercion."
        )
    if type(value) is bool:
        raise ConversionError("Native numeric value cannot be Boolean.")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConversionError("Native numeric value must be finite.") from exc
    if not math.isfinite(number):
        raise ConversionError("Native numeric value must be finite.")
    return number


def _value(element, name, default=None):
    matches = [p for p in element.findall("p") if p.get("n") == name]
    if len(matches) > 1:
        raise ConversionError("Duplicate native property: " + name)
    if not matches:
        return default
    child = matches[0]
    if "v" in child.attrib:
        if len(child):
            raise ConversionError("Native scalar mixes attribute and nested encodings.")
        return child.get("v")
    if any(p.tag != "p" or p.get("n") not in ("value", "status") for p in child):
        raise ConversionError("Unsupported nested native value configuration would be lost.")
    statuses = child.findall("./p[@n='status']")
    if len(statuses) > 1:
        raise ConversionError("Duplicate native status property.")
    if statuses:
        status = statuses[0]
        if len(status) or "v" not in status.attrib:
            raise ConversionError("Unsupported native status encoding.")
        if status.get("v", "0").split(";", 1)[0] != "0":
            raise ConversionError(
                "Non-good native status cannot be converted to a finite initial value."
            )
        if any(status.get("v", "0").split(";")[1:]):
            raise ConversionError("Unsupported native status facets would be lost.")
    return _value(child, "value", default)


def _status_value(element, name, types, boolean=False, default=None):
    matches = [p for p in element.findall("p") if p.get("n") == name]
    if len(matches) > 1:
        raise ConversionError("Duplicate native property: " + name)
    if matches:
        child = matches[0]
        if "v" in child.attrib:
            if len(child):
                raise ConversionError("Native scalar mixes attribute and nested encodings.")
            raise ConversionError(
                "Native status-valued slots require nested value/status properties; a compact scalar is ignored by Niagara."
            )
        expected = "baja:StatusBoolean" if boolean else "baja:StatusNumeric"
        if child.get("t") and types.get(id(child)) != expected:
            raise ConversionError("Native status slot has an incompatible explicit type.")
        for value in child.findall("p"):
            if value.get("n") == "value":
                expected_value = "baja:Boolean" if boolean else "baja:Double"
            elif value.get("n") == "status":
                expected_value = "baja:Status"
            else:
                continue  # _value reports unknown nested configuration below.
            if value.get("t") and types.get(id(value)) != expected_value:
                raise ConversionError("Native status field has an incompatible explicit type.")
    return _value(element, name, default)


def _modules(declarations, inherited):
    modules = dict(inherited)
    declared = set()
    for declaration in declarations.split(";"):
        if not declaration:
            continue
        separator = "=" if "=" in declaration else ":" if ":" in declaration else None
        if separator is None:
            raise ConversionError("Unrecognized native module alias declaration.")
        alias, module = declaration.split(separator, 1)
        if not alias or not module or alias in declared:
            raise ConversionError("Empty or duplicate native module alias declaration.")
        declared.add(alias)
        modules[alias] = module
    return modules


def _native_unit(encoded):
    """Validate the finite observed unit profile, including dimension and transform.

    BUnit values are four semicolon-terminated fields. A display name alone
    cannot identify the physical unit or replace its scale and offset.
    """
    fields = encoded.split(";")
    if len(fields) != 5 or fields[-1]:
        raise ConversionError("Native unit facets require a complete serialized BUnit record.")
    known = {value.split(";", 1)[0]: (key, value.split(";")) for key, value in UNITS.items()}
    if fields[0] not in known:
        raise ConversionError("Unknown native unit facets require explicit conversion.")
    unit, expected = known[fields[0]]
    if fields[2] != expected[2] or fields[1] not in {"", expected[0], expected[1]}:
        raise ConversionError("Native unit symbol/dimension is outside the supported profile.")

    def transform(text):
        number = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"
        match = re.fullmatch(r"(?:\*(" + number + r"))?(?:\+(" + number + r"))?", text)
        if not match:
            raise ConversionError("Unsupported native unit scale/offset encoding.")
        scale, offset = float(match[1] or 1), float(match[2] or 0)
        if not math.isfinite(scale) or not math.isfinite(offset):
            raise ConversionError("Native unit scale/offset must be finite.")
        return scale, offset

    if transform(fields[3]) != transform(expected[3]):
        raise ConversionError("Native unit scale/offset differs from the supported physical unit.")
    return unit


def _unit_facets(facets):
    if not facets:
        return ""
    unit, seen = "", set()
    for part in facets.split("|"):
        key = part.split("=", 1)[0]
        if key in seen:
            raise ConversionError("Duplicate native facet key.")
        seen.add(key)
        if part.startswith("units=u:"):
            unit = _native_unit(part[len("units=u:") :])
        elif part not in ("min=d:-inf", "max=d:+inf") and not re.fullmatch(
            r"precision=i:[0-9]{1,2}", part
        ):
            raise ConversionError("Unsupported native facet configuration would be lost: " + part)
    return unit


class NiagaraArchive:
    """Preserve raw XML or ZIP BOG, including unknown archive members."""

    def __init__(self, content: bytes):
        if not content or len(content) > 8 * 1024 * 1024:
            raise ConversionError("BOG must contain 1 byte through 8 MiB.")
        self.original = content
        self.hash = hashlib.sha256(content).hexdigest()
        self.zipped = content.startswith(b"PK")
        self.infos, self.members, self.comment = [], {}, b""
        try:
            if self.zipped:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    infos = archive.infolist()
                    if len(infos) > 64 or len({i.filename for i in infos}) != len(infos):
                        raise ConversionError("BOG archive has too many or duplicate members.")
                    if sum(i.file_size for i in infos) > 32 * 1024 * 1024 or any(
                        i.flag_bits & 1 for i in infos
                    ):
                        raise ConversionError("BOG archive is encrypted or expands beyond 32 MiB.")
                    if "file.xml" not in archive.namelist():
                        raise ConversionError("Native BOG ZIP requires file.xml at its root.")
                    self.infos = infos
                    self.members = {i.filename: archive.read(i) for i in infos}
                    self.comment = archive.comment
                    self.xml = self.members["file.xml"]
            else:
                self.xml = content
            self.root = SafeXML.fromstring(self.xml)
        except (
            zipfile.BadZipFile,
            ET.ParseError,
            DefusedXmlException,
            RuntimeError,
            zlib.error,
        ) as exc:
            raise ConversionError("Malformed or unsafe BOG archive/XML.") from exc
        if self.root.tag != "bajaObjectGraph" or self.root.get("version") not in ("1.0", "4.0"):
            raise ConversionError("Expected Niagara bajaObjectGraph version 1.0 or 4.0.")
        pending, count = [(self.root, 0)], 0
        while pending:
            element, depth = pending.pop()
            count += 1
            if depth > 48 or count > 50000:
                raise ConversionError("BOG exceeds XML depth/element limits.")
            pending.extend((child, depth + 1) for child in element)
        self.components, self.links, self.by_handle, self.by_path = [], [], {}, {}
        self.unhandled, self.value_types = [], {}
        self._walk(self.root, "", _modules(self.root.get("m", ""), {}), 0)
        for link in self.links:
            source = link["source_ord"]
            if source.startswith("h:"):
                handle = source[2:]
            elif source.startswith("slot:") and "|" not in source:
                relative = source[5:]
                path = posixpath.normpath(
                    relative if relative.startswith("/") else link["target_path"] + "/" + relative
                )
                handle = self.by_path.get(path, {}).get("handle")
            else:
                handle = None
            link["source"] = handle
            link["resolved"] = handle in self.by_handle

    def _walk(self, parent, path, inherited, depth):
        if depth > 48:
            raise ConversionError("BOG nesting exceeds 48 levels.")
        for element in parent.findall("p"):
            if len(self.components) + len(self.links) > 10000:
                raise ConversionError("BOG exceeds 10,000 components/links.")
            # BOG declarations apply to the remainder of the document, including
            # following siblings and parents' following siblings. They are not
            # XML namespace declarations with lexical scope.
            inherited.update(_modules(element.get("m", ""), inherited))
            modules = inherited
            typ = element.get("t", "")
            if ":" in typ:
                prefix, name = typ.split(":", 1)
                typ = modules.get(prefix, prefix) + ":" + name
            self.value_types[id(element)] = typ
            name = element.get("n", "")
            if typ in ("baja:Link", "baja:ConversionLink", "b:Link", "b:ConversionLink"):
                self.links.append(
                    {
                        "name": name,
                        "target": parent.get("h"),
                        "target_path": path,
                        "type": typ,
                        "source_ord": _value(element, "sourceOrd", ""),
                        "source_slot": _value(element, "sourceSlotName", ""),
                        "target_slot": _value(element, "targetSlotName", ""),
                        "converter": element.find("./p[@n='converter']") is not None,
                        "relation_id": _value(element, "relationId", "n:dataLink"),
                        "relation_tags": _value(element, "relationTags", ""),
                        "unknown_properties": [
                            prop.get("n", "<unnamed>")
                            for prop in element
                            if prop.tag != "p"
                            or prop.get("n")
                            not in {
                                "sourceOrd",
                                "sourceSlotName",
                                "targetSlotName",
                                "converter",
                                "relationId",
                                "relationTags",
                            }
                        ],
                    }
                )
                continue
            handle = element.get("h")
            if handle is not None:
                if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", handle) or handle in self.by_handle:
                    raise ConversionError("Invalid or duplicate Niagara component handle.")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,159}", name or "Root"):
                    raise ConversionError("Unsupported native component name encoding.")
                current = path + "/" + (name or "Root")
                if current in self.by_path:
                    raise ConversionError("Duplicate Niagara component path.")
                record = {
                    "handle": handle,
                    "path": current,
                    "name": name or "Root",
                    "type": typ,
                    "element": element,
                }
                self.components.append(record)
                self.by_handle[handle] = self.by_path[current] = record
                self._walk(element, current, modules, depth + 1)
            elif typ in FOLDERS:
                self._walk(element, path + "/" + (name or "Root"), modules, depth + 1)
            elif element.findall(".//p[@h]"):
                raise ConversionError("Component nesting without a handle is ambiguous.")
            else:
                if typ and typ not in VALUE_TYPES:
                    self.unhandled.append({"path": path + "/" + name, "type": typ})
                self._walk(element, path + "/" + name, modules, depth + 1)

    def summary(self):
        return {
            "sha256": self.hash,
            "components": [{k: v for k, v in r.items() if k != "element"} for r in self.components],
            "links": self.links,
            "unhandled_typed_records": self.unhandled,
            "members": list(self.members),
            "encoding": self.root.get("reversibleEncodingKeySource", "none"),
            "validation": "Offline BOG structure; station compilation/execution unverified",
        }

    def export(self):
        return self.original


def _lower_composites(graph: Program):
    """Lower finite Clamp/unclamped Scale using documented existing primitives.

    Clamped Scale with matching input/output units remains a native Reset. Its
    single facets slot describes its input; differing engineering units need a
    composite with independently faceted intermediate/output components. Reset
    always clamps and must never represent an extrapolating Scale. Source-free
    import exposes composites as their ordinary native primitives.
    """
    nodes, edges = [], [edge.model_copy(deep=True) for edge in graph.edges]
    reserved_nodes, reserved_edges = {n.id for n in graph.nodes}, {e.id for e in edges}
    by_id = {n.id: n for n in graph.nodes}

    def identifier(reserved, prefix):
        index = len(reserved)
        while (candidate := prefix + str(index)) in reserved:
            index += 1
        reserved.add(candidate)
        return candidate

    def add(kind, unit, *, value=None, parent):
        if len(reserved_nodes) >= min(2000, graph.target.max_nodes):
            raise ConversionError("Niagara composite expansion exceeds the target node limit.")
        node = Node(
            id=identifier(reserved_nodes, "niagara_lower_"),
            kind=kind,
            unit=unit,
            params={} if value is None else {"value": _scalar(value)},
            x=parent.x - 180,
            y=parent.y,
            label=("Native " + kind + " for " + (parent.label or parent.id))[:200],
        )
        nodes.append(node)
        return node.id

    def wire(source, target, port):
        if len(edges) >= 10000:
            raise ConversionError("Niagara composite expansion exceeds 10,000 edges.")
        edges.append(
            Edge(
                id=identifier(reserved_edges, "niagara_edge_"),
                source=source,
                target=target,
                target_port=port,
            )
        )

    for node in graph.nodes:
        params = {**BLOCKS[node.kind].parameters, **node.params}
        input_unit = None
        if node.kind == "Scale":
            incoming = next(e for e in graph.edges if e.target == node.id)
            input_unit = by_id[incoming.source].unit
        if node.kind == "TemperatureDifference":
            nodes.append(node.model_copy(deep=True, update={"kind": "Subtract", "params": {}}))
        elif node.kind == "TemperatureOffset":
            delta_unit = DELTA_FOR_ABSOLUTE[params["unit"]]
            converter = None
            if params["difference_unit"] != delta_unit:
                converter = add("DeltaConvert", delta_unit, parent=node)
                nodes[-1].params = {"from": params["difference_unit"], "to": delta_unit}
            nodes.append(node.model_copy(deep=True, update={"kind": "Add", "params": {}}))
            for edge in edges:
                if edge.target == node.id:
                    if edge.target_port == "base":
                        edge.target_port = "a"
                    elif converter:
                        edge.target, edge.target_port = converter, "in"
                    else:
                        edge.target_port = "b"
            if converter:
                wire(converter, node.id, "b")
        elif node.kind == "Clamp":
            minimum = add("Min", node.unit, parent=node)
            lower = add("Constant", node.unit, value=params["min"], parent=node)
            upper = add("Constant", node.unit, value=params["max"], parent=node)
            nodes.append(node.model_copy(deep=True, update={"kind": "Max", "params": {}}))
            for edge in edges:
                if edge.target == node.id:
                    edge.target, edge.target_port = minimum, "a"
            wire(upper, minimum, "b")
            wire(minimum, node.id, "a")
            wire(lower, node.id, "b")
        elif node.kind == "Scale" and (not params["clamp"] or input_unit != node.unit):
            subtract = add("Subtract", input_unit, parent=node)
            divide = add("Divide", "", parent=node)
            multiply = add("Multiply", node.unit, parent=node)
            in_min = add("Constant", input_unit, value=params["in_min"], parent=node)
            in_span = add(
                "Constant", input_unit, value=params["in_max"] - params["in_min"], parent=node
            )
            out_span = add(
                "Constant", node.unit, value=params["out_max"] - params["out_min"], parent=node
            )
            out_min = add("Constant", node.unit, value=params["out_min"], parent=node)
            nodes.append(node.model_copy(deep=True, update={"kind": "Add", "params": {}}))
            for edge in edges:
                if edge.target == node.id:
                    edge.target, edge.target_port = subtract, "a"
            wire(in_min, subtract, "b")
            wire(subtract, divide, "a")
            wire(in_span, divide, "b")
            if params["clamp"]:
                minimum = add("Min", "", parent=node)
                maximum = add("Max", "", parent=node)
                zero = add("Constant", "", value=0, parent=node)
                one = add("Constant", "", value=1, parent=node)
                wire(divide, minimum, "a")
                wire(one, minimum, "b")
                wire(minimum, maximum, "a")
                wire(zero, maximum, "b")
                wire(maximum, multiply, "a")
            else:
                wire(divide, multiply, "a")
            wire(out_span, multiply, "b")
            wire(multiply, node.id, "a")
            wire(out_min, node.id, "b")
        else:
            nodes.append(node.model_copy(deep=True))
    return graph.model_copy(deep=True, update={"nodes": nodes, "edges": edges})


def niagara_xml(program: Program):
    if "native_sedona" in program.metadata:
        raise ConversionError("Additional Sedona logic has no Niagara mapping.")
    graph = expand_macros(program)
    errors = [d.message for d in validate(graph) if d.level == "error"]
    if errors:
        raise ConversionError("; ".join(errors))
    unsupported = sorted({n.kind for n in graph.nodes} - SUPPORTED)
    if unsupported:
        raise ConversionError(
            "Niagara native primitive profile does not lower: " + ", ".join(unsupported)
        )
    if any(n.params.get("terminal") for n in graph.nodes):
        raise ConversionError(
            "Physical terminals need a Niagara driver binding; native export cannot omit them."
        )
    differences = DIFFERENCES + (
        EXTENDED_DIFFERENCES
        if any(
            n.kind
            in {"Scale", "Convert", "DeltaConvert", "TemperatureDifference", "TemperatureOffset"}
            for n in graph.nodes
        )
        else []
    )
    graph = _lower_composites(graph)
    root = ET.Element(
        "bajaObjectGraph",
        {"version": "4.0", "reversibleEncodingKeySource": "none", "FIPSEnabled": "false"},
    )
    root.append(
        ET.Comment(" BMS_STUDIO_BOG_V1 " + base64.b64encode(canonical(program)).decode() + " ")
    )
    folder = ET.SubElement(
        root, "p", {"n": "StudioProgram", "h": "root", "m": "b=baja", "t": "b:Folder"}
    )
    ET.SubElement(
        folder, "p", {"n": "studioConversionReview", "t": "b:String", "v": " ".join(differences)}
    )
    handles = {n.id: format(i + 1, "x") for i, n in enumerate(graph.nodes)}
    elements, ports = {}, {}
    names = {n.id: "n_" + re.sub(r"[^A-Za-z0-9_]", "_", n.id) for n in graph.nodes}
    if len(set(names.values())) != len(names):
        raise ConversionError("Node identifiers collide as Niagara slot names.")

    def prop(parent, name, value, boolean=False):
        wrapper = ET.SubElement(
            parent, "p", {"n": name, "t": "b:StatusBoolean" if boolean else "b:StatusNumeric"}
        )
        scalar = _scalar(value, boolean)
        ET.SubElement(wrapper, "p", {"n": "value", "v": str(scalar).lower()})
        ET.SubElement(wrapper, "p", {"n": "status", "v": "0"})

    for n in graph.nodes:
        boolean = output_type(n) == "boolean"
        if n.kind in ("Input", "Output"):
            typ, inputs = (
                "control:" + ("BooleanWritable" if boolean else "NumericWritable"),
                {"in": "in16"},
            )
        elif n.kind == "Constant":
            typ, inputs = "kitControl:" + ("BooleanConst" if boolean else "NumericConst"), {}
        elif n.kind == "Switch":
            typ, inputs = (
                "kitControl:" + ("BooleanSwitch" if boolean else "NumericSwitch"),
                {"select": "inSwitch", "on": "inTrue", "off": "inFalse"},
            )
        else:
            typ, inputs = NATIVE[n.kind]
        ports[n.id] = inputs
        name = names[n.id]
        element = ET.SubElement(
            folder,
            "p",
            {
                "n": name,
                "h": handles[n.id],
                "m": typ.split(":")[0] + "=" + typ.split(":")[0],
                "t": typ,
            },
        )
        elements[n.id] = element
        ET.SubElement(
            element,
            "p",
            {"n": "wsAnnotation", "t": "b:WsAnnotation", "v": f"{round(n.x)},{round(n.y)},8"},
        )
        if n.kind in {"Convert", "DeltaConvert"}:
            parameters = {**BLOCKS[n.kind].parameters, **n.params}
            for slot, key in (("inFacets", "from"), ("outFacets", "to")):
                ET.SubElement(
                    element,
                    "p",
                    {"n": slot, "t": "b:Facets", "v": "units=u:" + UNITS[parameters[key]]},
                )
        elif n.unit and not boolean:
            if n.unit not in UNITS:
                raise ConversionError("Niagara unit has no verified facet mapping: " + n.unit)
            ET.SubElement(
                element, "p", {"n": "facets", "t": "b:Facets", "v": "units=u:" + UNITS[n.unit]}
            )
        if n.kind in ("Input", "Output", "Constant"):
            default = (
                n.params.get("value", 0)
                if n.kind == "Constant"
                else n.params.get("default", False if boolean else 0)
            )
            prop(element, "out" if n.kind == "Constant" else "fallback", default, boolean)
        if n.kind == "Scale":
            parameters = {**BLOCKS[n.kind].parameters, **n.params}
            if parameters["in_min"] > parameters["in_max"]:
                parameters["in_min"], parameters["in_max"] = (
                    parameters["in_max"],
                    parameters["in_min"],
                )
                parameters["out_min"], parameters["out_max"] = (
                    parameters["out_max"],
                    parameters["out_min"],
                )
            for key, slot in RESET_LIMITS.items():
                prop(element, slot, parameters[key])
        if n.kind in ("Add", "Multiply", "And", "Or"):
            neutral = (
                True
                if n.kind == "And"
                else False
                if n.kind == "Or"
                else 1
                if n.kind == "Multiply"
                else 0
            )
            for slot in ("inC", "inD"):
                prop(element, slot, neutral, boolean)
    counts = {}

    def link(source, target, port):
        count = counts.get(target, 0)
        counts[target] = count + 1
        item = ET.SubElement(
            elements[target], "p", {"n": "Link" + (str(count) if count else ""), "t": "b:Link"}
        )
        for key, value in (
            ("sourceOrd", "h:" + handles[source]),
            ("sourceSlotName", "out"),
            ("targetSlotName", port),
        ):
            ET.SubElement(item, "p", {"n": key, "v": value})

    for edge in graph.edges:
        link(edge.source, edge.target, ports[edge.target][edge.target_port])
        if (
            next(n for n in graph.nodes if n.id == edge.target).kind in ("Min", "Max")
            and edge.target_port == "b"
        ):
            link(edge.source, edge.target, "inC")
            link(edge.source, edge.target, "inD")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def export_bog(program: Program):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", niagara_xml(program))
    return out.getvalue()


def import_bog(content: bytes):
    archive = NiagaraArchive(content)
    if archive.zipped and set(archive.members) != {"file.xml"}:
        raise ConversionError(
            "Additional BOG resources require archive preservation; semantic conversion cannot omit them."
        )
    source = SOURCE.search(archive.xml)
    if source:
        program = Program.model_validate_json(base64.b64decode(source[1], validate=True))
        if niagara_xml(program) != archive.xml:
            raise ConversionError(
                "Native BOG was edited; embedded source no longer matches. Open without its source comment for explicit semantic conversion."
            )
        return program
    if archive.root.get("reversibleEncodingKeySource", "none") != "none":
        raise ConversionError(
            "Protected Niagara encoding requires its authorized native runtime; it cannot be silently removed."
        )
    if archive.unhandled:
        first = archive.unhandled[0]
        raise ConversionError(
            "Unmodeled native component/value without a handle would be lost: "
            + first["path"]
            + " ("
            + first["type"]
            + ")"
        )
    nodes, edges, mapped, incoming, consumed, leaf_taps = [], [], {}, {}, set(), []
    native_facets = {}
    records = [r for r in archive.components if r["type"] not in FOLDERS]
    if len(records) > 2000:
        raise ConversionError("Niagara conversion exceeds 2,000 components.")
    for link in archive.links:
        if (
            not link["resolved"]
            or link["converter"]
            or link["type"].endswith(":ConversionLink")
            or link["source_slot"] != "out"
        ):
            raise ConversionError(
                "Native BOG link is external, unresolved or uses an unsupported converter/output slot."
            )
        if link["unknown_properties"]:
            raise ConversionError("Unsupported native link configuration would be lost.")
        if link["relation_id"] != "n:dataLink" or link["relation_tags"]:
            raise ConversionError("Unsupported native link relation configuration would be lost.")
        key = (link["target"], link["target_slot"])
        if key in incoming:
            raise ConversionError("Native BOG has multiple writers for one input slot.")
        incoming[key] = link["source"]
        consumed.add(link["source"])

    def wire(source, target, port):
        if len(edges) >= 10000:
            raise ConversionError("Niagara conversion exceeds 10,000 edges.")
        edges.append(Edge(id="e" + str(len(edges)), source=source, target=target, target_port=port))

    def const(value, boolean):
        if len(nodes) >= 2000:
            raise ConversionError("Niagara conversion exceeds 2,000 blocks.")
        identifier = "constant_" + str(len(nodes))
        nodes.append(
            Node(
                id=identifier,
                kind="Constant",
                params={"value": _scalar(value, boolean)},
                value_type="boolean" if boolean else "number",
            )
        )
        return identifier

    for index, record in enumerate(records):
        typ, element, handle = record["type"], record["element"], record["handle"]
        identifier = "n" + str(index)
        boolean = typ in (
            "control:BooleanWritable",
            "kitControl:BooleanConst",
            "kitControl:BooleanSwitch",
        ) or typ in {NATIVE[k][0] for k in ("Greater", "Less", "Equal", "And", "Or", "Not")}
        params = {}
        if typ in ("control:NumericWritable", "control:BooleanWritable"):
            kind = "Output" if (handle, "in16") in incoming else "Input"
            params = (
                {}
                if kind == "Output"
                else {
                    "default": _scalar(
                        _status_value(
                            element,
                            "fallback",
                            archive.value_types,
                            boolean,
                            "false" if boolean else "0",
                        ),
                        boolean,
                    )
                }
            )
            ports = {"in16": "in"} if kind == "Output" else {}
        elif typ in ("kitControl:NumericConst", "kitControl:BooleanConst"):
            kind, ports, params = (
                "Constant",
                {},
                {
                    "value": _scalar(
                        _status_value(
                            element,
                            "out",
                            archive.value_types,
                            boolean,
                            "false" if boolean else "0",
                        ),
                        boolean,
                    )
                },
            )
        elif typ in ("kitControl:NumericSwitch", "kitControl:BooleanSwitch"):
            kind, ports = "Switch", {"inSwitch": "select", "inTrue": "on", "inFalse": "off"}
        elif typ in REVERSE:
            kind, ports = REVERSE[typ]
            if kind == "Scale":
                params = {"clamp": True}
                for key, slot in RESET_LIMITS.items():
                    value = _status_value(element, slot, archive.value_types)
                    if value is None:
                        raise ConversionError(
                            "Configure every native Reset limit explicitly before conversion."
                        )
                    params[key] = _scalar(value)
                if params["in_min"] >= params["in_max"]:
                    raise ConversionError(
                        "Native Reset inputLowLimit must be less than inputHighLimit."
                    )
        else:
            raise ConversionError("No semantic Niagara mapping for " + typ)
        allowed_properties = {*ports, "out", "fallback", "facets", "wsAnnotation", "displayName"}
        if kind in REDUCTIONS:
            allowed_properties.update({"inC", "inD"})
        if kind == "Scale":
            allowed_properties.update(RESET_LIMITS.values())
        if kind == "Convert":
            allowed_properties -= {"facets", "fallback"}
            allowed_properties.update({"inFacets", "outFacets"})

        def unsupported_property(p, allowed=allowed_properties, node_kind=kind):
            if p.get("n") in allowed or p.get("h") or p.get("t", "").endswith(":Link"):
                return False
            if (
                node_kind in ("Input", "Output")
                and re.fullmatch(r"in(?:[1-9]|1[0-6])", p.get("n", ""))
                and "v" not in p.attrib
                and not len(p)
            ):
                return False
            return True

        if any(unsupported_property(p) for p in element.findall("p")):
            raise ConversionError(
                "Unsupported native component configuration would be lost: " + record["path"]
            )
        if kind == "Convert":
            converter_facets = {}
            for key, slot in (("from", "inFacets"), ("to", "outFacets")):
                prop = element.find("./p[@n='" + slot + "']")
                if (
                    prop is not None
                    and prop.get("t")
                    and archive.value_types.get(id(prop)) != "baja:Facets"
                ):
                    raise ConversionError(
                        "Native unit converter facets must have type baja:Facets."
                    )
                facets = _value(element, slot, "")
                params[key] = _unit_facets(facets)
                if params[key] not in (*ABSOLUTE_UNITS, *DELTA_UNITS):
                    raise ConversionError(
                        "Native unit converter requires explicit supported temperature units."
                    )
                converter_facets[slot] = facets
            if (params["from"] in DELTA_UNITS) != (params["to"] in DELTA_UNITS):
                raise ConversionError(
                    "Native converter cannot mix absolute and difference temperature units."
                )
            if params["from"] in DELTA_UNITS:
                kind = "DeltaConvert"
            unit = params["to"]
            native_facets[record["path"]] = converter_facets
        else:
            facets = _value(element, "facets", "")
            unit = _unit_facets(facets)
            if facets:
                native_facets[record["path"]] = facets
        node = Node(
            id=identifier,
            kind=kind,
            label=record["name"],
            unit=unit,
            value_type="boolean" if boolean else "number",
            params=params,
        )
        annotation = _value(element, "wsAnnotation", "")
        if annotation:
            try:
                node.x, node.y = map(float, annotation.split(",")[:2])
                if not math.isfinite(node.x) or not math.isfinite(node.y):
                    raise ValueError("nonfinite coordinates")
            except ValueError as exc:
                raise ConversionError("Invalid native wiresheet coordinates.") from exc
        nodes.append(node)
        mapped[handle] = (node, ports, record)
    if any(handle not in mapped for handle, _ in incoming):
        raise ConversionError("Native link targets an unsupported folder or property component.")
    if any(source not in mapped for source in incoming.values()):
        raise ConversionError("Native link source is not an executable component.")
    for handle, (node, ports, record) in mapped.items():
        allowed = set(ports) | ({"inC", "inD"} if node.kind in REDUCTIONS else set())
        if any(h == handle and slot not in allowed for h, slot in incoming):
            raise ConversionError(
                "Native input slot or writable priority is outside the conversion profile."
            )
        sources = []
        for slot, port in ports.items():
            source_handle = incoming.get((handle, slot))
            if source_handle is not None:
                if source_handle not in mapped:
                    raise ConversionError("Native link source is not an executable component.")
                source_id = mapped[source_handle][0].id
            else:
                value = _status_value(
                    record["element"],
                    slot,
                    archive.value_types,
                    input_type(node, port) == "boolean",
                )
                if value is None:
                    raise ConversionError(
                        "Connect or configure native input " + record["path"] + "." + slot
                    )
                source_id = const(value, input_type(node, port) == "boolean")
                nodes[-1].unit = (
                    (node.params["from"] if node.kind in {"Convert", "DeltaConvert"} else node.unit)
                    if nodes[-1].value_type == "number"
                    else ""
                )
            sources.append(source_id)
            wire(source_id, node.id, port)
        if node.kind in REDUCTIONS:
            extras = []
            for slot in ("inC", "inD"):
                if (handle, slot) in incoming:
                    extras.append(mapped[incoming[handle, slot]][0].id)
                else:
                    value = _status_value(
                        record["element"], slot, archive.value_types, node.value_type == "boolean"
                    )
                    if value is not None:
                        extra = const(value, node.value_type == "boolean")
                        nodes[-1].unit = node.unit
                        extras.append(extra)
            if extras:
                # Retain the public component ID as the final reduction result.
                original = node.id
                base_id = original + "_base"
                nodes[nodes.index(node)] = node.model_copy(deep=True, update={"id": base_id})
                for edge in edges:
                    if edge.target == original:
                        edge.target = base_id
                previous = base_id
                for i, extra in enumerate(extras):
                    new_id = original if i == len(extras) - 1 else original + "_reduce" + str(i)
                    nodes.append(
                        node.model_copy(
                            deep=True, update={"id": new_id, "label": node.label + " reduction"}
                        )
                    )
                    wire(previous, new_id, "a")
                    wire(extra, new_id, "b")
                    previous = new_id
        if handle not in consumed and node.kind != "Output":
            result_id = "n" + str(records.index(record))
            tap = Node(
                id=result_id + "_result",
                kind="Output",
                label=record["name"] + " result",
                unit=node.unit,
                value_type=output_type(node),
            )
            nodes.append(tap)
            wire(result_id, tap.id, "in")
            leaf_taps.append(record["path"])
    # Infer only exact, zero-offset arithmetic quantity contracts from linked
    # unit evidence. A raw Add never performs an implicit cross-unit conversion.
    by_id = {node.id: node for node in nodes}
    links = {(edge.target, edge.target_port): by_id[edge.source] for edge in edges}
    for node in nodes:
        if node.kind not in {"Subtract", "Add"}:
            continue
        left, right = links.get((node.id, "a")), links.get((node.id, "b"))
        if left is None or right is None:
            continue
        if (
            node.kind == "Subtract"
            and left.unit in ABSOLUTE_UNITS
            and right.unit == left.unit
            and node.unit == DELTA_FOR_ABSOLUTE[left.unit]
        ):
            node.kind = "TemperatureDifference"
            node.params = {"unit": left.unit}
        elif node.kind == "Add" and node.unit in ABSOLUTE_UNITS:
            base_port = next(
                (port for port, source in (("a", left), ("b", right)) if source.unit == node.unit),
                None,
            )
            difference_port = "b" if base_port == "a" else "a"
            difference = right if difference_port == "b" else left
            if base_port and difference.unit == DELTA_FOR_ABSOLUTE[node.unit]:
                node.kind = "TemperatureOffset"
                node.params = {"unit": node.unit, "difference_unit": difference.unit}
                for edge in edges:
                    if edge.target == node.id:
                        edge.target_port = "base" if edge.target_port == base_port else "difference"
    if len(nodes) > 2000 or len(edges) > 10000:
        raise ConversionError("Converted Niagara graph exceeds project limits.")
    program = Program(
        id="niagara-" + archive.hash[:16],
        name="Imported Niagara BOG",
        nodes=nodes,
        edges=edges,
        metadata={
            "conversion": {
                "source_format": "Niagara BOG",
                "source_sha256": archive.hash,
                "review_required": True,
                "differences": DIFFERENCES + EXTENDED_DIFFERENCES,
                "published_leaf_taps": leaf_taps,
                "native_facets": native_facets,
            }
        },
    )
    errors = [d.message for d in validate(program) if d.level == "error"]
    if errors:
        raise ConversionError(
            "Niagara conversion requires explicit type/unit/cycle repair: " + "; ".join(errors)
        )
    return program
