"""Optional static checks against genuine external Niagara module/API descriptors.

These tests execute our adapter and inspect vendor XML metadata. They do not run
Niagara code, replace a runtime license, or redistribute the vendor SDK/source.
"""

import hashlib
import os
import re
import xml.etree.ElementTree as XML
import zipfile
from pathlib import Path

import pytest
from bms_tool.models import Edge, Node, Program
from bms_tool.niagara import NATIVE, SOURCE, UNITS, NiagaraArchive, export_bog

from tests.test_native_sedona import block_program


@pytest.fixture(scope="module")
def sdk():
    default = (
        Path(__file__).resolve().parents[2] / "Reference_Library/research/niagara-sdk-4.10.9.14"
    )
    directory = Path(os.environ.get("BMS_TEST_NIAGARA_SDK_DIR", default))
    pins = {
        "baja.jar": "8f8351b226a2e1c7d92f4639e6d3282ab6ccc0e04dc0d27b256b050f7fe746b1",
        "control-rt.jar": "87c2fa2baaed1f1e9be298e9dd66ffe99500210822d57d9a1abbb595309cc3ce",
        "kitControl-rt.jar": "680983fcab508a88da7b09b6fea32afdbb65552b7067be3ccb8b27887b11ee49",
        "docDeveloper-doc.jar": "f74c03e55492495a9e7ba0f077bd5ca24e42fe1b2bea1a1fcf8bcacc55c7b156",
        "nre-config-edge10.dist": "ef7c125446e318cdc993b80a5f6caadd24b9da50218b674171622f6d63dcc162",
    }
    if not directory.is_dir():
        pytest.skip("Optional genuine Niagara SDK metadata is not present.")
    for name, digest in pins.items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    return directory


class DescriptorRegistry:
    """Read declarative public type/slot documentation, with inherited properties."""

    def __init__(self, directory):
        self._descriptors, self._ancestors = {}, {}
        self.types = {}
        for name in ("baja.jar", "control-rt.jar", "kitControl-rt.jar"):
            with zipfile.ZipFile(directory / name) as archive:
                module = XML.fromstring(archive.read("META-INF/module.xml"))
            namespace = module.get("moduleName", module.get("name"))
            for descriptor in module.findall("./types/type"):
                self.types[namespace + ":" + descriptor.get("name")] = descriptor.get("class")
        self.docs = zipfile.ZipFile(directory / "docDeveloper-doc.jar")
        self.documents = {
            name.split("/", 2)[2].removesuffix(".bajadoc").replace("/", "."): name
            for name in self.docs.namelist()
            if name.startswith("doc/") and name.endswith(".bajadoc") and name.count("/") >= 3
        }

    def descriptor(self, class_name):
        assert class_name in self.documents, class_name
        if class_name not in self._descriptors:
            self._descriptors[class_name] = XML.fromstring(
                self.docs.read(self.documents[class_name])
            ).find("class")
        return self._descriptors[class_name]

    def ancestors(self, class_name):
        if class_name == "java.lang.Object":
            return ()
        if class_name in self._ancestors:
            return self._ancestors[class_name]
        descriptor = self.descriptor(class_name)
        parent = descriptor.find("./extends/type")
        self._ancestors[class_name] = (class_name,) + (
            self.ancestors(parent.get("class")) if parent is not None else ()
        )
        return self._ancestors[class_name]

    def properties(self, class_name):
        result = {}
        primitives = {
            "double": "javax.baja.sys.BDouble",
            "float": "javax.baja.sys.BFloat",
            "int": "javax.baja.sys.BInteger",
            "long": "javax.baja.sys.BLong",
            "boolean": "javax.baja.sys.BBoolean",
            "java.lang.String": "javax.baja.sys.BString",
        }
        for ancestor in reversed(self.ancestors(class_name)):
            for prop in self.descriptor(ancestor).findall("property"):
                native = prop.find("type").get("class")
                result[prop.get("name")] = primitives.get(native, native)
        return result

    def check(self, document):
        symbols, components, links = {}, {}, []

        def walk(element, parent_class=None):
            declaration = element.get("m")
            if declaration:
                alias, module = declaration.split("=", 1)
                symbols[alias] = module
            encoded = element.get("t")
            frozen = self.properties(parent_class).get(element.get("n")) if parent_class else None
            if encoded:
                alias, name = encoded.split(":", 1)
                native_type = symbols[alias] + ":" + name
                assert native_type in self.types, native_type
                actual = self.types[native_type]
                assert frozen is None or actual == frozen, (element.attrib, frozen, actual)
            else:
                assert frozen, (element.attrib, parent_class)
                actual = frozen
            if element.get("h"):
                components[element.get("h")] = actual
            if actual == "javax.baja.sys.BLink":
                values = {child.get("n"): child.get("v") for child in element.findall("p")}
                links.append((parent_class, values))
            if "v" in element.attrib:
                assert "javax.baja.sys.BSimple" in self.ancestors(actual), (element.attrib, actual)
                assert not len(element)
            for child in element:
                if child.tag == "p":
                    walk(child, actual)

        for root in document.findall("p"):
            walk(root)
        for target_class, values in links:
            source = components[values["sourceOrd"].removeprefix("h:")]
            source_type = self.properties(source)[values["sourceSlotName"]]
            target_type = self.properties(target_class)[values["targetSlotName"]]
            assert source_type == target_type, (values, source_type, target_type)


@pytest.mark.parametrize("kind", [*NATIVE, "Input", "Output", "Constant", "Switch"])
def test_exported_component_types_and_all_frozen_slot_types_match_genuine_vendor_descriptors(
    sdk, kind
):
    registry = DescriptorRegistry(sdk)
    try:
        document = XML.fromstring(
            SOURCE.sub(b"", NiagaraArchive(export_bog(block_program(kind))).xml)
        )
        registry.check(document)
    finally:
        registry.docs.close()


@pytest.mark.parametrize("kind", ["Input", "Constant", "Switch"])
def test_native_boolean_variants_match_genuine_vendor_descriptors(sdk, kind):
    nodes = [
        Node(
            id="source",
            kind=kind,
            value_type="boolean",
            params={"value": True}
            if kind == "Constant"
            else {"default": True}
            if kind == "Input"
            else {},
        )
    ]
    edges = []
    if kind == "Switch":
        for index, port in enumerate(("select", "on", "off")):
            identifier = "input" + str(index)
            nodes.append(
                Node(id=identifier, kind="Input", value_type="boolean", params={"default": True})
            )
            edges.append(Edge(id=port, source=identifier, target="source", target_port=port))
    nodes.append(Node(id="result", kind="Output", value_type="boolean"))
    edges.append(Edge(id="out", source="source", target="result"))
    registry = DescriptorRegistry(sdk)
    try:
        document = XML.fromstring(
            SOURCE.sub(b"", NiagaraArchive(export_bog(Program(nodes=nodes, edges=edges))).xml)
        )
        registry.check(document)
    finally:
        registry.docs.close()


def test_exported_unit_records_match_genuine_native_unit_database(sdk):
    with zipfile.ZipFile(sdk / "nre-config-edge10.dist") as archive:
        database = XML.fromstring(archive.read("defaults/units.xml"))
    entries = {
        unit.get("n"): (quantity.get("dim"), unit.attrib)
        for quantity in database.findall("quantity")
        for unit in quantity.findall("unit")
    }
    for encoded in UNITS.values():
        name, symbol, dimension, transform, end = encoded.split(";")
        actual_dimension, entry = entries[name]
        assert not end and dimension == actual_dimension
        assert symbol == entry.get("s", "")
        match = re.fullmatch(r"(?:\*([^+]+))?(?:\+(.+))?", transform)
        assert match
        assert float(match[1] or 1) == float(entry.get("scale", 1))
        assert float(match[2] or 0) == float(entry.get("offset", 0))


def test_genuine_native_palette_module_aliases_are_resolved_across_folders(sdk):
    with zipfile.ZipFile(sdk / "kitControl-rt.jar") as archive:
        original = archive.read("module.palette")
    inspected = NiagaraArchive(original)
    reported = inspected.summary()["unhandled_typed_records"]
    assert reported
    # The real palette declares its module once and reuses that symbol later.
    assert all(
        ":" not in record["type"]
        or record["type"].split(":")[0] in {"kitControl", "control", "baja", "alarm"}
        for record in reported
    )
    assert inspected.export() == original
