"""Authored declarations exercise actual reviewed predicates, never installed tools."""

import copy
import hashlib
import json

import pytest
from bms_tool.jci_preflight import InventoryManifest, PreflightRequest, preflight
from bms_tool.jci_release_rules import RULESET_SHA, ReleaseReview, catalog, review

from tests.test_jci_preflight import application, inventory


def evaluate(operation="open", *, destination="18.0", product="CCT", packages=None, **facts):
    declared = inventory()
    declared["toolchain"].update(product=product, version=destination)
    if packages is not None:
        declared["packages"] = packages
    parsed = InventoryManifest.model_validate(declared)
    body = ReleaseReview(
        operation=operation, source_tool_product="CCT", source_tool_release="10.2", **facts
    )
    return review(
        body,
        parsed.toolchain,
        parsed.packages,
        caf_sha256="a" * 64,
        application_version="6.2.0.999",
    )


def findings(result):
    return {r["rule_id"]: r for r in result["findings"]}


def verify_seal(document):
    value = copy.deepcopy(document)
    seal = value.pop("content_sha256")
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    assert hashlib.sha256(raw).hexdigest() == seal


@pytest.mark.parametrize(
    "destination,origin,status",
    [
        ("10.1", "10.0", "condition-met"),
        ("13.0", "8.0", "condition-met"),
        ("18.0", "10.2", "condition-met"),
        ("10.0", "9.0", "unknown"),
        ("18.1", "10.2", "unknown"),
        ("19.0", "10.2", "unknown"),
        ("18.0.0.543", "10.2", "unknown"),
        ("18.0", "10.2.0.3000", "unknown"),
        ("18.0", "18.0", "unknown"),
        ("13.0", "18.0", "unknown"),
    ],
)
def test_earlier_cct_open_commission_has_bounded_operation_scope(destination, origin, status):
    for operation in ("open", "commission"):
        manifest = InventoryManifest.model_validate(inventory())
        manifest.toolchain.version = destination
        result = review(
            ReleaseReview(
                operation=operation, source_tool_product="CCT", source_tool_release=origin
            ),
            manifest.toolchain,
            manifest.packages,
            caf_sha256="b" * 64,
            application_version="999.0",
        )
        row = findings(result)["cct.earlier-open-commission"]
        assert row["status"] == status
        assert {tuple(s["pdf_pages"]) for s in row["sources"]} == {(54,), (53,)}
        assert (
            not result["can_deploy"]
            and not result["can_execute_native"]
            and not result["manufacturer_tool_executed"]
        )
        verify_seal(result)


@pytest.mark.parametrize(
    "operation,mode,active,status",
    [
        ("edit-logic", "10.2", "10.2", "condition-met"),
        ("simulate", "10.2", "10.2", "condition-met"),
        ("edit-defaults", "10.2", "10.4", "condition-met"),
        ("edit-logic", "10.2", "10.4", "conflict"),
        ("simulate", "10.2", "10.4", "conflict"),
        ("edit-defaults", "10.5", "10.4", "conflict"),
        ("edit-logic", "", "10.4", "unknown"),
        ("simulate", "10.2/FW6.2", "10.2", "unknown"),
    ],
)
def test_cct18_modes_differentiate_defaults_logic_and_simulation(operation, mode, active, status):
    result = evaluate(operation, caf_release_mode=mode, active_release_mode=active)
    assert findings(result)["cct18.mode-operation"]["status"] == status
    assert not result["can_execute_native"]
    if operation == "edit-defaults" and mode != active and status == "condition-met":
        assert "default-value edits" in findings(result)["cct18.mode-operation"]["detail"]
    older = evaluate(
        operation, destination="13.0", caf_release_mode=mode, active_release_mode=active
    )
    assert findings(older)["cct18.mode-operation"]["status"] == "unknown"


@pytest.mark.parametrize(
    "mode,active,family,other,status",
    [
        ("10.2", "10.4", "declared-family", "declared-family", "condition-met"),
        ("10.4", "10.2", "declared-family", "declared-family", "conflict"),
        ("10.2", "10.2", "declared-family", "declared-family", "conflict"),
        ("10.2", "10.4", "declared-family", "different-family", "conflict"),
        ("10.2", "10.4", "", "", "unknown"),
    ],
)
def test_upgrade_requires_newer_mode_same_independently_declared_family(
    mode, active, family, other, status
):
    result = evaluate(
        "upgrade-caf",
        caf_release_mode=mode,
        active_release_mode=active,
        caf_device_family=family,
        active_device_family=other,
        source_channel="production",
    )
    assert findings(result)["cct18.upgrade-mode-family"]["status"] == status
    assert findings(result)["cct.prerelease-upgrade"]["status"] == "condition-met"
    assert "exact controller model/package/firmware compatibility" in result["unverified"]


@pytest.mark.parametrize(
    "channel,status", [("alpha", "conflict"), ("beta", "conflict"), ("unknown", "unknown")]
)
def test_alpha_beta_exception_cannot_be_overridden_by_numeric_order(channel, status):
    result = evaluate(
        "upgrade-caf",
        source_channel=channel,
        caf_release_mode="10.2",
        active_release_mode="10.4",
        caf_device_family="same",
        active_device_family="same",
    )
    assert findings(result)["cct.prerelease-upgrade"]["status"] == status
    assert findings(result)["cct18.upgrade-mode-family"]["status"] == "condition-met"
    if channel != "unknown":
        assert result["status"] == "documented-conflict"


@pytest.mark.parametrize(
    "destination,generation,evidence,status",
    [
        ("16.0", "pre-16-only", "Reviewed package record", "conflict"),
        ("18.0", "pre-16-only", "Reviewed package record", "conflict"),
        ("18.0", "updated-16-plus", "Reviewed package record", "condition-met"),
        ("18.0", "updated-16-plus", "", "unknown"),
        ("18.0", "unknown", "Reviewed package record", "unknown"),
        ("15.0", "pre-16-only", "Reviewed package record", "unknown"),
        ("19.0", "updated-16-plus", "Reviewed package record", "unknown"),
    ],
)
def test_package_security_generation_is_explicit_and_source_qualified(
    destination, generation, evidence, status
):
    result = evaluate(
        "define-hardware",
        destination=destination,
        package_generation=generation,
        package_generation_evidence=evidence,
    )
    assert findings(result)["cct16.package-security"]["status"] == status
    assert findings(result)["cct16.package-security"]["sources"][0]["pdf_pages"] == [38]


def test_missing_required_package_license_dominates_unknown_but_optional_does_not():
    package = inventory()["packages"][0]
    missing = package | {"name": "Required missing", "license_status": "missing"}
    unknown = package | {"name": "Required unknown", "license_status": "unknown"}
    result = evaluate("transfer-to-device", packages=[missing, unknown])
    assert findings(result)["cct18.package-license"]["status"] == "conflict"
    result = evaluate("define-hardware", packages=[package, missing | {"required": False}])
    assert findings(result)["cct18.package-license"]["status"] == "condition-met"
    assert (
        findings(evaluate("define-hardware", packages=[]))["cct18.package-license"]["status"]
        == "unknown"
    )
    assert "cct18.package-license" not in findings(evaluate("open", packages=[missing]))


def test_sql_independence_is_not_a_runtime_installation_or_file_version_comparison():
    result = evaluate(source_sql_version="SQL Server Express", destination_sql_version="MSDE")
    assert findings(result)["cct.sql-file-independence"]["status"] == "condition-met"
    assert "runtime availability" in findings(result)["cct.sql-file-independence"]["detail"]
    caf = application(app_version="10.2", firmware="6.2")
    manifest = inventory()
    manifest["toolchain"]["version"] = "18.0"
    manifest["toolchain"]["sql_available"] = False
    report = preflight(
        caf,
        PreflightRequest(
            inventory_text=json.dumps(manifest),
            release_review=ReleaseReview(
                source_tool_product="CCT",
                source_tool_release="10.2",
                source_sql_version="SQL Express",
                destination_sql_version="MSDE",
            ),
        ),
    )
    assert next(r for r in report["checks"] if r["id"] == "tool.sql")["status"] == "blocked"
    assert report["status"] == "blocked" and not report["can_deploy"]
    assert report["release_review"]["source"]["observed_appl_sw_version"] == "10.2"
    assert report["release_review"]["source"]["declarations"]["caf_release_mode"] == ""


def test_mixed_firmware_rule_explicitly_retains_enumeration_display_gap():
    result = evaluate("mstp-coexistence", mixed_firmware_on_mstp=True)
    row = findings(result)["cct.mstp-mixed-firmware"]
    assert (
        row["status"] == "condition-met" and "enumerations may display incorrectly" in row["detail"]
    )
    assert "full attribute/enumeration display" in result["unverified"]
    assert findings(evaluate("mstp-coexistence"))["cct.mstp-mixed-firmware"]["status"] == "unknown"


@pytest.mark.parametrize(
    "source_product,destination_product,expected_rule",
    [("PCT", "CCT", "cct.earlier-open-commission"), ("CCT", "PCT", "pct103.release-modes")],
)
def test_cross_product_software_consolidation_never_proves_application_equivalence(
    source_product, destination_product, expected_rule
):
    manifest = InventoryManifest.model_validate(inventory())
    manifest.toolchain.product = destination_product
    manifest.toolchain.version = "18.0" if destination_product == "CCT" else "10.3"
    result = review(
        ReleaseReview(
            source_tool_product=source_product,
            source_tool_release="10.2",
            caf_release_mode="10.2",
            active_release_mode="10.2",
        ),
        manifest.toolchain,
        manifest.packages,
        caf_sha256="c" * 64,
        application_version="10.2",
    )
    assert findings(result)[expected_rule]["status"] == "unknown"
    assert findings(result)["pct-cct.not-equivalent"]["status"] == "unknown"
    assert result["status"] == "needs-evidence"


@pytest.mark.parametrize(
    "mode,active,origin,status",
    [
        ("10.2", "10.2", "10.2", "condition-met"),
        ("10.2", "10.3", "10.2", "conflict"),
        ("9.0", "9.0", "9.0", "unknown"),
        ("10.99", "10.99", "10.2", "unknown"),
    ],
)
def test_pct103_only_documents_its_historical_release_mode_workflow(mode, active, origin, status):
    manifest = InventoryManifest.model_validate(inventory())
    manifest.toolchain.product = "PCT"
    manifest.toolchain.version = "10.3"
    result = review(
        ReleaseReview(
            operation="simulate",
            source_tool_product="PCT",
            source_tool_release=origin,
            caf_release_mode=mode,
            active_release_mode=active,
        ),
        manifest.toolchain,
        manifest.packages,
        caf_sha256="c" * 64,
        application_version="10.2",
    )
    assert findings(result)["pct103.release-modes"]["status"] == status
    assert not result["can_execute_native"]


def test_unknown_origin_stays_unresolved_even_with_matching_declared_modes():
    manifest = InventoryManifest.model_validate(inventory())
    manifest.toolchain.version = "18.0"
    result = review(
        ReleaseReview(operation="simulate", caf_release_mode="10.2", active_release_mode="10.2"),
        manifest.toolchain,
        manifest.packages,
        caf_sha256="c" * 64,
        application_version="10.2",
    )
    assert findings(result)["cct18.mode-operation"]["status"] == "condition-met"
    assert findings(result)["application.origin-unknown"]["status"] == "unknown"
    assert result["status"] == "needs-evidence"


def test_catalog_hash_exact_primary_sources_and_schema_bounds():
    document = catalog()
    assert document["ruleset_sha256"] == RULESET_SHA
    assert (
        hashlib.sha256(
            json.dumps(
                document["ruleset"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        == RULESET_SHA
    )
    hashes = {s["sha256"] for r in document["ruleset"]["rules"] for s in r["sources"]}
    assert hashes == {
        "cd4ec7ba7d8012a1dbfa8ced59ae6d14cf025a08f99614473be41af889543a73",
        "0c12f1988f5be8c46cc9d779d782139fe2b41994d98afc54d7dfc91e234d20d4",
        "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
        "46aeeb12517462f3eae28e177dff57bd38ea319cd98dcb7a067eb2aed9006248",
    }
    for invalid in (
        {"operation": "execute-a-script"},
        {"source_tool_release": "x" * 81},
        {"mixed_firmware_on_mstp": "true"},
        {"package_generation_evidence": "x" * 2001},
        {"made_up": True},
    ):
        with pytest.raises(ValueError):
            ReleaseReview.model_validate(invalid)


def test_future_source_tool_does_not_pass_matching_mode_only_review():
    manifest = InventoryManifest.model_validate(inventory())
    manifest.toolchain.version = "18.0"
    result = review(
        ReleaseReview(
            operation="simulate",
            source_tool_product="CCT",
            source_tool_release="99.0",
            caf_release_mode="10.2",
            active_release_mode="10.2",
        ),
        manifest.toolchain,
        manifest.packages,
        caf_sha256="d" * 64,
        application_version="10.2",
    )
    assert findings(result)["cct18.mode-operation"]["status"] == "condition-met"
    assert findings(result)["application.origin-unknown"]["status"] == "unknown"
    assert result["status"] == "needs-evidence"


@pytest.mark.parametrize("operation", ["simulate", "edit-logic", "edit-defaults"])
@pytest.mark.parametrize(
    "caf_mode,active_mode",
    [("99.0", "99.0"), ("10.99", "10.99"), ("18.0", "18.0"), ("99.0", "10.2"), ("10.2", "10.99")],
)
def test_mode_reference_coverage_is_independent_of_equality_tool_release_and_order(
    operation, caf_mode, active_mode
):
    result = evaluate(operation, caf_release_mode=caf_mode, active_release_mode=active_mode)
    rows = findings(result)
    assert rows["cct18.mode-reference-coverage"]["status"] == "unknown"
    if caf_mode == active_mode:
        assert rows["cct18.mode-operation"]["status"] == "condition-met"
        assert result["status"] == "needs-evidence"
    assert result["status"] != "documented-conditions-only"
    assert result["source"]["declarations"]["caf_release_mode"] == caf_mode
    assert result["source"]["declarations"]["active_release_mode"] == active_mode
    assert not result["can_execute_native"] and not result["can_deploy"]
    verify_seal(result)


def test_future_upgrade_destination_does_not_pass_other_matching_prerequisites():
    result = evaluate(
        "upgrade-caf",
        source_channel="production",
        caf_release_mode="10.2",
        active_release_mode="99.0",
        caf_device_family="same",
        active_device_family="same",
        package_generation="updated-16-plus",
        package_generation_evidence="Authored generation evidence",
    )
    rows = findings(result)
    assert rows["cct18.upgrade-mode-family"]["status"] == "condition-met"
    assert rows["cct16.package-security"]["status"] == "condition-met"
    assert rows["cct.prerelease-upgrade"]["status"] == "condition-met"
    assert rows["cct18.mode-reference-coverage"]["status"] == "unknown"
    assert result["status"] == "needs-evidence"


def test_explicit_mode_references_are_not_an_installed_or_complete_support_list():
    from bms_tool.jci_release_rules import CCT18_MODE_REFERENCES

    assert set(CCT18_MODE_REFERENCES) == {f"10.{i}" for i in range(8)}
    assert CCT18_MODE_REFERENCES["10.6"][0]["pdf_pages"] == [259]
    assert CCT18_MODE_REFERENCES["10.7"][0]["pdf_pages"] == [766]
    assert all(
        source["sha256"] == "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903"
        for sources in CCT18_MODE_REFERENCES.values()
        for source in sources
    )
    assert "Non-exhaustive" in catalog()["ruleset"]["mode_reference_scope"]
    for mode in CCT18_MODE_REFERENCES:
        result = evaluate("simulate", caf_release_mode=mode, active_release_mode=mode)
        assert findings(result)["cct18.mode-reference-coverage"]["status"] == "condition-met"
        assert "exact controller model/package/firmware compatibility" in result["unverified"]
        assert not result["can_execute_native"]
