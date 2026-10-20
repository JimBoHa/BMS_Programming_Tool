"""Read observed JCI DynamicHardwareDefinition XML without inventing a controller schema.

Native device-interface metadata describes points and parameter ranges, not CAF
object allocation, an application compiler, or a controller loader. All planning
here is offline; input XML and unknown metadata remain byte-exact on export.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from collections import defaultdict

from defusedxml import ElementTree as XML

NS = "urn:JohnsonControls:Tools:Metasys:Modeling:Devices"
Q = "{" + NS + "}"
SYSTEMS = {"imperial", "metric"}
FLOAT_FIELDS = {"min", "max", "default", "covIncrement"}
INTEGER_FIELDS = {"units", "displayPrecision"}
SCOPE = "Offline native device-definition engineering plan; no CAF object creation, compilation or device writes."


def _integer(value, name, maximum=4294967295):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9]{1,10}", value)
        or int(value) > maximum
    ):
        raise ValueError(f"Native hardware {name} requires an unsigned integer in range.")
    return int(value)


def _identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]{0,159}", value):
        raise ValueError(f"Native hardware {name} is missing or has unsupported encoding.")
    return value


def _one(element, name, required=True):
    matches = element.findall(Q + name)
    if len(matches) > 1 or (required and not matches):
        raise ValueError(f"Native hardware requires exactly one {name} element.")
    return matches[0] if matches else None


def _value_profile(element, system, enumerations, inherited=None):
    kind = element.tag.removeprefix(Q)
    if kind not in {"Float", "Boolean", "Enum"}:
        raise ValueError("Unsupported native hardware value type: " + kind)
    attributes = dict(inherited or {})
    attributes.update(element.attrib)
    measurements = element.findall(Q + "Measurement")
    if any(child.tag != Q + "Measurement" for child in element):
        raise ValueError("Unsupported native hardware value child structure.")
    if measurements:
        systems = [measurement.get("system") for measurement in measurements]
        if len(systems) != len(set(systems)) or any(name not in SYSTEMS for name in systems):
            raise ValueError("Native hardware measurements require unique imperial/metric systems.")
        matching = [
            measurement for measurement in measurements if measurement.get("system") == system
        ]
        if len(matching) != 1:
            raise ValueError("Native hardware has no explicit measurement for system " + system)
        if len(matching[0]):
            raise ValueError("Unsupported native measurement child structure.")
        attributes.update(
            {key: value for key, value in matching[0].attrib.items() if key != "system"}
        )
    allowed = FLOAT_FIELDS | INTEGER_FIELDS | ({"set"} if kind != "Float" else set())
    if set(attributes) - allowed:
        raise ValueError(
            "Unsupported native hardware value attributes: "
            + ", ".join(sorted(set(attributes) - allowed))
        )
    profile = {"type": kind, "parameters": {}}
    values = profile["parameters"]
    for key, value in attributes.items():
        if key in INTEGER_FIELDS:
            values[key] = _integer(value, key, 65535)
        elif key == "set":
            values[key] = value
        elif kind == "Boolean" and key == "default":
            if value not in ("0", "1", "false", "true"):
                raise ValueError("Native hardware Boolean default must be 0, 1, false or true.")
            values[key] = value in ("1", "true")
        elif kind == "Enum" and key == "default":
            values[key] = _integer(value, "enum default", 65535)
        else:
            try:
                number = float(value)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ValueError("Native hardware numeric parameters must be finite.") from exc
            if not math.isfinite(number):
                raise ValueError("Native hardware numeric parameters must be finite.")
            values[key] = number
    if "min" in values and "max" in values and values["min"] > values["max"]:
        raise ValueError("Native hardware minimum exceeds maximum.")
    if (
        "default" in values
        and kind == "Float"
        and (
            ("min" in values and values["default"] < values["min"])
            or ("max" in values and values["default"] > values["max"])
        )
    ):
        raise ValueError("Native hardware default lies outside its declared range.")
    if values.get("covIncrement", 0) < 0:
        raise ValueError("Native hardware COV increment cannot be negative.")
    if kind in {"Enum", "Boolean"}:
        enum_set = values.get("set")
        if not enum_set:
            raise ValueError("Native hardware enumerated values require their enum-set reference.")
        local = enumerations.get(enum_set)
        profile["enum_reference"] = enum_set
        profile["enum_entries"] = copy.deepcopy(local)
        profile["enum_resolution"] = "local" if local is not None else "external-unresolved"
        if (
            kind == "Enum"
            and local is not None
            and "default" in values
            and values["default"] not in local
        ):
            raise ValueError("Native hardware enum default is absent from its local enum set.")
    return profile


class JciHardwareDefinition:
    def __init__(self, content: bytes):
        if not isinstance(content, bytes) or not content or len(content) > 8 * 1024 * 1024:
            raise ValueError("Native hardware XML requires 1 byte through 8 MiB.")
        try:
            root = XML.fromstring(content)
        except Exception as exc:
            raise ValueError("Invalid or unsafe native hardware XML.") from exc
        if root.tag != Q + "Interface" or root.get("schemaVersion") != "1.0":
            raise ValueError("Expected the observed JCI Interface namespace/schemaVersion 1.0.")
        pending, count = [(root, 0)], 0
        while pending:
            element, depth = pending.pop()
            count += 1
            if depth > 32 or count > 50000:
                raise ValueError("Native hardware XML exceeds depth/element limits.")
            pending.extend((child, depth + 1) for child in element)
        self.original = content
        self.hash = hashlib.sha256(content).hexdigest()
        self.root = root
        self.name = _identifier(root.get("name"), "interface name")
        self.revision = _integer(root.get("revision"), "interface revision", 65535)
        self.description = root.get("description", "")
        device = _one(root, "Device")
        vendor = _one(device, "Vendor")
        self.vendor = {
            "number": _integer(vendor.get("number"), "vendor", 65535),
            "name": vendor.get("name", ""),
        }
        self.unknown = []
        for child in root:
            if child.tag not in {
                Q + name for name in ("Device", "Definitions", "Points", "Applications")
            }:
                self.unknown.append({"path": "/Interface", "tag": child.tag})
        self.buses = []
        communication = _one(device, "Communication")
        for bus in communication:
            if bus.tag != Q + "SensorActuatorBus":
                self.unknown.append({"path": "/Interface/Device/Communication", "tag": bus.tag})
                continue
            protocol = _one(bus, "BACnetMSTP")
            low = _integer(protocol.get("minAddress"), "minimum address", 254)
            high = _integer(protocol.get("maxAddress"), "maximum address", 254)
            if low > high:
                raise ValueError("Native hardware address range is reversed.")
            self.buses.append(
                {
                    "bus": "SensorActuatorBus",
                    "protocol": "BACnetMSTP",
                    "min_address": low,
                    "max_address": high,
                }
            )
        definitions = _one(root, "Definitions", required=False)
        self.enumerations, self.attribute_definitions = {}, {}
        if definitions is not None:
            for definition in definitions:
                key = _identifier(definition.get("id"), "definition identifier")
                if definition.tag == Q + "EnumerationSet":
                    if key in self.enumerations:
                        raise ValueError("Duplicate native enumeration-set identifier.")
                    entries = {}
                    for entry in definition:
                        if entry.tag != Q + "Entry" or len(entry):
                            raise ValueError("Unsupported native enumeration-set entry.")
                        number = _integer(entry.get("value"), "enum entry", 65535)
                        if number in entries:
                            raise ValueError("Duplicate native enum entry value.")
                        entries[number] = entry.text or ""
                    self.enumerations[key] = entries
                elif definition.tag == Q + "Attribute":
                    if key in self.attribute_definitions:
                        raise ValueError("Duplicate native attribute identifier.")
                    self.attribute_definitions[key] = definition
                else:
                    self.unknown.append({"path": "/Interface/Definitions", "tag": definition.tag})
        points = _one(root, "Points")
        self.prefix = points.get("defaultPrefix", "")
        self.default_update_rate = points.get("updateRate")
        self.points = {}
        for point in points:
            if len(self.points) >= 4096:
                raise ValueError("Native hardware exceeds 4096 points.")
            key = _identifier(point.get("id"), "point identifier")
            if key in self.points:
                raise ValueError("Duplicate native hardware point identifier.")
            if point.tag not in {Q + "Input", Q + "Output"}:
                self.unknown.append({"path": "/Interface/Points", "tag": point.tag})
                continue
            self.points[key] = point
        self.presets = {}
        applications = _one(root, "Applications", required=False)
        if applications is not None:
            for preset in applications:
                if preset.tag != Q + "Preset":
                    self.unknown.append({"path": "/Interface/Applications", "tag": preset.tag})
                    continue
                key = _identifier(preset.get("id"), "preset identifier")
                if key in self.presets:
                    raise ValueError("Duplicate native preset identifier.")
                references = []
                for entry in preset:
                    if entry.tag != Q + "Point" or entry.get("ref") not in self.points:
                        raise ValueError("Native preset contains an unknown point reference.")
                    references.append(entry.get("ref"))
                if len(set(references)) != len(references):
                    raise ValueError("Native preset contains duplicate point references.")
                self.presets[key] = {"name": preset.get("name", ""), "points": references}

    def export(self):
        return self.original

    def point(self, identifier: str, system="imperial"):
        if not isinstance(system, str) or system not in SYSTEMS:
            raise ValueError("Measurement system must be imperial or metric.")
        if not isinstance(identifier, str):
            raise ValueError("Native hardware point identifier must be a string.")
        point = self.points.get(identifier)
        if point is None:
            raise ValueError("Native hardware point identifier was not found.")
        if set(point.attrib) - {"id", "name", "description", "updateRate", "class", "instance"}:
            raise ValueError(
                "Unsupported native hardware point attributes require explicit interpretation."
            )
        if any(child.tag not in {Q + "Value", Q + "Attribute"} for child in point):
            raise ValueError("Unsupported native hardware point child structure.")
        value = _one(point, "Value")
        if set(value.attrib) - {"writeStrategy"}:
            raise ValueError(
                "Unsupported native hardware Value attributes require explicit interpretation."
            )
        if len(value) != 1:
            raise ValueError("Native point Value requires exactly one typed descriptor.")
        profile = _value_profile(value[0], system, self.enumerations)
        attributes, seen = [], set()
        for attribute in point.findall(Q + "Attribute"):
            ref = attribute.get("ref")
            definition = self.attribute_definitions.get(ref)
            if definition is None or ref in seen:
                raise ValueError("Native point attribute reference is missing or duplicated.")
            seen.add(ref)
            if set(attribute.attrib) != {"ref"} or set(definition.attrib) - {
                "id",
                "type",
                "name",
                "property",
                "linked",
            }:
                raise ValueError("Unsupported native point attribute configuration.")
            if len(attribute) != 1 or len(definition) != 1 or attribute[0].tag != definition[0].tag:
                raise ValueError("Native point attribute type does not match its definition.")
            if len(definition[0]):
                raise ValueError(
                    "Inherited native attribute measurement structures require explicit interpretation."
                )
            linked = definition.get("linked", "false")
            if linked not in ("0", "1", "false", "true"):
                raise ValueError("Native attribute linked flag requires a Boolean value.")
            attributes.append(
                {
                    "id": ref,
                    "name": definition.get("name", ""),
                    "property_id": _integer(
                        definition.get("property"), "attribute property", 4294967295
                    ),
                    "configuration_type": definition.get("type", ""),
                    "linked": linked in ("1", "true"),
                    "value": _value_profile(
                        attribute[0], system, self.enumerations, definition[0].attrib
                    ),
                }
            )
        rate = point.get("updateRate", self.default_update_rate)
        try:
            update_rate = float(rate) if rate is not None else None
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Native hardware update rate must be finite and positive.") from exc
        if update_rate is not None and (not math.isfinite(update_rate) or update_rate <= 0):
            raise ValueError("Native hardware update rate must be finite and positive.")
        return {
            "id": identifier,
            "name": point.get("name", ""),
            "description": point.get("description", ""),
            "direction": point.tag.removeprefix(Q).lower(),
            "object_type": _integer(point.get("class"), "BACnet object type", 1023),
            "instance": _integer(point.get("instance"), "BACnet instance", 4194303),
            "value": profile,
            "attributes": attributes,
            "update_rate": update_rate,
            "write_strategy": value.get("writeStrategy"),
        }

    def summary(self, system="imperial"):
        if not isinstance(system, str) or system not in SYSTEMS:
            raise ValueError("Measurement system must be imperial or metric.")
        points, errors, addresses = [], [], defaultdict(list)
        for identifier in self.points:
            try:
                point = self.point(identifier, system)
                points.append(point)
                addresses[(point["object_type"], point["instance"])].append(identifier)
            except ValueError as exc:
                errors.append({"id": identifier, "error": str(exc)})
        return {
            "sha256": self.hash,
            "name": self.name,
            "revision": self.revision,
            "description": self.description,
            "vendor": copy.deepcopy(self.vendor),
            "buses": copy.deepcopy(self.buses),
            "measurement_system": system,
            "default_prefix": self.prefix,
            "points": points,
            "point_errors": errors,
            "presets": copy.deepcopy(self.presets),
            "alias_groups": [
                {"object_type": key[0], "instance": key[1], "point_ids": values}
                for key, values in addresses.items()
                if len(values) > 1
            ],
            "unknown_records": copy.deepcopy(self.unknown),
            "scope": SCOPE,
            "validation": "Observed XML subset checked; manufacturer XSD, package signature and device acceptance unverified.",
        }

    def selection(self, point_ids: list[str], system="imperial"):
        if (
            not isinstance(point_ids, list)
            or not 1 <= len(point_ids) <= 1000
            or any(not isinstance(key, str) for key in point_ids)
        ):
            raise ValueError("Select 1 through 1000 explicit native point identifiers.")
        if len(set(point_ids)) != len(point_ids):
            raise ValueError("Duplicate native point selection.")
        points = [self.point(key, system) for key in point_ids]
        used = {}
        for point in points:
            identity = point["object_type"], point["instance"]
            if identity in used:
                raise ValueError(
                    "Selected native points alias the same BACnet object: "
                    + used[identity]
                    + " and "
                    + point["id"]
                )
            used[identity] = point["id"]
        return {
            "definition_sha256": self.hash,
            "interface_name": self.name,
            "revision": self.revision,
            "vendor": copy.deepcopy(self.vendor),
            "buses": copy.deepcopy(self.buses),
            "measurement_system": system,
            "points": points,
            "scope": SCOPE,
            "can_apply": False,
        }

    def preset(self, identifier: str, system="imperial"):
        if not isinstance(identifier, str) or identifier not in self.presets:
            raise ValueError("Native hardware preset was not found.")
        return self.selection(list(self.presets[identifier]["points"]), system)


def plan_hardware_migration(
    old: JciHardwareDefinition, new: JciHardwareDefinition, point_ids: list[str], system="imperial"
):
    selection = old.selection(point_ids, system)
    if old.name != new.name or old.vendor["number"] != new.vendor["number"]:
        raise ValueError(
            "Native hardware migration requires the same interface and vendor identity."
        )
    metadata_before = {
        "revision": old.revision,
        "vendor": old.vendor,
        "buses": old.buses,
        "default_prefix": old.prefix,
    }
    metadata_after = {
        "revision": new.revision,
        "vendor": new.vendor,
        "buses": new.buses,
        "default_prefix": new.prefix,
    }
    interface_changes = {
        field: {"old": copy.deepcopy(value), "new": copy.deepcopy(metadata_after[field])}
        for field, value in metadata_before.items()
        if value != metadata_after[field]
    }
    changes, blocking = [], []
    for before in selection["points"]:
        identifier = before["id"]
        if identifier not in new.points:
            blocking.append(
                {
                    "id": identifier,
                    "reason": "Selected point was removed; no rename or replacement is guessed.",
                }
            )
            continue
        try:
            after = new.point(identifier, system)
        except ValueError as exc:
            blocking.append({"id": identifier, "reason": str(exc)})
            continue
        fields = {
            field: {"old": before[field], "new": after[field]}
            for field in before
            if before[field] != after[field]
        }
        if fields:
            changes.append(
                {
                    "id": identifier,
                    "fields": fields,
                    "requires_rebinding": bool(set(fields) & {"object_type", "instance"}),
                    "requires_program_review": bool(
                        set(fields) & {"direction", "value", "attributes", "write_strategy"}
                    ),
                }
            )
        if (
            before["direction"] != after["direction"]
            or before["value"]["type"] != after["value"]["type"]
        ):
            blocking.append({"id": identifier, "reason": "Native direction or value type changed."})
    if not blocking:
        try:
            new.selection(point_ids, system)
        except ValueError as exc:
            blocking.append({"id": "selection", "reason": str(exc)})
    return {
        "old_sha256": old.hash,
        "new_sha256": new.hash,
        "interface_name": old.name,
        "old_revision": old.revision,
        "new_revision": new.revision,
        "measurement_system": system,
        "interface_changes": interface_changes,
        "changes": changes,
        "blocking": blocking,
        "requires_review": bool(changes or blocking or interface_changes),
        "can_apply": False,
        "scope": SCOPE,
    }
