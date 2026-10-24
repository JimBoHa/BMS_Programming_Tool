"""Guarded offline relocation of existing local UI bindings in observed CAFs.

Only two existing scalar leaves change. This is an archive edit, not native
compilation, a controller download, a cross-host relocation, or physical wiring.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile

from pydantic import Field

from .caf import CafArchive, Q
from .models import StrictModel

VMA_SOURCE = "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/VMA1615/1626/1628/1630-VAV-Controllers-Installation-Guide/K/Technical-specifications"
PCV_SOURCE = "https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-PCV1615/1626/1628/1630-Programmable-VAV-Box-Controllers-Installation-Instructions/H/Accessories/Technical-specifications"
MODELS = {
    "MS-VMA1630-0": VMA_SOURCE,
    "FX-PCV1630-0": PCV_SOURCE,
    "FX-PCV1615-0": PCV_SOURCE,
}
BOUNDARY = (
    "Offline existing-CAF terminal edit only. Native CCT/PCT reopen, validation, "
    "compilation and controller acceptance remain unverified. No controller "
    "program, live value, jumper or wiring is changed."
)


class HardwareMoveRequest(StrictModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ref: str = Field(min_length=1, max_length=240)
    old_slot: int = Field(ge=1, le=8, strict=True)
    destination_slot: int = Field(ge=1, le=8, strict=True)


class HardwareExportRequest(HardwareMoveRequest):
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class CafHardwareBindings:
    def __init__(self, caf: CafArchive):
        self.caf = caf

    @staticmethod
    def _properties(obj):
        return {p.get("id"): p for p in obj if p.tag == Q + "property"}

    def _scalar(self, props, pid, kind, attributes=None):
        prop = props.get(str(pid))
        scalar = self.caf.scalar(prop)
        if scalar is None or scalar["type"] != kind or scalar["attributes"] != (attributes or {}):
            raise ValueError(f"Hardware property {pid} has an unsupported scalar encoding.")
        return scalar["text"]

    def summary(self):
        result = {
            "profile": "caf-local-ui-bindings/1",
            "source_sha256": self.caf.hash,
            "offline_only": True,
            "native_download": False,
            "boundary": BOUNDARY,
            "supported": False,
            "inputs": [],
            "errors": [],
            "universal_slots": [1, 2, 3],
        }
        try:
            roots = [(r, o) for r, o in self.caf.objects.items() if o.get("classid") == "194"]
            if len(roots) != 1:
                raise ValueError("One observed native controller root is required.")
            root_ref, root = roots[0]
            if root.get("classVersion") != "1.0":
                raise ValueError("Unsupported native controller schema version.")
            root_props = self._properties(root)
            model = self._scalar(root_props, 70, "string")
            result["model"] = model
            if model not in MODELS:
                raise ValueError(
                    "This exact controller model has no supported CAF terminal-edit profile."
                )
            result["capacity_source"] = MODELS[model]
            release = self._scalar(root_props, 12, "string")
            result["release_mode"] = release
            if release not in {"10.1", "10.2"}:
                raise ValueError("Only observed CAF release modes 10.1 and 10.2 are supported.")
            device = self._scalar(root_props, 75, "BACoid", {"id": "8"})
            if (
                not re.fullmatch(r"[0-9]{1,7}", device)
                or int(device) > 4194302
                or str(int(device)) != device
                or root.get("objectid") != device
                or self._scalar(root_props, 32527, "string") != root_ref
            ):
                raise ValueError("Native controller identity or item reference is inconsistent.")
            result["device"] = f"device,{device}"
            if any(
                re.fullmatch(r"0*(?:598|910|243|671|673)", o.get("classid", ""))
                for o in self.caf.objects.values()
            ):
                raise ValueError(
                    "SA/IOM and other hardware classes are outside this local UI edit profile."
                )
            for obj in self.caf.objects.values():
                if obj.get("classid") in {"240", "242"}:
                    continue
                props = {str(int(pid)): prop for pid, prop in self._properties(obj).items()}
                label = (self.caf.scalar(props.get("31")) or {}).get("text", "")
                if "519" in props or re.fullmatch(r"(?:UI|BI|CI)\s+IN\s*[0-9]+", label, re.I):
                    raise ValueError(
                        "Unrecognized physical-looking hardware record could conceal terminal occupancy."
                    )
            occupied = set()
            for ref, obj in self.caf.objects.items():
                cid = obj.get("classid")
                if cid not in {"240", "242"}:
                    continue
                if obj.get("classVersion") != "1.0":
                    raise ValueError("Unsupported physical input schema version.")
                props = self._properties(obj)
                external_type = "0" if cid == "240" else "3"
                instance = self._scalar(props, 75, "BACoid", {"id": external_type})
                if (
                    not re.fullmatch(r"[0-9]{1,7}", instance)
                    or int(instance) > 4194302
                    or str(int(instance)) != instance
                    or obj.get("objectid") != instance
                    or ref != f"{root_ref}/{external_type}_{instance}"
                    or self._scalar(props, 32527, "string") != ref
                ):
                    raise ValueError(
                        "Physical input identity or local parent reference is inconsistent."
                    )
                if {str(int(pid)) for pid in props} & {"3645", "2577"}:
                    raise ValueError(
                        "Explicit SA/device-host bindings cannot be edited by this local profile."
                    )
                label = self._scalar(props, 31, "string")
                text_slot = self._scalar(props, 519, "unsignedByte")
                if not re.fullmatch(r"[0-9]{1,3}", text_slot) or str(int(text_slot)) != text_slot:
                    raise ValueError("Physical input slot has an unsupported encoding.")
                slot = int(text_slot)
                internal = (
                    cid == "240"
                    and label == "AI1-Int"
                    and slot == 4
                    and (self.caf.scalar(props.get("518")) or {}).get("type") == "enum"
                    and (self.caf.scalar(props.get("518")) or {}).get("text") == "9"
                )
                if not internal and (slot not in (1, 2, 3) or label != f"UI IN{slot}"):
                    raise ValueError(
                        "Input terminal is not an observed local universal input or internal DPT."
                    )
                if slot in occupied:
                    raise ValueError("Duplicate physical input slots make assignment ambiguous.")
                occupied.add(slot)
                result["inputs"].append(
                    {
                        "ref": ref,
                        "object": f"{'analog' if cid == '240' else 'binary'}-input,{instance}",
                        "class_id": cid,
                        "slot": slot,
                        "device_type": label,
                        "name": (self.caf.scalar(props.get("2390")) or {}).get("text", ""),
                        "movable": not internal,
                        "internal": internal,
                        "record_sha256": _hash(
                            {"attributes": obj.attrib, "properties": self.caf.properties(ref)}
                        ),
                    }
                )
            if not result["inputs"] or not any(p["movable"] for p in result["inputs"]):
                raise ValueError("No existing local universal input binding is available.")
            if not self.caf._patchable_xml:
                raise ValueError(
                    "Terminal editing requires observed UTF-8/ASCII XML serialization."
                )
            result["unassigned_slots"] = [n for n in (1, 2, 3) if n not in occupied]
            result["supported"] = True
        except ValueError as exc:
            result["errors"].append(str(exc))
            result["unassigned_slots"] = []
        return result

    def preview(self, request):
        request = HardwareMoveRequest.model_validate(
            request.model_dump() if isinstance(request, HardwareMoveRequest) else request
        )
        if request.source_sha256 != self.caf.hash:
            raise ValueError("CAF source hash changed; reopen and review this exact archive.")
        summary = self.summary()
        if not summary["supported"]:
            raise ValueError("; ".join(summary["errors"]))
        sources = [p for p in summary["inputs"] if p["ref"] == request.ref]
        if len(sources) != 1 or not sources[0]["movable"]:
            raise ValueError(
                "Choose an existing local UI; internal DPT and unknown inputs cannot move."
            )
        source = sources[0]
        if source["slot"] != request.old_slot:
            raise ValueError("Original terminal no longer matches the requested baseline.")
        if request.destination_slot not in (1, 2, 3):
            raise ValueError("Destination must be a documented universal input IN1, IN2 or IN3.")
        if (
            request.destination_slot != request.old_slot
            and request.destination_slot not in summary["unassigned_slots"]
        ):
            raise ValueError("Destination already has an assigned input.")
        if request.destination_slot != request.old_slot:
            # Parsed text alone does not prove a loss-preserving byte splice is
            # possible (for example, a scalar could contain CDATA or comments).
            # Refuse that serialization during review, before offering export.
            props = self._properties(self.caf.objects[request.ref])
            for pid in ("519", "31"):
                self.caf._scalar_span(props[pid][0][0])
        plan = {
            "profile": "caf-local-ui-relocation/1",
            "source_sha256": self.caf.hash,
            "model": summary["model"],
            "capacity_source": summary["capacity_source"],
            "request": request.model_dump(),
            "source": source,
            "changes": [
                {
                    "ref": request.ref,
                    "property": 519,
                    "type": "unsignedByte",
                    "old": str(request.old_slot),
                    "value": str(request.destination_slot),
                },
                {
                    "ref": request.ref,
                    "property": 31,
                    "type": "string",
                    "old": f"UI IN{request.old_slot}",
                    "value": f"UI IN{request.destination_slot}",
                },
            ]
            if request.destination_slot != request.old_slot
            else [],
            "preserved": [
                "External object identifier",
                "Object/item references",
                "Input setup and signal curve",
                "Application logic and connections",
                "Unknown properties and XML bytes",
            ],
            "native_validation": "pending",
            "offline_only": True,
            "native_download": False,
            "boundary": BOUNDARY,
        }
        plan["plan_sha256"] = _hash(plan)
        return plan

    def export(self, request):
        request = HardwareExportRequest.model_validate(
            request.model_dump() if isinstance(request, HardwareExportRequest) else request
        )
        plan = self.preview(request.model_dump(exclude={"plan_sha256"}))
        if request.plan_sha256 != plan["plan_sha256"]:
            raise ValueError("CAF terminal plan changed; preview the exact edit again.")
        if not plan["changes"]:
            return self.caf.original, plan
        edits = []
        for change in plan["changes"]:
            props = self._properties(self.caf.objects[change["ref"]])
            prop = props[str(change["property"])]
            a, b, before, after = self.caf._scalar_span(prop[0][0])
            edits.append((a, b, before + change["value"].encode("ascii") + after))
        xml = self.caf.xml
        for a, b, replacement in sorted(edits, reverse=True):
            xml = xml[:a] + replacement + xml[b:]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as container:
            container.comment = self.caf.comment
            container.writestr(copy.copy(self.caf.info), xml)
        data = output.getvalue()
        verified = CafArchive(data)
        if verified.xml != xml or list(verified.objects) != list(self.caf.objects):
            raise ValueError("Edited CAF failed exact XML/identity readback.")
        actual = CafHardwareBindings(verified).summary()
        if not actual["supported"]:
            raise ValueError("Edited CAF hardware inventory failed readback.")
        expected = copy.deepcopy(self.summary()["inputs"])
        for point in expected:
            if point["ref"] == request.ref:
                point.update(
                    slot=request.destination_slot, device_type=f"UI IN{request.destination_slot}"
                )

        def bindings(rows):
            return [{k: v for k, v in p.items() if k != "record_sha256"} for p in rows]

        if bindings(actual["inputs"]) != bindings(expected):
            raise ValueError("Edited CAF changed unexpected hardware bindings.")
        plan["output_sha256"] = hashlib.sha256(data).hexdigest()
        return data, plan
