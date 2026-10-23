"""Exact-part, operator-declared target transport admission; no field operations."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Literal

from bacpypes3.pdu import Address
from pydantic import Field

from .hardware_target import HardwareTargetRequest, serial_identity
from .models import StrictModel

SOURCE = {
    "title": "Metasys System Field Equipment Controllers and Related Products Product Bulletin",
    "document": "LIT-12011042",
    "edition": "13.0",
    "sha256": "3a65a6ffe84c8e453d814af07470638fd7a1b12965df52e859580a276d2386a3",
    "pdf_pages": [2, 3, 4, 16, 22, 23, 24],
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Field-Equipment-Controllers-and-Related-Products-Product-Bulletin/13.0",
    "qualification": "Exact listed part numbers and this edition only. An SA sensor port is not an FC bus. Capability does not identify the currently selected protocol or prove physical hardware.",
}
MODELS = {
    "MS-FAC4911-0": {
        "native_protocols": ["bacnet-ip", "bacnet-sc"],
        "ports": ["Ethernet", "SA"],
        "note": "Engine support requires firmware9.0 or later plus referenced engine limitations; no native deployment guarantee.",
    },
    **{
        name: {
            "native_protocols": ["bacnet-mstp", "n2"],
            "ports": ["FC", "SA"],
            "note": "Selected protocol is an operator declaration. CCT protocol switching is outside this profile.",
        }
        for name in ("MS-FAC2611-0", "MS-FAC3613-0")
    },
}
PROFILE = {
    "profile": "studio-jci-model-target-transport/1",
    "source": SOURCE,
    "models": MODELS,
    "adapters": {"bacnet-ip": True, "bacnet-mstp": True, "bacnet-sc": False, "n2": False},
    "semantics": {
        "identity": "Exact operator-declared complete part number; no prefix, case or shortened native Model_Name promotion. Raw observed text is separate and not authentication.",
        "interface": "A shared IPv4 interface may reach IP controllers and routed MS/TP controllers. The router endpoint is not the controller's native transport.",
        "routed": "Only explicitly declared MS/TP with a one-octet remote MAC is qualified here. Other existing generic1..8octet routed targets remain untouched and unresolved by this optional profile.",
        "admission": "Optional HardwareWorkbench survey admission only, recomputed against current target/configuration; no connection, scan, protocol toggle, power lease or write.",
        "observations": "Post-read raw Device/model/vendor/firmware values, exact text match or unresolved/mismatch. No guessed model aliases or physical/native deployment proof.",
        "addresses": "Existing target and interface address validation unchanged. Manufacturer-specific MAC/N2 address ranges are not additionally enforced by this transport-only profile.",
    },
    "gaps": [
        "BACnet/SC and N2 clients, native JCI allocation/compiler/CAF/transfer, firmware switching and physical commissioning",
        "other exact models, verified native Model_Name aliases, routed IP/proxy arrangements and manufacturer address-range reconciliation",
        "SA/accessory electrical compatibility, BTCVT, physical bus topology and capacity certification",
    ],
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


PROFILE_SHA = hashlib.sha256(canonical(PROFILE)).hexdigest()


class ModelQualification(StrictModel):
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=80, strict=True)
    current_protocol: Literal["bacnet-ip", "bacnet-mstp", "bacnet-sc", "n2", "unknown"]


class ModelReviewRequest(StrictModel):
    qualification: ModelQualification
    target: HardwareTargetRequest


def catalog():
    return {
        "format": "bms.jci-model-target-transport-catalog/1",
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "qualification_schema": ModelQualification.model_json_schema(),
        "target_schema": HardwareTargetRequest.model_json_schema(),
        "controller_writes": False,
    }


def review(qualification, target, config, *, connected):
    """Pure decision over declarations and a current local interface snapshot."""
    q = ModelQualification.model_validate(qualification)
    t = HardwareTargetRequest.model_validate(target)
    declaration, destination = q.model_dump(), t.model_dump()
    model = MODELS.get(q.model)
    path = (
        "direct-mstp"
        if t.transport == "direct-mstp"
        else "routed-explicit"
        if t.router
        else "direct-ipv4"
    )
    findings = []

    def finding(code, message):
        findings.append({"code": code, "message": message})

    if q.profile_sha256 != PROFILE_SHA:
        finding(
            "unsupported_profile", "Refresh the supported source-qualified profile before reading."
        )
    if model is None:
        finding(
            "unresolved_model", "This exact complete part number is not in the reviewed model set."
        )
    if q.current_protocol == "unknown":
        finding(
            "unresolved_current_protocol",
            "Declare the currently selected native protocol; model capability does not select it.",
        )
    elif model is not None and q.current_protocol not in model["native_protocols"]:
        finding(
            "protocol_not_documented_for_model",
            "The declared protocol conflicts with this exact part's documented capability.",
        )
    if q.current_protocol in ("bacnet-sc", "n2"):
        finding(
            "adapter_unavailable",
            "This software has no implemented adapter for the declared SC or N2 mode.",
        )
    if q.current_protocol == "bacnet-ip" and path != "direct-ipv4":
        finding(
            "path_not_qualified",
            "This first native-IP model profile qualifies direct IPv4 only; routed IP/proxy arrangements are unresolved.",
        )
    elif q.current_protocol == "bacnet-mstp":
        if path == "direct-ipv4":
            finding(
                "native_mstp_requires_explicit_path",
                "Select direct MS/TP or a separately pinned IPv4 router/DNET:MAC; the router is not an IP controller.",
            )
        elif path == "routed-explicit" and Address(t.address).addrLen != 1:
            finding(
                "routed_link_unresolved",
                "A multi-octet generic remote address is not promoted to an MS/TP MAC by this profile.",
            )
    if (
        model is not None
        and path == "direct-mstp"
        and "bacnet-mstp" not in model["native_protocols"]
    ):
        finding(
            "direct_mstp_not_documented",
            "This exact controller has no documented FC MS/TP transport.",
        )
    if not connected or not isinstance(config, dict):
        finding(
            "interface_not_open",
            "Open the selected existing interface explicitly before starting a qualified read.",
        )
    elif (config.get("transport") == "mstp") != (path == "direct-mstp"):
        finding(
            "interface_path_mismatch",
            "The open interface does not match the selected direct or IPv4 target path.",
        )
    elif path == "direct-mstp":
        try:
            serial_identity(config, t)
        except ValueError as error:
            finding("serial_identity_not_admitted", str(error)[:400])
    return {
        "format": "bms.jci-model-target-transport-review/1",
        "profile": PROFILE["profile"],
        "profile_sha256": PROFILE_SHA,
        "source": copy.deepcopy(SOURCE),
        "declaration": declaration,
        "documented_model": copy.deepcopy(model),
        "documented_protocols": copy.deepcopy(model["native_protocols"]) if model else [],
        "adapter_implemented": PROFILE["adapters"].get(q.current_protocol, False),
        "target": destination,
        "path": path,
        "interface": {"connected": bool(connected), "config": copy.deepcopy(config)},
        "dispatch_admitted": not findings,
        "findings": findings,
        "native_compatibility_verified": False,
        "controller_writes": False,
    }


def observe(admission, report):
    """Annotate the owned job only; never change a native survey report/schema."""
    identity = copy.deepcopy(report.get("identity", {}))
    raw = identity.get("model")
    return {
        "origin": "owned-survey-raw-identity",
        "declared_model": admission["declaration"]["model"],
        "raw_identity": identity,
        "model_text_status": "unresolved"
        if not isinstance(raw, str) or not raw
        else "exact_text_match"
        if raw == admission["declaration"]["model"]
        else "different_text_unresolved",
        "target_matches_admission": report.get("target") == admission["target"],
        "config_matches_admission": report.get("connector_config")
        == admission["interface"]["config"],
        "native_compatibility_verified": False,
        "meaning": "Raw native text only; a shortened or different Model_Name is not promoted to an exact part identity. Self-reported text is not manufacturer authentication or physical installation proof.",
    }
