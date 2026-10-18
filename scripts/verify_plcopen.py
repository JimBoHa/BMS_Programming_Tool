#!/usr/bin/env python3
"""Validate every generated example against an independently supplied TC6 XSD.

The schema is not redistributed with this project. Install the dev extra and
provide a local, trusted copy of the PLCopen TC6 v2.01 schema.
"""

import argparse
import json
from pathlib import Path

from bms_tool.formats import export_plcopen
from bms_tool.templates import all_templates
from lxml import etree

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--schema", type=Path, required=True)
args = parser.parse_args()
schema = etree.XMLSchema(
    etree.parse(str(args.schema), etree.XMLParser(no_network=True, resolve_entities=False))
)
results = []
for program in all_templates():
    schema.assertValid(etree.fromstring(export_plcopen(program)))
    results.append({"program": program.id, "schema_valid": True})
print(
    json.dumps(
        {
            "schema": str(args.schema),
            "results": results,
            "external_compiler_or_hardware_validation": False,
        },
        indent=2,
    )
)
