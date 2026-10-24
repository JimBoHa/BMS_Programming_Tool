"""Offline JCI target/toolchain preflight with explicit, attributable evidence.

An uploaded inventory is a declaration, not proof that a manufacturer tool was
executed. Release/application versions and firmware remain separate namespaces.
No compatibility table is extrapolated from model names or version ordering.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator

from .caf import BY_CLASS, CafArchive, Q
from .jci_release_rules import ReleaseReview
from .jci_release_rules import review as review_release
from .models import StrictModel

Text = Annotated[str, Field(max_length=256)]
Names = Annotated[list[Text], Field(max_length=100)]
License = Literal["licensed", "missing", "unknown"]


class ToolInventory(StrictModel):
    product: Literal["CCT", "PCT", "unknown"] = "unknown"
    version: Text = ""
    installed: StrictBool | None = None
    license_status: License = "unknown"
    platform: Literal["windows", "macos", "linux", "unknown"] = "unknown"
    sql_available: StrictBool | None = None
    supported_models: Names = Field(default_factory=list)
    supported_application_versions: Names = Field(default_factory=list)
    supported_firmware_versions: Names = Field(default_factory=list)
    evidence: Annotated[str, Field(max_length=2000)] = ""


class PackageInventory(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=256)]
    version: Text = ""
    installed: StrictBool | None = None
    license_status: License = "unknown"
    required: StrictBool = True
    supported_models: Names = Field(default_factory=list)
    supported_application_versions: Names = Field(default_factory=list)
    supported_firmware_versions: Names = Field(default_factory=list)
    evidence: Annotated[str, Field(max_length=2000)] = ""
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("name")
    @classmethod
    def named_package(cls, value):
        if not value.strip():
            raise ValueError("Package name must contain visible text.")
        return value


class InventoryManifest(StrictModel):
    schema_version: Literal[1] = 1
    toolchain: ToolInventory = Field(default_factory=ToolInventory)
    packages: list[PackageInventory] = Field(default_factory=list, max_length=100)
    package_inventory_complete: StrictBool | None = None
    hardware_definition_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("packages")
    @classmethod
    def unique_packages(cls, value):
        keys = [(row.name.strip().casefold(), row.version.strip()) for row in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate package name/version entries are ambiguous.")
        return value


class PreflightRequest(StrictModel):
    release_review: ReleaseReview | None = None
    target_model: Text = ""
    target_firmware: Text = ""
    application_object_ref: Text = ""
    transport: Literal["unspecified", "bacnet-ip", "btcvt", "direct-serial"] = "unspecified"
    inventory_text: str = Field(default="{}", max_length=256 * 1024)
    hardware_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


def inventory_template():
    """Unknown values intentionally remain unknown; this is not host detection."""
    value = InventoryManifest().model_dump()
    value["packages"] = [PackageInventory(name="Required controller package").model_dump()]
    return value


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate inventory JSON key: " + key)
        result[key] = value
    return result


def _parse_inventory(text):
    if len(text.encode("utf-8")) > 256 * 1024:
        raise ValueError("Inventory UTF-8 text exceeds the 256 KiB limit.")
    try:
        value = json.loads(
            text.removeprefix("\ufeff"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("Non-finite inventory JSON value: " + value)
            ),
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Inventory must be a valid bounded UTF-8 JSON object.") from exc
    if not isinstance(value, dict):
        raise ValueError("Inventory must be a JSON object.")
    return InventoryManifest.model_validate(value)


def _candidates(caf):
    rows = []
    for ref, obj in caf.objects.items():
        names = BY_CLASS.get(obj.get("classid"), {})
        # SA expansion/sensor model properties do not identify the application target.
        if names.get("12") != "Appl SW Version" or names.get("70") != "Model Name":
            continue
        properties = {
            prop.get("id"): caf.scalar(prop) for prop in obj if prop.tag == Q + "property"
        }
        if "70" not in properties and "12" not in properties:
            continue
        if len(ref) > 256:
            raise ValueError("CAF application-target references must be at most 256 characters.")
        values, evidence = {}, []
        for key, label in (("70", "model"), ("12", "application_version"), ("44", "firmware")):
            scalar = properties.get(key)
            # Do not turn a structured/enum property into an invented string identity.
            value = (
                scalar["text"].strip()
                if scalar
                and scalar["type"] == "string"
                and not scalar["attributes"]
                and len(scalar["text"]) <= 256
                else ""
            )
            values[label] = value
            if key in properties:
                evidence.append(
                    {
                        "object_ref": ref,
                        "class_id": obj.get("classid"),
                        "property_id": key,
                        "property_name": names.get(key),
                        "scalar": scalar
                        if scalar is None or len(json.dumps(scalar)) <= 4096
                        else {
                            "type": scalar["type"],
                            "oversize": True,
                            "text_sha256": hashlib.sha256(
                                scalar["text"].encode("utf-8")
                            ).hexdigest(),
                            "text_characters": len(scalar["text"]),
                        },
                    }
                )
        rows.append({"object_ref": ref, **values, "evidence": evidence})
        if len(rows) > 256:
            raise ValueError("CAF preflight exceeds the 256 application-target candidate limit.")
    return rows


def _version(value):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", value.strip()):
        return None
    return tuple(int(part) for part in value.strip().split("."))


def _same(left, right):
    return left.strip().casefold() == right.strip().casefold()


def preflight(caf: CafArchive, request: PreflightRequest, hardware=None):
    manifest = _parse_inventory(request.inventory_text)
    checks = []

    def add(identifier, category, label, status, detail, evidence=None):
        checks.append(
            {
                "id": identifier,
                "category": category,
                "label": label,
                "status": status,
                "detail": detail,
                "evidence": evidence or [],
            }
        )

    def compare(identifier, category, label, observed, expected, evidence=None):
        if not observed or not expected:
            add(
                identifier,
                category,
                label,
                "unknown",
                "Both values are required for comparison.",
                evidence,
            )
        else:
            match = _same(observed, expected)
            add(
                identifier,
                category,
                label,
                "match" if match else "blocked",
                f"CAF: {observed}; declared target: {expected}. "
                + (
                    "Exact identifiers agree."
                    if match
                    else "Identifiers differ; no substitution is assumed."
                ),
                evidence,
            )

    def present(identifier, category, label, value):
        add(
            identifier,
            category,
            label,
            "unknown" if value is None else "match" if value else "blocked",
            "Not supplied."
            if value is None
            else "Declared available; not independently probed."
            if value
            else "Declared unavailable.",
        )

    def licensed(identifier, category, label, value):
        add(
            identifier,
            category,
            label,
            {"licensed": "match", "missing": "blocked", "unknown": "unknown"}[value],
            "Declared license status: "
            + value
            + ". License activation is not checked by this report.",
        )

    def supported(identifier, category, label, observed, supported_values, evidence):
        if not observed or not supported_values or not evidence.strip():
            add(
                identifier,
                category,
                label,
                "unknown",
                "An observed identifier, explicit support list, and evidence description are required.",
            )
        else:
            match = any(_same(observed, value) for value in supported_values)
            add(
                identifier,
                category,
                label,
                "match" if match else "blocked",
                f"{observed} "
                + ("is" if match else "is not")
                + " in the supplied support list. No version range or model-family expansion is inferred.",
                [{"declaration": evidence, "supported_values": supported_values}],
            )

    candidates = _candidates(caf)
    if request.application_object_ref:
        selected = next(
            (row for row in candidates if row["object_ref"] == request.application_object_ref), None
        )
        if selected is None:
            raise ValueError(
                "Selected application object is not an inspected CAF target candidate."
            )
    else:
        selected = candidates[0] if len(candidates) == 1 else None
    add(
        "caf.target",
        "CAF identity",
        "Application target identification",
        "match" if selected else "unknown",
        "Selected CAF object: " + selected["object_ref"]
        if selected
        else "No unique application target. Select an object when multiple candidates are present.",
    )
    observed = selected or {"model": "", "firmware": "", "application_version": "", "evidence": []}
    compare(
        "target.model",
        "CAF identity",
        "Controller model",
        observed["model"],
        request.target_model,
        observed["evidence"],
    )
    compare(
        "target.firmware",
        "CAF identity",
        "Controller firmware",
        observed["firmware"],
        request.target_firmware,
        observed["evidence"],
    )
    add(
        "caf.application-version",
        "CAF identity",
        "CAF Appl SW Version",
        "match" if observed["application_version"] else "unknown",
        (
            "CAF property 12: "
            + observed["application_version"]
            + ". This is not a firmware version."
        )
        if observed["application_version"]
        else "No string application-version property was identified.",
        observed["evidence"],
    )

    tool = manifest.toolchain
    add(
        "tool.identity",
        "Toolchain",
        "CCT/PCT product and version",
        "match" if tool.product != "unknown" and tool.version.strip() else "unknown",
        f"Declared product: {tool.product}; version: {tool.version or 'unknown'}. Tool version is separate from CAF release mode.",
    )
    present("tool.installed", "Toolchain", "Manufacturer tool installed", tool.installed)
    licensed("tool.license", "Toolchain", "Manufacturer tool license", tool.license_status)
    add(
        "tool.platform",
        "Toolchain",
        "Windows tool environment",
        "unknown"
        if tool.platform == "unknown"
        else "match"
        if tool.platform == "windows"
        else "blocked",
        "Declared platform: "
        + tool.platform
        + ". Exact Windows, architecture, and SQL version support still requires the selected tool's installation guide.",
    )
    present("tool.sql", "Toolchain", "Required SQL environment available", tool.sql_available)
    for key, label, value, supported_values in (
        ("model", "Declared tool model support", request.target_model, tool.supported_models),
        (
            "application",
            "Declared CAF Appl SW Version support",
            observed["application_version"],
            tool.supported_application_versions,
        ),
        (
            "firmware",
            "Declared tool firmware support",
            request.target_firmware,
            tool.supported_firmware_versions,
        ),
    ):
        supported("tool." + key, "Toolchain", label, value, supported_values, tool.evidence)

    present(
        "packages.complete",
        "Controller packages",
        "Controller package inventory complete",
        manifest.package_inventory_complete,
    )
    required = [package for package in manifest.packages if package.required]
    if not required:
        add(
            "packages.required",
            "Controller packages",
            "Required controller packages",
            "unknown",
            "No required package was identified. An empty list does not establish that no packages are needed.",
        )
    for index, package in enumerate(manifest.packages):
        prefix = f"package.{index}"
        label = f"{package.name} {package.version}".strip()
        if not package.required:
            add(
                prefix + ".optional",
                "Controller packages",
                label,
                "information",
                "Declared optional; not used to establish required package readiness.",
            )
            continue
        present(
            prefix + ".installed", "Controller packages", label + ": installed", package.installed
        )
        licensed(
            prefix + ".license", "Controller packages", label + ": license", package.license_status
        )
        add(
            prefix + ".version",
            "Controller packages",
            label + ": version evidence",
            "match" if package.version.strip() and package.evidence.strip() else "unknown",
            "Declared version: "
            + (package.version or "unknown")
            + ". A declared file hash is not independently verified.",
            [{"declaration": package.evidence, "declared_sha256": package.sha256}],
        )
        for key, value, supported_values in (
            ("model", request.target_model, package.supported_models),
            ("firmware", request.target_firmware, package.supported_firmware_versions),
            (
                "application",
                observed["application_version"],
                package.supported_application_versions,
            ),
        ):
            supported(
                prefix + "." + key,
                "Controller packages",
                label + ": " + key + " support",
                value,
                supported_values,
                package.evidence,
            )

    if hardware is None:
        add(
            "hardware.definition",
            "Hardware metadata",
            "Native hardware definition",
            "unknown",
            "No original DynamicHardwareDefinition XML supplied. This metadata alone would not prove a controller model supports the program.",
        )
        hardware_evidence = None
    else:
        hardware_evidence = {
            "sha256": hardware.hash,
            "name": hardware.name,
            "revision": hardware.revision,
            "vendor": hardware.vendor,
            "point_count": len(hardware.points),
        }
        expected = manifest.hardware_definition_sha256
        add(
            "hardware.definition",
            "Hardware metadata",
            "Native hardware definition hash",
            "unknown"
            if not expected
            else "match"
            if expected.lower() == hardware.hash
            else "blocked",
            "Definition parsed and hashed. "
            + (
                "No expected hash was declared."
                if not expected
                else "Compared against the manifest's expected hash; this is provenance, not hardware compatibility."
            ),
            [hardware_evidence],
        )
        add(
            "hardware.vendor",
            "Hardware metadata",
            "Hardware definition vendor",
            "match" if hardware.vendor["number"] == 5 else "blocked",
            "Observed BACnet vendor identifier: "
            + str(hardware.vendor["number"])
            + "; JCI identifier: 5.",
        )

    if request.transport == "btcvt":
        source = {
            "title": "Metasys System Configuration Guide 14.1, transfer-to-device limitations",
            "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Metasys-System-Configuration-Guide/14.1/Metasys-system/Performance-guidelines-and-limitations/Transfer-to-device-download-limitations",
            "scope": "Documented release-specific restriction; no host driver or pairing test performed.",
        }
        version, firmware = _version(tool.version), _version(request.target_firmware)
        firmware_family = (
            (firmware[0], firmware[1] if len(firmware) > 1 else 0) if firmware else None
        )
        conflict = tool.product == "CCT" and version is not None and version >= (14,)
        add(
            "btcvt.tool",
            "Transport",
            "BTCVT tool restriction",
            "blocked"
            if conflict
            else "unknown"
            if tool.product != "CCT" or version is None
            else "match",
            "CCT 14.0 and later does not support BTCVT, per the cited 14.1 guide. An earlier CCT only clears that ceiling; PCT compatibility is not established by this CCT restriction. Exact tools and hardware still require testing.",
            [source],
        )
        add(
            "btcvt.firmware",
            "Transport",
            "BTCVT firmware restriction",
            "unknown"
            if firmware_family is None
            else "blocked"
            if firmware_family >= (7, 0)
            else "match"
            if firmware_family <= (6, 2)
            else "unknown",
            "The cited guide supports Bluetooth application transfers at firmware 6.2 and earlier and excludes 7.0 and later. CAF release mode is not used for this check.",
            [source],
        )
    add(
        "transport.validation",
        "Transport",
        "Native transfer over the planned connection",
        "unknown",
        "Planned connection: "
        + request.transport
        + ". BACnet discovery/property access, an open serial port, or Bluetooth pairing alone does not verify native application transfer.",
    )
    add(
        "native.integration",
        "Acceptance evidence",
        "Validated native compiler/transfer integration",
        "unknown",
        "This preflight does not execute CCT/PCT, compile native logic, establish a loader session, or validate a native bridge.",
    )
    add(
        "native.acceptance",
        "Acceptance evidence",
        "Vendor and controller acceptance",
        "unknown",
        "Vendor reopen/validation, application-only bench transfer, readback, restart persistence, and restore evidence remain required.",
    )
    release_report = None
    if request.release_review is not None:
        release_report = review_release(
            request.release_review,
            tool,
            manifest.packages,
            caf_sha256=caf.hash,
            application_version=observed["application_version"],
        )
        for finding in release_report["findings"]:
            add(
                "release." + finding["rule_id"],
                "Documented release rules",
                finding["rule_id"],
                {"condition-met": "match", "conflict": "blocked", "unknown": "unknown"}[
                    finding["status"]
                ],
                finding["detail"],
                finding["sources"],
            )
    counts = dict(Counter(row["status"] for row in checks))
    return {
        "schema_version": 1,
        "status": "blocked"
        if counts.get("blocked")
        else "needs-evidence"
        if counts.get("unknown")
        else "declared-comparisons-match",
        "can_deploy": False,
        "scope": "Offline inspection and comparison of submitted evidence. Inventory declarations are not independently verified installation or compatibility results.",
        "source": {
            "caf_sha256": caf.hash,
            "caf_xml_sha256": hashlib.sha256(caf.xml).hexdigest(),
            "inventory_utf8_sha256": hashlib.sha256(
                request.inventory_text.encode("utf-8")
            ).hexdigest(),
            "inventory_text": request.inventory_text,
            "inventory": manifest.model_dump(),
            "hardware": hardware_evidence,
        },
        "target": {
            "model": request.target_model,
            "firmware": request.target_firmware,
            "transport": request.transport,
        },
        "application_candidates": candidates,
        "selected_application": selected,
        "release_review": release_report,
        "checks": checks,
        "counts": counts,
    }
