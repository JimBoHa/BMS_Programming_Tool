"""Offline JCI bus declarations; no protocol client or physical wiring inspection."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .models import StrictModel

FORMAT = "bms.jci-bus-plan"
Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:+-]{1,80}$")]
Name = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^\S(?:[^\x00-\x1f]*\S)?$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MAX_BYTES = 2 * 1024 * 1024
SCOPE = "Offline operator-declared physical buses, devices, links and EOL settings only. No field scans, address changes, measured wiring, power/cable certification or controller writes. Unknown model/generation, cable and capacity facts remain unresolved. Separate physical bus keys scope MAC comparisons; network numbers do not identify these buses."
SOURCES = {
    "metasys-r15": {
        "document": "LIT-12011034",
        "revision": "15.0",
        "date": "2026-09-29",
        "section": "PDF 18–21 (addresses), 23–26 (FC), 29–32 (SA), 39–40 (connections)",
        "artifact": "publisher PDF bytes",
        "sha256": "18c323a65edec4fe29120bab29d38303bf57e9b21fe1b1a108eb597c077aee37",
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/MS/TP-Communications-Bus-Technical-Bulletin/15.0",
    },
    "fx-2024": {
        "document": "LIT-12011670",
        "revision": "2024-12-11",
        "date": "2024-12-11",
        "section": "PDF 10–12 (addresses), 14–18 (FC), 19–22 (SA), 25–28 (connections)",
        "artifact": "publisher PDF bytes; cover date overrides legacy download filename",
        "sha256": "30b55a915954c78a05ecea598ce1890494629ff78451660a2f440785774c2605",
        "url": "https://docs.johnsoncontrols.com/bas/r/Facility-Explorer/en-US/FX-MS/TP-Communications-Bus-Technical-Bulletin",
    },
    "sensor-access": {
        "document": "LIT-12013113 refreshed NS8000; LIT-1900348 handheld tool",
        "revision": "NS8000 2025-12-08; handheld 2018-06-01",
        "section": "Primary publisher Overview, Technical specifications and Selection charts; handheld Technical specifications",
        "artifact": "publisher text-extraction capture 2026-10-21; not PDF bytes",
        "sha256": "89688cc647251a30cf3170bb760c0b1a2c5882100e3ed86a965882e3b351a9f8",
        "url": "https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Product-Bulletin-Refreshed-Models/Overview",
        "supporting_urls": [
            "https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Product-Bulletin-Refreshed-Models/Technical-specifications",
            "https://docs.johnsoncontrols.com/bas/r/Johnson-Controls/en-US/NS8000-Series-Network-Sensors-Product-Bulletin-Refreshed-Models/Selection-charts",
            "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Handheld-VAV-Balancing-Tool-Catalog-Page/Handheld-VAV-Balancing-Tool/Handheld-VAV-Balancing-Tool-Technical-Specifications",
        ],
    },
}
# This deliberately narrow model set does not expand by prefix or controller generation.
MODELS = {
    **{
        m: {
            "family": "fx-2024",
            "class": "controller",
            "legacy_mode_128": True,
            "generation": "legacy-dip128",
        }
        for m in ["FX-PCG2611-0", "FX-PCG2621-0", "FX-PCV1615-0", "FX-PCV1630-0"]
    },
    **{
        m: {
            "family": "fx-2024",
            "class": "iom",
            "legacy_mode_128": True,
            "generation": "legacy-dip128",
        }
        for m in ["FX-PCX3711-0", "FX-PCX3721-0"]
    },
    **{
        m: {
            "family": "metasys-r15",
            "class": "controller",
            "legacy_mode_128": True,
            "generation": "legacy-dip128",
        }
        for m in ["MS-VMA1615-0", "MS-VMA1630-0"]
    },
    **{
        m: {
            "family": "sensor-access",
            "class": "sensor",
            "sensor_range": [199, 206],
            "service_port": True,
            "address_setting": "DIP",
            "generation": "refreshed-2025-12-08",
        }
        for m in ["NSB8BTN040-0", "NSB8BTN240-0"]
    },
    "TL-CWCVT-0": {"family": "metasys-r15", "class": "converter", "address": 2},
    "NS-ATV7003-0": {"family": "sensor-access", "class": "balancing", "address": 198},
}


def canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Bus plan requires bounded finite JSON.") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


CATALOG = {
    "id": "jci-bus-preflight/1",
    "sources": SOURCES,
    "models": MODELS,
    "limits": {"buses": 32, "nodes": 256, "links": 512, "bytes": MAX_BYTES},
}
CATALOG["sha256"] = digest(CATALOG)


class Bus(StrictModel):
    id: Key
    name: Name
    profile: Literal["metasys-r15", "fx-2024", "unknown"] = "unknown"
    kind: Literal["fc", "sa", "unknown"] = "unknown"
    segments: list[Key] = Field(default_factory=lambda: ["segment-1"], min_length=1, max_length=16)
    inventory_complete: bool = Field(default=False, strict=True)
    nce_integral: Literal["present", "absent", "unknown"] = "unknown"
    zfr1810_coordinators: Literal["present", "absent", "unknown"] = "unknown"
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def segment_keys(self):
        if len(set(self.segments)) != len(self.segments):
            raise ValueError("Bus segment keys must be unique.")
        return self


class Device(StrictModel):
    id: Key
    bus_id: Key
    label: Name
    model: str = Field(default="", max_length=120)
    generation: str | None = Field(default=None, max_length=120)
    role: Literal[
        "fc-host",
        "sa-host",
        "field-controller",
        "iom",
        "fit",
        "converter",
        "display",
        "network-sensor",
        "handheld-balancer",
        "subordinate",
        "nce-integral",
        "zfr1810",
        "repeater-port",
        "unknown",
    ] = "unknown"
    mac: int | None = Field(default=None, ge=0, le=255, strict=True)
    segment: Key | None = None
    mode: Literal["wired", "wireless", "unknown"] = "unknown"
    switch128: Literal["on", "off", "not-applicable", "unknown"] = "unknown"
    eol: Literal["on", "off", "fixed-on", "unknown"] = "unknown"
    notes: str = Field(default="", max_length=2000)


class Link(StrictModel):
    id: Key
    a: Key
    b: Key
    kind: Literal["terminal", "modular", "sensor-service", "repeater-bridge", "unknown"] = "unknown"
    length_m: Annotated[float, Field(ge=0, le=100000, strict=True, allow_inf_nan=False)] | None = (
        None
    )
    straight_through: bool | None = Field(default=None, strict=True)
    notes: str = Field(default="", max_length=2000)


class BusPlan(StrictModel):
    format: Literal["bms.jci-bus-plan"] = FORMAT
    version: Literal[1] = 1
    catalog_sha256: Hash
    name: Name
    notes: str = Field(default="", max_length=4000)
    buses: list[Bus] = Field(default_factory=list, max_length=32)
    devices: list[Device] = Field(default_factory=list, max_length=256)
    links: list[Link] = Field(default_factory=list, max_length=512)

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if isinstance(value, dict) and (
            value.get("format") != FORMAT or type(value.get("version")) is not int
        ):
            raise ValueError("Bus plan requires explicit format and integer version 1.")
        return value

    @model_validator(mode="after")
    def identities(self):
        if self.catalog_sha256 != CATALOG["sha256"]:
            raise ValueError(
                "Bus source catalog changed; review current evidence and rebind explicitly."
            )
        for rows in (self.buses, self.devices, self.links):
            if len({r.id for r in rows}) != len(rows):
                raise ValueError("Bus, device and link IDs must be unique within each category.")
        buses = {b.id: b for b in self.buses}
        devices = {d.id: d for d in self.devices}
        pairs = set()
        for device in self.devices:
            bus = buses.get(device.bus_id)
            if bus is None or (device.segment is not None and device.segment not in bus.segments):
                raise ValueError(
                    "Every device needs an existing bus and declared segment or explicit unknown segment."
                )
        for link in self.links:
            a, b = devices.get(link.a), devices.get(link.b)
            if a is None or b is None or a.id == b.id or a.bus_id != b.bus_id:
                raise ValueError(
                    "Links require two distinct existing devices on the same declared physical bus."
                )
            pair = tuple(sorted((a.id, b.id)))
            if pair in pairs:
                raise ValueError(
                    "Duplicate physical links are ambiguous; each device pair may appear once."
                )
            pairs.add(pair)
        return self


def template():
    return BusPlan(
        format=FORMAT, version=1, catalog_sha256=CATALOG["sha256"], name="New JCI bus plan"
    ).model_dump()


def validate_plan(value):
    if len(canonical(value)) > MAX_BYTES:
        raise ValueError("Bus plan exceeds 2 MiB.")
    return BusPlan.model_validate(value)


def review(value):
    plan = validate_plan(value)
    findings = []
    by_id = {d.id: d for d in plan.devices}

    def add(code, severity, message, bus=None, devices=(), links=(), category="topology"):
        if severity == "error" and category == "topology" and bus and bus.profile == "unknown":
            severity = "unknown"
        f = {
            "code": code,
            "severity": severity,
            "category": category,
            "message": message,
            "bus_id": bus.id if bus else None,
            "device_ids": sorted(d.id for d in devices),
            "link_ids": sorted(link.id for link in links),
        }
        f["id"] = digest(f)
        findings.append(f)

    if not plan.buses:
        add("no-buses", "unknown", "No physical buses were declared.")
    summaries = []
    for bus in plan.buses:
        devices = [d for d in plan.devices if d.bus_id == bus.id]
        links = [link for link in plan.links if by_id[link.a].bus_id == bus.id]
        if bus.profile == "unknown" or bus.kind == "unknown":
            add(
                "bus-profile-unresolved",
                "unknown",
                "Bus-specific address and topology rules require an explicit reviewed bus type/profile.",
                bus,
            )
        if not bus.inventory_complete:
            add(
                "inventory-incomplete",
                "unknown",
                "Not all devices and cable connections are declared included.",
                bus,
            )
        if not devices:
            add("no-devices", "unknown", "This declared bus has no device connections.", bus)
        assigned = defaultdict(list)
        for d in devices:
            model = MODELS.get(d.model)
            generation_known = model is not None and (
                not model.get("generation") or d.generation == model["generation"]
            )
            if model and not generation_known:
                add(
                    "device-generation-unverified",
                    "unknown",
                    "Model alone does not confirm the selected hardware generation; switch decoding and service-port exceptions remain unresolved.",
                    bus,
                    [d],
                    category="address",
                )
            if model is None:
                add(
                    "model-generation-unverified",
                    "unknown",
                    "Exact device model/generation has no reviewed profile; role declarations are not manufacturer approval.",
                    bus,
                    [d],
                    category="address",
                )
            if d.mac is None and d.role != "repeater-port":
                add(
                    "mac-unknown",
                    "unknown",
                    "The bus connection's MAC address is unknown.",
                    bus,
                    [d],
                    category="address",
                )
            if d.mac == 255:
                add(
                    "broadcast-not-device",
                    "error",
                    "255 is broadcast and cannot be assigned to a device.",
                    bus,
                    [d],
                    category="address",
                )
            elif d.mac is not None:
                assigned[d.mac].append(d)
            if d.role == "repeater-port" and d.mac is not None:
                add(
                    "repeater-mac-unverified",
                    "unknown",
                    "A declared repeater-side physical connection is not a verified addressed BACnet device; its supplied MAC is still checked for duplication.",
                    bus,
                    [d],
                    category="address",
                )
            if d.segment is None:
                add("segment-unknown", "unknown", "Device's physical segment is unknown.", bus, [d])
            if d.role == "unknown":
                add(
                    "role-unknown",
                    "unknown",
                    "Unknown device role cannot establish reserved-address ownership.",
                    bus,
                    [d],
                    category="address",
                )
            if model:
                expected = {
                    "controller": {"field-controller", "sa-host"},
                    "iom": {"iom"},
                    "sensor": {"network-sensor"},
                    "converter": {"converter"},
                    "balancing": {"handheld-balancer"},
                }[model["class"]]
                if d.role not in expected:
                    add(
                        "model-role-conflict",
                        "error",
                        "Declared role conflicts with this exact model's reviewed device class.",
                        bus,
                        [d],
                        category="address",
                    )
                if d.role == "sa-host" and model["family"] != bus.profile:
                    add(
                        "host-family-profile-unresolved",
                        "unknown",
                        "This SA host's manufacturer family does not match the selected reviewed bus profile.",
                        bus,
                        [d],
                    )
                if (
                    model.get("legacy_mode_128")
                    and generation_known
                    and d.role in ("field-controller", "iom")
                ):
                    if d.mode == "unknown" or d.switch128 in ("unknown", "not-applicable"):
                        add(
                            "legacy-switch-unresolved",
                            "unknown",
                            "This legacy model uses switch128 for wireless mode, not an address bit; declare mode and on/off setting.",
                            bus,
                            [d],
                            category="address",
                        )
                    elif (d.mode == "wired" and d.switch128 == "on") or (
                        d.mode == "wireless" and d.switch128 == "off"
                    ):
                        add(
                            "wireless-switch-mode-conflict",
                            "error",
                            "Legacy switch128 must be OFF on the wired device connection and ON for its supported wireless mode; it is never added to the MAC.",
                            bus,
                            [d],
                            category="address",
                        )
                elif d.switch128 == "on" and d.role != "sa-host":
                    add(
                        "switch-interpretation-unverified",
                        "unknown",
                        "No reviewed switch128 interpretation is established for this model/connection.",
                        bus,
                        [d],
                        category="address",
                    )
            elif d.switch128 not in ("unknown", "not-applicable"):
                add(
                    "switch-interpretation-unverified",
                    "unknown",
                    "Unknown model/generation prevents interpreting switch128 as mode or address.",
                    bus,
                    [d],
                    category="address",
                )
            if d.mode == "wireless":
                add(
                    "wireless-topology-unverified",
                    "unknown",
                    "Wireless coordinator/system configuration and topology are outside this wired-plan profile.",
                    bus,
                    [d],
                )
            elif d.mode == "unknown":
                add(
                    "connection-mode-unknown",
                    "unknown",
                    "Wired/wireless connection mode is undeclared.",
                    bus,
                    [d],
                )
            if bus.profile == "unknown" or bus.kind == "unknown" or d.mac is None or d.mac == 255:
                continue
            mac = d.mac
            role = d.role
            if role == "sa-host":
                if bus.kind != "sa":
                    add(
                        "host-bus-role-conflict",
                        "error",
                        "An SA host connection belongs on its own SA bus, not the FC bus.",
                        bus,
                        [d],
                        category="address",
                    )
                elif mac != 0:
                    add(
                        "sa-host-fixed-zero",
                        "error",
                        "The SA host MAC is fixed at 0; its upstream FC address is a separate bus connection.",
                        bus,
                        [d],
                        category="address",
                    )
            elif role == "fc-host":
                if bus.kind != "fc":
                    add(
                        "host-bus-role-conflict",
                        "error",
                        "An FC supervisory connection is not an SA host.",
                        bus,
                        [d],
                        category="address",
                    )
                elif mac != 0:
                    add(
                        "fc-host-nondefault-unverified",
                        "unknown",
                        "The reviewed FC supervisor default is 0; no exact nondefault host profile is established here.",
                        bus,
                        [d],
                        category="address",
                    )
            elif role in ("field-controller", "iom", "nce-integral", "zfr1810"):
                if role == "nce-integral" and mac != 4:
                    add(
                        "nce-integral-fixed-four",
                        "error",
                        "The reviewed NCE integral-controller reservation is address 4.",
                        bus,
                        [d],
                        category="address",
                    )
                if not 4 <= mac <= 127:
                    add(
                        "manager-address-range",
                        "error",
                        "The declared manager role requires 4..127; 0..3 are reserved for host/tools/display and 128..254 are not manager MACs.",
                        bus,
                        [d],
                        category="address",
                    )
                if bus.kind == "sa" and role != "iom":
                    add(
                        "sa-endpoint-role-conflict",
                        "error",
                        "This reviewed SA profile permits I/O expansion managers, not ordinary field controllers/coordinators as downstream controllers.",
                        bus,
                        [d],
                        category="address",
                    )
                if bus.profile == "metasys-r15" and bus.kind == "fc":
                    if mac == 4:
                        if bus.nce_integral == "present" and role != "nce-integral":
                            add(
                                "nce-integral-address-reserved",
                                "error",
                                "Address4 is reserved for the NCE integral controller in this declared NCE context.",
                                bus,
                                [d],
                                category="address",
                            )
                        elif bus.nce_integral == "unknown":
                            add(
                                "nce-context-unknown",
                                "unknown",
                                "Confirm whether an NCE integral controller reserves address 4 on this bus.",
                                bus,
                                [d],
                                category="address",
                            )
                    if 120 <= mac <= 127:
                        if bus.zfr1810_coordinators == "present" and role != "zfr1810":
                            add(
                                "zfr1810-address-reserved",
                                "error",
                                "120..127 are reserved for multiple ZFR1810 coordinators in this declared context.",
                                bus,
                                [d],
                                category="address",
                            )
                        elif bus.zfr1810_coordinators == "unknown":
                            add(
                                "zfr1810-context-unknown",
                                "unknown",
                                "Confirm whether ZFR1810 coordinators reserve 120..127; no inference for other coordinator generations.",
                                bus,
                                [d],
                                category="address",
                            )
            elif role in ("fit", "converter", "display"):
                target = {"fit": 1, "converter": 2, "display": 3}[role]
                if mac != target:
                    add(
                        "tool-display-reserved-address",
                        "error",
                        f"The selected reviewed role uses reserved address {target}.",
                        bus,
                        [d],
                        category="address",
                    )
                if role == "display" and bus.kind != "sa":
                    add(
                        "display-fc-support-unverified",
                        "unknown",
                        "The reviewed physical display connection is SA; FC use is not established by a reserved number alone.",
                        bus,
                        [d],
                        category="address",
                    )
            elif role in ("network-sensor", "handheld-balancer", "subordinate"):
                if bus.kind != "sa":
                    add(
                        "fc-subordinate-unsupported",
                        "error",
                        "These subordinate/sensor roles are not supported on the reviewed FC bus.",
                        bus,
                        [d],
                        category="address",
                    )
                if role == "handheld-balancer" and mac != 198:
                    add(
                        "balancer-fixed-address",
                        "error",
                        "The reviewed handheld balancing tool has fixed address 198.",
                        bus,
                        [d],
                        category="address",
                    )
                elif role == "network-sensor":
                    if model and generation_known and model.get("sensor_range"):
                        low, high = model["sensor_range"]
                        if not low <= mac <= high:
                            add(
                                "sensor-model-address-range",
                                "error",
                                f"This exact sensor profile uses {low}..{high}; switch128 is not its legacy controller wireless mode.",
                                bus,
                                [d],
                                category="address",
                            )
                    else:
                        add(
                            "sensor-address-profile-unresolved",
                            "unknown",
                            "Sensor address ranges depend on exact model/generation;199..219 are reserved for particular sensors, not a generic available pool.",
                            bus,
                            [d],
                            category="address",
                        )
                elif role == "subordinate":
                    if not 128 <= mac <= 254:
                        add(
                            "sa-subordinate-range",
                            "error",
                            "SA subordinate addresses lie in 128..254.",
                            bus,
                            [d],
                            category="address",
                        )
                    elif 198 <= mac <= 219:
                        add(
                            "sensor-reservation-owner-unverified",
                            "unknown",
                            "198..219 include documented balancing/network-sensor reservations; no arbitrary subordinate allocation is approved.",
                            bus,
                            [d],
                            category="address",
                        )
        for mac, rows in sorted(assigned.items()):
            if len(rows) > 1:
                add(
                    "duplicate-mac-on-bus",
                    "error",
                    f"MAC {mac} is repeated on this declared physical bus, including across repeater segments. Other physical buses are independent.",
                    bus,
                    rows,
                    category="address",
                )
        hosts = [d for d in devices if d.role == ("sa-host" if bus.kind == "sa" else "fc-host")]
        if bus.kind == "sa":
            if len(hosts) != 1:
                add(
                    "sa-single-host",
                    "error" if len(hosts) > 1 else "unknown",
                    "An SA bus requires exactly one SA host connection.",
                    bus,
                    hosts,
                )
            if (
                len(bus.segments) != 1
                or any(d.role == "repeater-port" for d in devices)
                or any(link.kind == "repeater-bridge" for link in links)
            ):
                add(
                    "sa-single-segment-no-repeaters",
                    "error",
                    "SA is one private segment and does not support repeaters or routed FC segmentation.",
                    bus,
                    devices,
                )
            for host in hosts:
                if host.eol == "off":
                    add(
                        "sa-host-eol-fixed-on",
                        "error",
                        "SA host termination is integral/fixed ON; a declared OFF setting contradicts the reviewed host profile.",
                        bus,
                        [host],
                    )
                elif host.eol == "unknown":
                    add(
                        "sa-host-eol-unknown",
                        "unknown",
                        "Confirm the planned SA host fixed termination evidence.",
                        bus,
                        [host],
                    )
        elif bus.kind == "fc" and len(bus.segments) > 3:
            if bus.profile == "metasys-r15":
                add(
                    "fc-segment-count",
                    "error",
                    "The reviewed Metasys R15 FC rules limit the bus to three repeater-connected segments.",
                    bus,
                )
            elif bus.profile == "fx-2024":
                add(
                    "fx-segment-limit-unresolved",
                    "unknown",
                    "FX 2024 page 8 describes up to three segments, while page 14 also lists FX80 with 32 segments and two cascaded repeaters/three segments. Exact host/repeater limits need clarification; no universal FX limit or approval is inferred.",
                    bus,
                )

        adjacency = {d.id: set() for d in devices}
        trunks = defaultdict(list)
        service_links = []
        for link in links:
            a, b = by_id[link.a], by_id[link.b]
            adjacency[a.id].add(b.id)
            adjacency[b.id].add(a.id)
            if link.length_m is None and link.kind != "repeater-bridge":
                add(
                    "cable-length-unknown",
                    "unknown",
                    "Planned cable length is unknown; no cable-length compliance is established.",
                    bus,
                    [a, b],
                    [link],
                )
            reviewed_service = bus.kind == "sa" and any(
                MODELS.get(sensor.model, {}).get("service_port")
                and sensor.generation == MODELS.get(sensor.model, {}).get("generation")
                and sensor.role == "network-sensor"
                and tool.role == "converter"
                and tool.model == "TL-CWCVT-0"
                for sensor, tool in ((a, b), (b, a))
            )
            if link.kind == "modular" or (link.kind == "sensor-service" and reviewed_service):
                if link.straight_through is False:
                    add(
                        "modular-crossover-invalid",
                        "error",
                        "The reviewed 6-pin SA cable must be straight-through, not crossover.",
                        bus,
                        [a, b],
                        [link],
                    )
                elif link.straight_through is None:
                    add(
                        "modular-pinout-unverified",
                        "unknown",
                        "Straight-through6-pin cable pinout is not declared.",
                        bus,
                        [a, b],
                        [link],
                    )
                if link.length_m is not None and link.length_m > 30:
                    add(
                        "modular-cable-length",
                        "error",
                        "The reviewed 6-pin SA modular connection is limited to 30 m.",
                        bus,
                        [a, b],
                        [link],
                    )
            if link.kind == "sensor-service":
                service_links.append(link)
                continue
            if link.kind == "repeater-bridge":
                if (
                    bus.kind != "fc"
                    or a.role != "repeater-port"
                    or b.role != "repeater-port"
                    or a.segment == b.segment
                ):
                    add(
                        "repeater-bridge-declaration",
                        "error",
                        "A declared FC repeater bridge needs distinct segments and explicit repeater-side connection nodes.",
                        bus,
                        [a, b],
                        [link],
                    )
                add(
                    "repeater-hardware-unverified",
                    "unknown",
                    "Exact repeater model, side identity and permitted cascade/capacity are not verified by this graph.",
                    bus,
                    [a, b],
                    [link],
                )
                continue
            if link.kind == "unknown":
                add(
                    "link-kind-unknown",
                    "unknown",
                    "Connection kind is unknown; no trunk/exception interpretation is approved.",
                    bus,
                    [a, b],
                    [link],
                )
                continue
            if a.segment is not None and b.segment is not None and a.segment != b.segment:
                add(
                    "cross-segment-cable",
                    "error",
                    "Ordinary cable must remain in one segment; FC segments require an explicitly declared repeater bridge.",
                    bus,
                    [a, b],
                    [link],
                )
            else:
                trunks[a.segment].append(link)
        for link in service_links:
            a, b = by_id[link.a], by_id[link.b]
            pairs = [(a, b), (b, a)]
            pair = next(
                (
                    (s, t)
                    for s, t in pairs
                    if MODELS.get(s.model, {}).get("service_port")
                    and s.generation == MODELS.get(s.model, {}).get("generation")
                    and t.model == "TL-CWCVT-0"
                    and s.role == "network-sensor"
                    and t.role == "converter"
                ),
                None,
            )
            if pair is None or bus.kind != "sa":
                add(
                    "service-exception-unverified",
                    "unknown",
                    "Claimed sensor-service cable lacks the exact reviewed refreshed-sensor/CWCVT leaf profile; it is not silently counted as a normal trunk or approved stub.",
                    bus,
                    [a, b],
                    [link],
                )
            else:
                sensor, tool = pair
                if (
                    len(adjacency[tool.id]) != 1
                    or sum(sensor.id in (x.a, x.b) for x in service_links) > 1
                ):
                    add(
                        "service-port-daisy-chain",
                        "error",
                        "A reviewed sensor service port supports one accessory leaf, not a downstream trunk or multiple accessories.",
                        bus,
                        [sensor, tool],
                        [link],
                    )
                else:
                    add(
                        "documented-sensor-service-leaf",
                        "info",
                        "Exact reviewed NS8000 refreshed access-port/CWCVT leaf is treated separately from ordinary trunk branching. This does not establish power budget, commissioning behavior or arbitrary RJ45/RJ12 compatibility.",
                        bus,
                        [sensor, tool],
                        [link],
                    )
        main_kinds = {link.kind for link in links if link.kind in ("terminal", "modular")}
        if bus.kind == "sa" and main_kinds == {"terminal", "modular"}:
            add(
                "sa-mixed-trunk-connectors",
                "error",
                "Do not mix ordinary SA modular-jack and screw-terminal trunk connections. An explicitly reviewed sensor service accessory is a separate exception.",
                bus,
            )
        if (
            bus.kind == "sa"
            and "modular" in main_kinds
            and sum(link.kind == "modular" for link in links) > 1
        ):
            add(
                "sa-modular-daisy-chain",
                "error",
                "The controller 6-pin SA modular port supports one attached device; ordinary modular daisy-chaining is not supported.",
                bus,
            )
        if bus.kind == "fc" and "modular" in main_kinds:
            add(
                "fc-modular-profile-unverified",
                "unknown",
                "This profile does not verify FC modular connector pinouts or topology exceptions.",
                bus,
            )
        for segment_links in trunks.values():
            degree = defaultdict(int)
            for link in segment_links:
                degree[link.a] += 1
                degree[link.b] += 1
            branches = [by_id[id] for id, n in degree.items() if n > 2]
            if branches:
                add(
                    "trunk-branch",
                    "error",
                    "Declared ordinary trunk cables form a branch rather than a daisy chain; service/repeater exceptions are reviewed separately.",
                    bus,
                    branches,
                    segment_links,
                )
            if bus.kind == "fc":
                for id, n in degree.items():
                    d = by_id[id]
                    if d.eol == "unknown":
                        add(
                            "fc-eol-unknown",
                            "unknown",
                            "FC segment endpoint/interior EOL setting is unknown.",
                            bus,
                            [d],
                        )
                    elif (n == 1 and d.eol == "off") or (n > 1 and d.eol in ("on", "fixed-on")):
                        add(
                            "fc-eol-position-conflict",
                            "error",
                            "FC EOL must be enabled at the two segment ends and disabled at ordinary interior nodes.",
                            bus,
                            [d],
                        )
            elif bus.kind == "sa":
                for id, n in degree.items():
                    d = by_id[id]
                    if d.role == "sa-host":
                        continue
                    if d.eol == "unknown":
                        add(
                            "sa-far-end-eol-unreviewed",
                            "unknown",
                            "SA far-end/other termination evidence is undeclared; fixed host EOL is the minimum, both ends are preferred.",
                            bus,
                            [d],
                        )
                    elif n == 1 and d.eol == "off":
                        add(
                            "sa-host-only-termination",
                            "info",
                            "Host-only SA termination is documented as acceptable; end termination is preferred. Actual loads, wire and noise still require review.",
                            bus,
                            [d],
                        )
                    elif n > 1 and d.eol in ("on", "fixed-on"):
                        add(
                            "sa-interior-eol-review",
                            "unknown",
                            "Interior SA termination needs exact device/wiring review; no generic electrical approval is made.",
                            bus,
                            [d],
                        )
        seen = set()
        components = 0
        edges = len(links)
        for id in adjacency:
            if id in seen:
                continue
            components += 1
            stack = [id]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                stack.extend(adjacency[current] - seen)
        if components > 1:
            add(
                "disconnected-plan",
                "error",
                "Declared devices/cables form disconnected components on this physical bus.",
                bus,
                devices,
            )
        if edges > len(devices) - components:
            add(
                "cyclic-plan",
                "error",
                "Declared physical connections contain a cycle; an MS/TP trunk is not a ring.",
                bus,
                devices,
                links,
            )
        add(
            "capacity-cable-power-unverified",
            "unknown",
            "Device counts are recorded but exact host/third-party/loading/COV limits, cable construction, shielding, voltage drop and power budget are not certified by this address/topology profile.",
            bus,
            category="engineering",
        )
        summaries.append(
            {
                "bus_id": bus.id,
                "devices": len(devices),
                "links": len(links),
                "segments": len(bus.segments),
                "components": components,
                "source": copy.deepcopy(SOURCES.get(bus.profile)),
                "addressed_connections": len(
                    [d for d in devices if d.mac is not None and d.role != "repeater-port"]
                ),
            }
        )
    findings.sort(
        key=lambda f: ({"error": 0, "unknown": 1, "info": 2}[f["severity"]], f["code"], f["id"])
    )
    counts = {s: sum(f["severity"] == s for f in findings) for s in ("error", "unknown", "info")}
    checks = {}
    for category in ("address", "topology", "engineering"):
        severities = {f["severity"] for f in findings if f["category"] == category}
        checks[category] = (
            "conflicts"
            if "error" in severities
            else "incomplete"
            if "unknown" in severities
            else "no-conflicts-in-declarations"
        )
    result = {
        "checks": checks,
        "format": "bms.jci-bus-review",
        "version": 1,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "plan": plan.model_dump(),
        "plan_sha256": digest(plan.model_dump()),
        "catalog": copy.deepcopy(CATALOG),
        "scope": SCOPE,
        "status": "conflicts"
        if counts["error"]
        else "incomplete"
        if counts["unknown"]
        else "no-conflicts-in-declarations",
        "counts": counts,
        "findings": findings,
        "buses": summaries,
        "field_operations": False,
        "physical_wiring_verified": False,
        "operator_declarations_authenticated": False,
    }
    result["content_sha256"] = digest(result)
    return result


class PlanBody(StrictModel):
    plan: dict


def bus_preflight_router():
    router = APIRouter(prefix="/api/bus-preflight")

    @router.get("/catalog")
    def catalog():
        return {"catalog": copy.deepcopy(CATALOG), "template": template(), "scope": SCOPE}

    @router.post("/validate")
    def validate(body: PlanBody):
        value = validate_plan(body.plan).model_dump()
        return {"plan": value, "plan_sha256": digest(value)}

    @router.post("/review")
    def calculate(body: PlanBody):
        return review(body.plan)

    @router.post("/export-plan")
    def export_plan(body: PlanBody):
        value = validate_plan(body.plan).model_dump()
        return Response(
            canonical(value) + b"\n",
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="jci-bus-plan.json"'},
        )

    @router.post("/export-review")
    def export_review(body: PlanBody):
        value = review(body.plan)
        return Response(
            canonical(value) + b"\n",
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="jci-bus-review.json"'},
        )

    return router
