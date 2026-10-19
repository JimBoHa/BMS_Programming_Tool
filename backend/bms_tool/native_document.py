"""Data-only, versioned native component extension for saved Sedona projects."""

import math
import struct
from collections import Counter
from typing import Literal
from xml.etree import ElementTree as XML

from pydantic import Field, model_validator

from .models import StrictModel

TYPES = {
    "types::WriteFloat": ({"in"}, {"in"}, "number"),
    "types::ConstFloat": ({"out"}, set(), "number"),
    "types::WriteBool": ({"in"}, {"in"}, "boolean"),
    "types::ConstBool": ({"out"}, set(), "boolean"),
    "math::Add2": (set(), {"in1", "in2"}, "number"),
    "math::Sub2": (set(), {"in1", "in2"}, "number"),
    "math::Mul2": (set(), {"in1", "in2"}, "number"),
    "math::Div2": (set(), {"in1", "in2"}, "number"),
    "math::Min": (set(), {"in1", "in2"}, "number"),
    "math::Max": (set(), {"in1", "in2"}, "number"),
}


class NativeComponent(StrictModel):
    path: str = Field(pattern=r"^/online(?:/[A-Za-z][A-Za-z0-9_]{0,6}){1,16}$")
    type: str
    properties: dict[str, str] = Field(default_factory=dict, max_length=2)


class NativeLink(StrictModel):
    source: str
    source_port: Literal["out"] = "out"
    target: str
    target_port: str


class NativeDocument(StrictModel):
    version: Literal[1] = 1
    components: list[NativeComponent] = Field(default_factory=list, max_length=400)
    links: list[NativeLink] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def check_graph(self):
        paths = {}
        children = Counter()
        for component in self.components:
            if component.path in paths or component.type not in TYPES:
                raise ValueError("Duplicate native component path or unsupported native type.")
            parent = component.path.rsplit("/", 1)[0]
            children[parent] += 1
            if children[parent] > 200:
                raise ValueError("Native component exceeds the SDK's 200-child limit.")
            if parent != "/online" and parent not in paths:
                raise ValueError("Native parent must precede its child in the saved document.")
            paths[component.path] = component
            config, _, typ = TYPES[component.type]
            if component.properties.keys() - config:
                raise ValueError("Only persistent native configuration properties can be saved.")
            for text in component.properties.values():
                if text == "null":
                    continue
                if typ == "boolean":
                    if text not in ("true", "false"):
                        raise ValueError("Native Boolean must be true, false, or null.")
                else:
                    try:
                        value = float(text)
                        native = struct.unpack("f", struct.pack("f", value))[0]
                    except (ValueError, OverflowError, struct.error) as exc:
                        raise ValueError("Native number exceeds the float32 range.") from exc
                    if not math.isfinite(native) or (value != 0 and native == 0):
                        raise ValueError(
                            "Native number must be finite and representable as float32."
                        )
        writers = set()
        for link in self.links:
            if link.source not in paths or link.target not in paths:
                raise ValueError("Native link references a missing component.")
            source, target = paths[link.source], paths[link.target]
            _, target_ports, target_type = TYPES[target.type]
            if link.target_port not in target_ports or TYPES[source.type][2] != target_type:
                raise ValueError("Native link port/type mismatch.")
            if (link.target, link.target_port) in writers:
                raise ValueError("Native input has multiple writers.")
            writers.add((link.target, link.target_port))
        return self

    def attach(self, app, links):
        by_path = {
            "/online": XML.SubElement(app, "comp", {"name": "online", "type": "sys::Folder"})
        }
        for component in self.components:
            parent, name = component.path.rsplit("/", 1)
            element = XML.SubElement(
                by_path[parent], "comp", {"name": name, "type": component.type}
            )
            by_path[component.path] = element
            for name, value in component.properties.items():
                XML.SubElement(element, "prop", {"name": name, "val": value})
        for link in self.links:
            XML.SubElement(
                links,
                "link",
                {
                    "from": link.source + "." + link.source_port,
                    "to": link.target + "." + link.target_port,
                },
            )

    @classmethod
    def from_snapshot(cls, snapshot):
        components = [c for c in snapshot["components"] if c["path"].startswith("/online/")]
        by_id = {c["id"]: c for c in components}
        links = []
        for component in components:
            for link in component["links"]:
                target = by_id.get(int(link["to"]))
                if target is None:
                    raise ValueError("Native snapshot has an external component link.")
                source_port = next(
                    p["name"] for p in component["properties"] if p["id"] == link["from_slot"]
                )
                target_port = next(
                    p["name"] for p in target["properties"] if p["id"] == link["to_slot"]
                )
                links.append(
                    {
                        "source": component["path"],
                        "source_port": source_port,
                        "target": target["path"],
                        "target_port": target_port,
                    }
                )
        return cls.model_validate(
            {
                "components": [
                    {
                        "path": c["path"],
                        "type": c["type"],
                        "properties": {
                            p["name"]: p["value"]
                            for p in c["properties"]
                            if p["config"] == "true" and p["name"] != "meta"
                        },
                    }
                    for c in components
                ],
                "links": links,
            }
        )
