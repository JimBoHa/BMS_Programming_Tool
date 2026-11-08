"""Independently authored offline engineering inputs; no building or vendor archive."""

import gzip
import io
import json
import zipfile

from .test_controller_application import authored_application

NAMESPACE = "http://johnsoncontrols.com/MetasysIII/2002/3/Core"
XML = (
    '<objects xmlns="' + NAMESPACE + '">'
    '<object ref="authored-controller" classid="194" classVersion="60">'
    '<property id="12"><data><string>unverified-tool-label</string></data></property>'
    '<property id="2390"><data><string>Authored source</string></data></property>'
    '</object><object ref="authored-system" classid="575" classVersion="62">'
    '<property id="65000"><data><struct><structElement>'
    "<string>opaque original data</string></structElement></struct></data></property>"
    "</object><jobInfo><unexamined>original metadata</unexamined></jobInfo></objects>"
).encode()
PROGRAM = {
    "schema_version": 1,
    "id": "authored-program",
    "name": "Authored engineering graph",
    "revision": 9007199254740993,
    "nodes": [],
    "edges": [],
    "metadata": {"opaque": ["preserve exact source", 73.125]},
}


def caf_source(xml=XML, *, second=False, encrypted=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(zipfile.ZipInfo("authored.xml", (1980, 1, 1, 0, 0, 0)), xml)
        archive.comment = b"Authored original"
        if second:
            archive.writestr("another.xml", b"<different/>")
    raw = bytearray(output.getvalue())
    if encrypted:
        raw[6] |= 1
        central = raw.index(b"PK\x01\x02")
        raw[central + 8] |= 1
    return bytes(raw)


def native_source(*, compressed=False, partial=False):
    raw = authored_application(target=8 if partial else 1)
    return raw if compressed else gzip.decompress(raw)


def program_source(*, bom=False, **changes):
    raw = json.dumps({**PROGRAM, **changes}, ensure_ascii=False).encode()
    return b"\xef\xbb\xbf" + raw if bom else raw
