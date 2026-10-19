"""Semantic conversion of a bounded, verified standard Sedona SAX/SAB subset.

Backward dependencies retain a one-scan delay. Null propagation and native
non-atomic publication are reported as changed failure behavior, not silently
described as equivalent. Unknown logic and hardware services reject conversion.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
import tempfile
from pathlib import Path

from defusedxml import ElementTree as XML

from .engine import validate
from .formats import ConversionError
from .models import Edge, Node, Program
from .sedona import compiler, toolchain

NATIVE = {
    "math::Add2": ("Add", {"in1": "a", "in2": "b"}),
    "math::Sub2": ("Subtract", {"in1": "a", "in2": "b"}),
    "math::Mul2": ("Multiply", {"in1": "a", "in2": "b"}),
    "math::Div2": ("Divide", {"in1": "a", "in2": "b"}),
    "math::Min": ("Min", {"in1": "a", "in2": "b"}),
    "math::Max": ("Max", {"in1": "a", "in2": "b"}),
    "logic::And2": ("And", {"in1": "a", "in2": "b"}),
    "logic::Or2": ("Or", {"in1": "a", "in2": "b"}),
    "logic::Not": ("Not", {"in": "in"}),
    "types::ConstFloat": ("Constant", {}),
    "types::ConstBool": ("Constant", {}),
    "types::WriteFloat": ("Input", {"in": "in"}),
    "types::WriteBool": ("Input", {"in": "in"}),
}
INFRASTRUCTURE = {
    "sys::UserService",
    "sys::User",
    "sox::SoxService",
    "platUnix::UnixPlatformService",
}
KITS = {"sys", "types", "math", "logic", "sox", "inet", "platUnix"}


def _number(text, boolean=False):
    if boolean:
        if text not in ("true", "false"):
            raise ConversionError(
                "Three-valued/null boolean initialization cannot be converted losslessly."
            )
        return text == "true"
    try:
        value = float(text)
    except ValueError as exc:
        raise ConversionError(
            "Null/nonnumeric initialization is outside the finite conversion profile."
        ) from exc
    if not math.isfinite(value):
        raise ConversionError("Nonfinite initialization is outside the finite conversion profile.")
    return value


def _local_schema(parts):
    sdk, _ = toolchain()
    for name, checksum in parts:
        if name not in KITS:
            raise ConversionError(
                f"Unsupported native kit {name!r}. Generated Studio graphs use their .sedona.zip bundle."
            )
        if checksum is not None:
            if not re.fullmatch(r"[a-fA-F0-9]{1,8}", checksum):
                raise ConversionError("Invalid native kit checksum.")
            checksum = format(int(checksum, 16), "08x")
        manifests = sdk / "manifests" / name
        matches = list(manifests.glob(name + "-" + (checksum or "*") + ".xml"))
        if not matches:
            raise ConversionError(
                f"Matching local kit manifest is missing: {name}-{checksum}. No remote kit is downloaded."
            )


def decode_sab(content):
    if len(content) > 8 * 1024 * 1024 or len(content) < 10:
        raise ConversionError("Invalid SAB size.")
    if struct.unpack_from(">II", content) != (0x73617070, 3):
        raise ConversionError("Only the observed Sedona SAB version 0.3 is supported.")
    count, position, parts = content[8], 9, []
    if not 1 <= count <= 32:
        raise ConversionError("Invalid SAB schema size.")
    for _ in range(count):
        end = content.find(b"\0", position, position + 65)
        if end < 0 or end + 5 > len(content):
            raise ConversionError("Truncated SAB kit schema.")
        name = content[position:end].decode("ascii")
        checksum = struct.unpack_from(">I", content, end + 1)[0]
        parts.append((name, format(checksum, "08x")))
        position = end + 5
    _local_schema(parts)
    sdk, java = toolchain()
    with tempfile.TemporaryDirectory(prefix="bms-sab-import-") as tmp:
        path = Path(tmp) / "source.sab"
        path.write_bytes(content)
        compiler(sdk, java, path)
        decoded = (path.with_suffix(".sax")).read_bytes()
        if len(decoded) > 8 * 1024 * 1024:
            raise ConversionError("Decoded SAX exceeds 8 MiB.")
        return decoded


def import_sax(content, *, source_kind="SAX"):
    if len(content) > 8 * 1024 * 1024:
        raise ConversionError("SAX exceeds 8 MiB.")
    root = XML.fromstring(content)
    if root.tag != "sedonaApp" or root.find("app") is None:
        raise ConversionError("Not a Sedona application.")
    parts = [(k.get("name"), k.get("checksum")) for k in root.findall("./schema/kit")]
    names = [p[0] for p in parts]
    if "sys" not in names or len(set(names)) != len(names):
        raise ConversionError("Native schema requires sys and unique kit names.")
    _local_schema(parts)
    records, excluded, unsupported, props_by_path, seen = [], [], [], {}, set()

    def walk(element, parent="", depth=0):
        if depth > 24:
            raise ConversionError("Sedona component nesting exceeds 24 levels.")
        for child in element.findall("comp"):
            name, typ = child.get("name", ""), child.get("type", "")
            if typ.split("::", 1)[0] not in names:
                raise ConversionError("Component type belongs to an undeclared kit.")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,6}", name):
                raise ConversionError("Invalid native component name.")
            path = parent + "/" + name
            if path in seen:
                raise ConversionError("Duplicate native component path.")
            seen.add(path)
            if typ == "sys::Folder":
                walk(child, path, depth + 1)
            elif typ in INFRASTRUCTURE and path.startswith("/service/"):
                excluded.append({"path": path, "type": typ})
                walk(child, path, depth + 1)
            elif typ in NATIVE:
                if child.findall("comp"):
                    raise ConversionError(
                        "Children beneath executable native blocks need a separate execution adapter."
                    )
                records.append(
                    {
                        "path": path,
                        "type": typ,
                        "props": {p.get("name"): p.get("val") for p in child.findall("prop")},
                    }
                )
                props_by_path[path] = child
            else:
                unsupported.append(path + " (" + typ + ")")

    walk(root.find("app"))
    if unsupported:
        raise ConversionError(
            "Unsupported native logic/services; nothing was converted: "
            + ", ".join(unsupported[:20])
        )
    if not records or len(records) > 400:
        raise ConversionError("Convert 1–400 supported native components at a time.")
    paths = {r["path"]: (i, r) for i, r in enumerate(records)}
    links = {}
    for link in root.findall("./links/link"):
        try:
            from_path, from_port = link.attrib["from"].rsplit(".", 1)
            to_path, to_port = link.attrib["to"].rsplit(".", 1)
        except (KeyError, ValueError) as exc:
            raise ConversionError("Malformed native property link.") from exc
        if from_path not in paths or to_path not in paths or from_port != "out":
            raise ConversionError(
                "Native link references an unsupported component or source property."
            )
        _, target = paths[to_path]
        if to_port not in NATIVE[target["type"]][1] or (to_path, to_port) in links:
            raise ConversionError("Unsupported target port or multiple native link writers.")
        links[to_path, to_port] = from_path
    nodes, edges, delays, ignored_runtime = [], [], [], []
    for i, record in enumerate(records):
        path, typ, props = record["path"], record["type"], record["props"]
        kind, ports = NATIVE[typ]
        boolean = typ.endswith("Bool") or typ.startswith("logic::")
        value_type = "boolean" if boolean else "number"
        params = {}
        if kind == "Constant":
            params["value"] = _number(props.get("out", "false" if boolean else "0"), boolean)
        if kind == "Input":
            if (path, "in") in links:
                kind = "Output"
            else:
                params["default"] = _number(props.get("in", "false" if boolean else "0"), boolean)
                ports = {}
        allowed = {
            "meta",
            "out" if kind == "Constant" else "in" if typ.startswith("types::Write") else "",
        }
        for prop in props.keys() - allowed:
            if prop in {"out", *ports}:
                ignored_runtime.append(path + "." + prop)
            else:
                raise ConversionError(
                    "Unmapped native configuration property: " + path + "." + prop
                )
        node_id = "s" + str(i)
        nodes.append(
            Node(
                id=node_id,
                kind=kind,
                label=path,
                params=params,
                value_type=value_type,
                x=100 + (i % 4) * 250,
                y=80 + (i // 4) * 180,
            )
        )
        for native_port, port in ports.items():
            source_path = links.get((path, native_port))
            source_id = None
            if source_path:
                source_index, source = paths[source_path]
                source_id = "s" + str(source_index)
                if source_index >= i and not source["type"].startswith("types::Const"):
                    delay_id = f"d{i}_{native_port}"
                    nodes.append(
                        Node(
                            id=delay_id,
                            kind="Delay",
                            value_type=value_type,
                            params={"initial": False if boolean else 0},
                            label="Native previous-scan dependency",
                            x=nodes[-1].x - 100,
                            y=nodes[-1].y - 80,
                        )
                    )
                    edges.append(Edge(id=delay_id, source=source_id, target=delay_id))
                    source_id = delay_id
                    delays.append({"from": source_path, "to": path, "port": native_port})
            else:
                source_id = f"default{i}_{native_port}"
                nodes.append(
                    Node(
                        id=source_id,
                        kind="Constant",
                        value_type=value_type,
                        params={"value": False if boolean else 0},
                        label="Native unlinked default",
                    )
                )
            edges.append(
                Edge(id=f"e{i}_{native_port}", source=source_id, target=node_id, target_port=port)
            )
        output_id = "watch" + str(i)
        nodes.append(
            Node(
                id=output_id,
                kind="Output",
                label=path + ".out",
                value_type=value_type,
                x=1200,
                y=i * 100,
            )
        )
        edges.append(Edge(id=output_id, source=node_id, target=output_id))
    app_props = {p.get("name"): p.get("val") for p in root.findall("./app/prop")}
    scan = _number(app_props.get("scanPeriod", "50")) / 1000
    if not 0.01 <= scan <= 60:
        raise ConversionError("Native scan period is outside the supported 0.01–60 second range.")
    report = {
        "source_format": "Sedona " + source_kind,
        "profile": "finite non-null numeric/boolean values",
        "native_components": len(records),
        "previous_scan_links": delays,
        "excluded_infrastructure": excluded,
        "nonpersistent_runtime_properties": ignored_runtime,
        "review_required": True,
        "behavior_changes": [
            "Source null/NaN propagation becomes strict scan faults with held outputs.",
            "The graph runtime commits a complete scan atomically; native Sedona publishes per component.",
            "The graph runtime uses Python double precision; native float properties use 32 bits.",
            "Network users, services and platform installation settings require separate configuration.",
        ],
        "source_sha256": hashlib.sha256(content).hexdigest(),
    }
    program = Program(
        id="sedona-import-" + report["source_sha256"][:12],
        name="Imported Sedona application",
        nodes=nodes,
        edges=edges,
        scan_seconds=scan,
        metadata={"conversion": report},
    )
    errors = [d.message for d in validate(program) if d.level == "error"]
    if errors:
        raise ConversionError(
            "Native conversion failed type/execution checks: " + "; ".join(errors)
        )
    return program
