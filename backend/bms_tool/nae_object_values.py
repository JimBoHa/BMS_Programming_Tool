"""Decode actual native NAE object reads, never creation defaults or images.

Unknown content remains in the caller's retained input artifact. These readouts
grant no write, configuration-image, transfer or restoration authority.
"""

from __future__ import annotations

import hashlib
import math
import re

from defusedxml.ElementTree import fromstring

from .nae_https import INTEGRATION_NS, MAX_RESPONSE, NAV_NS

CORE = "{http://johnsoncontrols.com/MetasysIII/2002/3/Core}"
NAV = "{" + NAV_NS + "}"
INTEGRATION = "{" + INTEGRATION_NS + "}"
INTEGER_BOUNDS = {
    "unsignedByte": (0, 255),
    "unsignedShort": (0, 65535),
    "unsignedLong": (0, 4294967295),
    "byte": (-128, 127),
    "short": (-32768, 32767),
    "long": (-2147483648, 2147483647),
    "oid": (0, 4294967295),
    "enum": (0, 4294967295),
}


def _int(value, minimum, maximum):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,10})", value):
        raise ValueError("Invalid native integer encoding.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError("Native integer exceeds its declared range.")
    return number


def _flag(value, default=False):
    if value is None:
        return default
    if value not in ("true", "false", "1", "0"):
        raise ValueError("Invalid native flag encoding.")
    return value in ("true", "1")


def _read(raw, method, namespace=NAV):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_RESPONSE:
        raise ValueError("Native read artifact exceeds its byte budget.")
    try:
        root = fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception:
        raise ValueError("Invalid native read artifact XML.") from None
    stack, count = [(root, 0)], 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 50000 or depth > 64:
            raise ValueError("Native read structure exceeds its element/depth budget.")
        stack.extend((child, depth + 1) for child in node)
    if root.tag != namespace + method + "Response":
        raise ValueError("Native artifact does not match the requested current-value operation.")
    if len(root) != 1 or root[0].tag != namespace + method + "Result":
        raise ValueError("Ambiguous native operation result.")
    return root[0]


def _codes(nodes):
    # Never reflect arbitrary server messages, which can contain supplied data.
    result = []
    for node in nodes:
        try:
            result.append(_int(node.get("code"), 0, 4294967295))
        except ValueError:
            result.append(None)
    return result


def _scalar(data):
    values = [n for n in data if n.tag != CORE + "uniqueProp"]
    if len(values) != 1 or not values[0].tag.startswith(CORE):
        return {"status": "unsupported_value", "datatype": None}
    node = values[0]
    kind, text = node.tag[len(CORE) :], node.text or ""
    nil = node.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
    if nil is not None:
        if nil not in ("true", "false", "1", "0"):
            return {"status": "invalid_native_value", "datatype": kind}
        if _flag(nil):
            if text or len(node):
                return {"status": "invalid_native_value", "datatype": kind}
            return {"status": "null_value", "datatype": kind, "value": None}
    if len(node):
        return {"status": "unsupported_value", "datatype": kind}
    try:
        if kind in INTEGER_BOUNDS:
            value = _int(text, *INTEGER_BOUNDS[kind])
        elif kind == "BACoid":
            value = {
                "object_type": _int(node.get("id"), 0, 1023),
                "instance": _int(text, 0, 4194302),
            }
        elif kind in ("float", "double"):
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text):
                raise ValueError()
            value = float(text)
            if not math.isfinite(value):
                raise ValueError()
        elif kind == "boolean":
            if text not in ("true", "false", "1", "0"):
                raise ValueError()
            value = _flag(text)
        elif kind == "string":
            if len(text) > 4096:
                return {"status": "unsupported_value", "datatype": kind}
            value = text
        else:
            return {"status": "unsupported_value", "datatype": kind}
    except (ValueError, OverflowError):
        return {"status": "invalid_native_value", "datatype": kind}
    return {"status": "ok", "datatype": kind, "value": value}


def object_values(raw, *, reference, class_id, class_version, properties=None, view_id=None):
    """Decode one exact current-value read; the source bytes are retained by caller.

    `properties` qualifies a ReadPropertyMultiple response; `view_id` qualifies a
    GetView response. A missing requested field, conflicting class/reference,
    duplicate or creation-definition response cannot become a verified readout.
    """
    if type(reference) is not str or not 1 <= len(reference) <= 512:
        raise ValueError("An exact native object reference is required.")
    if type(class_id) is not int or not 1 <= class_id <= 65535:
        raise ValueError("An exact native object class is required.")
    if type(class_version) is not str or not re.fullmatch(r"\d{1,3}\.\d{1,3}", class_version):
        raise ValueError("An exact native object class version is required.")
    if (properties is None) == (view_id is None):
        raise ValueError("Select exactly one native read scope.")
    if properties is not None:
        if (
            type(properties) is not list
            or not 1 <= len(properties) <= 64
            or any(type(p) is not int or not 0 <= p <= 65535 for p in properties)
            or len(set(properties)) != len(properties)
        ):
            raise ValueError("Invalid requested native property scope.")
        operation = "ReadPropertyMultiple"
        result = _read(raw, operation)
        items = result.findall(NAV + "items/" + NAV + "item")
        if len(items) != 1:
            raise ValueError("Native property read returned a different object count.")
        objects = result.findall(NAV + "items/" + NAV + "item/" + CORE + "object")
    else:
        if type(view_id) is not int or not 0 <= view_id <= 65535:
            raise ValueError("Invalid requested native view scope.")
        operation = "GetView"
        result = _read(raw, operation)
        objects = result.findall(CORE + "viewData/" + CORE + "object")
    if len(objects) != 1 or len(list(result.iter(CORE + "object"))) != 1:
        raise ValueError("Native read lacks one unambiguous selected object.")
    obj = objects[0]
    if (
        obj.get("ref") != reference
        or obj.get("classid") != str(class_id)
        or obj.get("classVersion") != class_version
    ):
        raise ValueError("Native read object identity/class/version differs from its selection.")
    if view_id is None:
        props = obj.findall(CORE + "property")
    else:
        views = obj.findall(CORE + "view")
        if len(views) != 1 or views[0].get("id") != str(view_id):
            raise ValueError("Returned native view differs from its selection.")
        props = []
        stack = [views[0]]
        while stack:
            parent = stack.pop()
            for child in parent:
                if child.tag == CORE + "property":
                    props.append(child)
                elif child.tag in (CORE + "group", CORE + "subgroup"):
                    stack.append(child)
    property_errors = {id(error) for p in props for error in p.iter(CORE + "error")}
    if any(id(e) not in property_errors for e in result.iter(CORE + "error")):
        raise ValueError("Native read returned a failure outside the selected property scope.")
    rows, seen = [], set()
    for node in props:
        identity = _int(node.get("id"), 0, 65535)
        if identity in seen or node.get("arrayIndex") is not None:
            raise ValueError(
                "Duplicate/indexed native property is outside this whole-property read."
            )
        seen.add(identity)
        row = {
            "property_id": identity,
            "writable_advertised": _flag(node.get("w")),
            "write_available": False,
        }
        errors = list(node.iter(CORE + "error"))
        data = node.findall(CORE + "data")
        if errors:
            row.update(status="native_error", error_codes=_codes(errors))
        elif len(data) != 1:
            row.update(status="invalid_native_value", datatype=None)
        else:
            row.update(_scalar(data[0]))
        rows.append(row)
    if not rows or (properties is not None and seen != set(properties)):
        raise ValueError("Returned native properties differ from the requested complete set.")
    # Unknown XML is retained as input bytes; decoding a subset does not establish
    # a complete or restorable configuration image.
    return {
        "profile": "nae-native-object-values/1",
        "operation": operation,
        "reference": reference,
        "class_id": class_id,
        "class_version": class_version,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "encoding_basis": "retained response-body artifact, not a wire/image hash",
        "properties": rows,
        "decoded_all_values": all(r["status"] == "ok" for r in rows),
        "native_image_backup": False,
        "write_available": False,
    }


def view_definitions(raw, *, reference):
    if type(reference) is not str or not 1 <= len(reference) <= 512:
        raise ValueError("An exact native object reference is required.")
    result = _read(raw, "GetViewList")
    definitions = result.findall(CORE + "viewList/" + CORE + "viewDefns/" + CORE + "viewDefn")
    if not definitions or len(definitions) > 256:
        raise ValueError("Native view definitions are empty or exceed their bound.")
    rows, seen = [], set()
    for node in definitions:
        target = node.get("reference", reference)
        if target != reference and not target.startswith(reference + "."):
            raise ValueError("Native view definition points outside its selected object.")
        identity = (target, _int(node.get("id"), 0, 65535))
        if identity in seen:
            raise ValueError("Duplicate native view definition for the same object.")
        seen.add(identity)
        rows.append(
            {
                "reference": identity[0],
                "view_id": identity[1],
                "active": _flag(node.get("active")),
                "default": _flag(node.get("default")),
            }
        )
    return rows


def engineering_outcome(raw):
    result = _read(raw, "GetEngView", INTEGRATION)
    views = result.findall(CORE + "engViewData")
    if len(views) != 1:
        raise ValueError("Ambiguous native engineering view.")
    errors, rows = list(result.iter(CORE + "error")), views[0].findall(CORE + "row")
    local_errors = {id(error) for error in views[0].iter(CORE + "error")}
    outside_failure = any(id(error) not in local_errors for error in errors)
    return {
        "status": (
            "rejected"
            if outside_failure
            else ("partial" if rows else "rejected")
            if errors
            else "returned_data"
        ),
        "row_count": len(rows),
        "error_codes": _codes(errors),
        "write_available": False,
    }
