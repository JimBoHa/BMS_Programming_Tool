"""Read-only, versioned reference names; never source names or executable meanings."""

import copy
import json
import re
from functools import lru_cache
from pathlib import Path

from .caf import CafArchive
from .caf_graph import CafGraph, _properties
from .moi_identity import seal, sha

PROFILE = "caf-reference-labels/1"
CATALOG_PROFILE = "oct-fdb-control-10.8-firmware-12.0/1"
CATALOG_SHA256 = "d155e2fac61c7e0c0455f4e25d749831993b4f72b6ad8d433008f3840f3a4515"
CATALOG_FILE = Path(__file__).with_name("data") / "cafReferenceLabels.json"


@lru_cache(maxsize=1)
def _catalog():
    try:
        raw = CATALOG_FILE.read_bytes()
    except OSError as exc:
        raise ValueError(
            "Packaged reference names are unavailable; raw CAF references remain usable."
        ) from exc
    if sha(raw) != CATALOG_SHA256:
        raise ValueError(
            "Packaged reference names failed their recorded digest; raw CAF references remain usable."
        )
    data = json.loads(raw)
    if data.get("profile") != CATALOG_PROFILE:
        raise ValueError("Packaged reference names have an unknown profile.")
    return data


class CafReferenceLabels:
    def __init__(self, archive):
        self.archive = archive if isinstance(archive, CafArchive) else CafArchive(archive)

    def _field(self, props, pid, permitted, catalog):
        scalar = copy.deepcopy(self.archive.scalar(props.get(pid)))
        result = {
            "property_id": int(pid),
            "observed": scalar,
            "enum_set": None,
            "code": None,
            "reference_name": None,
            "status": "absent" if pid not in props else "unsupported_encoding",
        }
        if scalar is None or scalar["type"] != "enum" or set(scalar["attributes"]) != {"set"}:
            return result
        raw_set = scalar["attributes"]["set"]
        text = scalar["text"]
        if (
            raw_set not in permitted
            or not re.fullmatch(r"0|[1-9][0-9]{0,9}", text)
            or int(text) > 4294967295
        ):
            return result
        name = catalog["enum_sets"][raw_set]["members"].get(text)
        return {
            **result,
            "enum_set": int(raw_set),
            "code": int(text),
            "reference_name": name,
            "status": "reference_label" if name is not None else "unmapped",
        }

    def diagram(self, ref):
        graph = CafGraph(self.archive).diagram(ref)
        catalog = _catalog()
        rows = []
        for block in graph["blocks"]:
            props = _properties(self.archive.objects[block["ref"]])
            rows.append(
                {
                    "index": block["index"],
                    "ref": block["ref"],
                    "class_id": block["class_id"],
                    "instance": block["instance"],
                    "standard_name": self._field(props, "3670", {"432"}, catalog),
                    "setup": self._field(props, "518", {"287", "288"}, catalog),
                }
            )
        body = {
            "profile": PROFILE,
            "source_sha256": self.archive.hash,
            "diagram_ref": ref,
            "catalog": {
                "profile": CATALOG_PROFILE,
                "sha256": CATALOG_SHA256,
                "source": copy.deepcopy(catalog["source"]),
                "sets": [
                    {"id": int(k), "name": v["name"], "members": len(v["members"])}
                    for k, v in sorted(catalog["enum_sets"].items())
                ],
                "archive_compatibility_verified": False,
            },
            "rows": rows,
            "controller_write": False,
            "field_requests": 0,
            "runtime_meaning_verified": False,
        }
        return {**body, "annotation_sha256": seal(body)}
