"""Bounded offline review of explicitly operator-declared integer enum maps."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator

from .models import StrictModel

Code = Annotated[int, Field(strict=True, ge=-(2**31), le=2**32 - 1)]


def _identity(value):
    if not value.strip():
        raise ValueError("Enum identities require a nonblank name.")
    return value


Identity = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_identity)]
PROFILE = "operator-enum-mapping-review/1"
SCOPE = "Offline operator-declared finite code domains and mappings only. BACnet datatype rules do not establish a native object binding, JCI Enum Set identity, portable enum code equivalence or executable lowering. No network operations, controller writes, CAF/CCT conversion or semantic-equivalence claim."

PROFILE_RULES = {
    "version": 1,
    "binarypv_codes": [0, 1],
    "multistate_minimum": 1,
    "maximum_states_per_domain": 256,
    "maximum_mappings": 256,
    "maximum_probes": 256,
    "code_profile": "strict integer -2147483648..4294967295; no bool/float/string coercion",
    "provenance": "operator declarations only; no automatic native/portable binding",
    "loss": "explicit many-to-one policy and nonblank rationale required",
    "coverage": "source totality separate from optional target coverage",
    "equivalence": "not established by labels or this review",
}


class EnumState(StrictModel):
    id: Identity
    code: Code
    label: str | None = Field(default=None, max_length=256)


class EnumDomain(StrictModel):
    namespace: Identity
    id: Identity
    datatype: Literal["declared-integer", "bacnet-binarypv", "bacnet-multistate"] = (
        "declared-integer"
    )
    states: list[EnumState] = Field(min_length=1, max_length=256)
    number_of_states: int | None = Field(default=None, strict=True, ge=1, le=2**32 - 1)
    declared_complete: bool = Field(default=True, strict=True)
    origin: Literal["operator-declared"] = "operator-declared"
    reference_notes: str = Field(default="", max_length=1000)


class EnumMapRow(StrictModel):
    source_code: Code
    target_code: Code | None = None


class EnumPolicy(StrictModel):
    allow_many_to_one: bool = Field(default=False, strict=True)
    loss_rationale: str = Field(default="", max_length=1000)
    require_target_coverage: bool = Field(default=False, strict=True)


class EnumMappingRequest(StrictModel):
    schema_version: Literal[1] = 1
    source: EnumDomain
    target: EnumDomain
    mappings: list[EnumMapRow] = Field(default_factory=list, max_length=256)
    policy: EnumPolicy = Field(default_factory=EnumPolicy)
    probes: list[Code | None] = Field(default_factory=list, max_length=256)

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Enum mapping schema_version requires integer 1.")
        return value


class EnumMappingExport(StrictModel):
    plan: EnumMappingRequest
    expected_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _missing_sample(codes, first, last):
    sample = []
    for code in range(first, min(last + 1, first + len(codes) + 32)):
        if code not in codes:
            sample.append(code)
            if len(sample) == 32:
                break
    return sample


def review_enum_mapping(body):
    options = body if isinstance(body, EnumMappingRequest) else EnumMappingRequest(**body)
    document = options.model_dump(mode="json")
    if len(canonical(document)) > 2 * 1024 * 1024:
        raise ValueError("Enum mapping plan exceeds its 2 MiB canonical source profile.")
    buckets = {"error": [], "warning": []}
    counts = Counter()
    codes_count = Counter()

    def finding(severity, code, **detail):
        counts[severity] += 1
        codes_count[code] += 1
        limit = 96 if severity == "error" else 32
        if len(buckets[severity]) < limit:
            buckets[severity].append(dict(severity=severity, code=code, **detail))

    def domain_review(domain, side):
        by_code = defaultdict(list)
        by_id = defaultdict(list)
        labels = defaultdict(list)
        for state in domain.states:
            by_code[state.code].append(state)
            by_id[state.id].append(state.code)
            if state.label is not None:
                labels[state.label].append(state.code)
            if state.label is None or not state.label.strip():
                finding(
                    "warning",
                    "unknown_or_blank_label",
                    domain=side,
                    state_code=state.code,
                    state_id=state.id,
                )
        valid = True
        for code, states in by_code.items():
            if len(states) > 1:
                valid = False
                finding(
                    "error",
                    "duplicate_domain_code",
                    domain=side,
                    state_code=code,
                    state_ids=[s.id for s in states],
                )
        for id, codes in by_id.items():
            if len(codes) > 1:
                valid = False
                finding("error", "duplicate_state_id", domain=side, state_id=id, codes=codes)
        for codes in labels.values():
            if len(codes) > 1:
                finding("warning", "duplicate_labels_do_not_merge_codes", domain=side, codes=codes)
        if not domain.declared_complete:
            valid = False
            finding("error", "domain_declared_incomplete", domain=side)
        codes = set(by_code)
        missing_count = 0
        missing_sample = []
        if domain.datatype == "bacnet-binarypv":
            expected = {0, 1}
            missing = expected - codes
            unknown = codes - expected
            missing_count = len(missing)
            missing_sample = sorted(missing)
            if missing or unknown:
                valid = False
                finding(
                    "error",
                    "binary_domain_must_be_exact_zero_one",
                    domain=side,
                    missing_codes=sorted(missing),
                    outside_codes=sorted(unknown),
                )
        elif domain.datatype == "bacnet-multistate":
            count = domain.number_of_states
            if count is None:
                valid = False
                finding("error", "multistate_count_unresolved", domain=side)
            else:
                outside = sorted(c for c in codes if not 1 <= c <= count)
                within = {c for c in codes if 1 <= c <= count}
                missing_count = count - len(within)
                missing_sample = _missing_sample(within, 1, count)
                if outside or missing_count:
                    valid = False
                    finding(
                        "error",
                        "multistate_domain_incomplete_or_outside_range",
                        domain=side,
                        number_of_states=count,
                        missing_count=missing_count,
                        missing_codes_sample=missing_sample,
                        outside_codes=outside,
                    )
        if domain.datatype != "bacnet-multistate" and domain.number_of_states is not None:
            valid = False
            finding("error", "count_not_applicable_to_datatype", domain=side)
        return (
            {c: states[0] for c, states in by_code.items()},
            valid,
            {
                "namespace": domain.namespace,
                "id": domain.id,
                "datatype": domain.datatype,
                "origin": "operator-declared",
                "valid_complete_declaration": valid,
                "declared_unique_codes": len(codes),
                "missing_domain_codes_count": missing_count,
                "missing_domain_codes_sample": missing_sample,
            },
        )

    source, source_valid, source_summary = domain_review(options.source, "source")
    target, target_valid, target_summary = domain_review(options.target, "target")
    if (options.source.namespace, options.source.id) == (
        options.target.namespace,
        options.target.id,
    ):

        def definition(d):
            return (
                d.datatype,
                d.number_of_states,
                sorted((s.code, s.id, s.label is None, s.label or "") for s in d.states),
            )

        if definition(options.source) != definition(options.target):
            source_valid = False
            target_valid = False
            source_summary["valid_complete_declaration"] = False
            target_summary["valid_complete_declaration"] = False
            finding("error", "same_domain_identity_has_conflicting_definition")
    rows = defaultdict(list)
    for index, row in enumerate(options.mappings):
        rows[row.source_code].append(row)
        if row.source_code not in source:
            finding(
                "error", "unknown_source_code", mapping_index=index, source_code=row.source_code
            )
        if row.target_code is None:
            finding(
                "error", "unmapped_source_code", mapping_index=index, source_code=row.source_code
            )
        elif row.target_code not in target:
            finding(
                "error", "unknown_target_code", mapping_index=index, target_code=row.target_code
            )
    for code, entries in rows.items():
        if len(entries) > 1:
            finding("error", "duplicate_source_mapping", source_code=code, rows=len(entries))
    effective = {
        c: entries[0].target_code
        for c, entries in rows.items()
        if c in source and len(entries) == 1 and entries[0].target_code in target
    }
    missing = sorted(set(source) - set(effective))
    if missing:
        finding("error", "source_states_not_deterministically_mapped", codes=missing)
    collapsed = defaultdict(list)
    for code, destination in effective.items():
        collapsed[destination].append(code)
    losses = [
        {"target_code": code, "source_codes": sorted(sources)}
        for code, sources in collapsed.items()
        if len(sources) > 1
    ]
    for loss in losses:
        if not options.policy.allow_many_to_one:
            finding("error", "many_to_one_loss_not_allowed", **loss)
        elif not options.policy.loss_rationale.strip():
            finding("error", "loss_rationale_required", **loss)
        else:
            finding("warning", "many_to_one_loss_explicitly_declared", **loss)
    unreachable = sorted(set(target) - set(effective.values()))
    if unreachable:
        finding(
            "error" if options.policy.require_target_coverage else "warning",
            "target_states_unreachable_from_declared_source",
            codes=unreachable,
        )
    evaluations = []
    resolved = effective if source_valid and target_valid else {}
    for code, destination in sorted(resolved.items()):
        a, b = source[code], target[destination]
        evaluations.append(
            {
                "source_state_id": a.id,
                "source_code": code,
                "source_label": a.label,
                "target_state_id": b.id,
                "target_code": destination,
                "target_label": b.label,
                "labels_equal": a.label is not None and a.label == b.label,
                "meaning": "Explicit operator row; label similarity is not semantic equivalence.",
            }
        )
    probes = []
    for value in options.probes:
        if value is None:
            probes.append({"input": None, "status": "unknown_value"})
        elif not source_valid or not target_valid:
            probes.append({"input": value, "status": "invalid_domain_declaration"})
        elif value not in source:
            probes.append({"input": value, "status": "unknown_source_code"})
        elif value not in effective:
            probes.append({"input": value, "status": "not_deterministically_mapped"})
        else:
            code = effective[value]
            state = target[code]
            probes.append(
                {
                    "input": value,
                    "status": "mapped_by_declared_table",
                    "target_code": code,
                    "target_state_id": state.id,
                    "target_label": state.label,
                    "target_datatype": options.target.datatype,
                }
            )
    function_complete = (
        source_valid
        and target_valid
        and not missing
        and all(
            c in source and len(rs) == 1 and rs[0].target_code in target for c, rs in rows.items()
        )
    )
    findings = buckets["error"] + buckets["warning"]
    report = {
        "profile": PROFILE,
        "profile_sha256": hashlib.sha256(canonical(PROFILE_RULES)).hexdigest(),
        "profile_rules": json.loads(canonical(PROFILE_RULES)),
        "scope": SCOPE,
        "source_plan": document,
        "source_plan_sha256": hashlib.sha256(canonical(document)).hexdigest(),
        "domains": {"source": source_summary, "target": target_summary},
        "policy": options.policy.model_dump(),
        "status": "invalid"
        if counts["error"]
        else "valid_with_declared_loss"
        if losses
        else "valid_declared_mapping",
        "properties": {
            "source_function_complete": function_complete,
            "lossless": (not losses) if function_complete else None,
            "target_coverage": (not unreachable) if target_valid else None,
            "semantic_equivalence": "not established",
            "native_or_portable_binding": "not established",
        },
        "missing_source_codes": missing,
        "unreachable_target_codes": unreachable,
        "collapsing_targets": losses,
        "mapping_evidence": evaluations,
        "probes": probes,
        "findings": findings,
        "finding_counts": dict(counts),
        "finding_code_counts": dict(codes_count),
        "omitted_findings": sum(counts.values()) - len(findings),
        "field_operations": False,
        "executable_lowering": False,
    }
    if len(canonical(report)) > 4 * 1024 * 1024:
        raise ValueError("Enum review exceeds its 4 MiB response profile.")
    report["review_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def export_review(body):
    report = review_enum_mapping(body.plan)
    if report["review_sha256"] != body.expected_review_sha256:
        raise ValueError(
            "Enum mapping source or rules changed; review the current declaration before export."
        )
    return report


def import_plan(raw):
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("Enum mapping plans require 1 byte through 2 MiB.")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in enum mapping plan.")
            result[key] = value
        return result

    def no_constant(value):
        raise ValueError("Nonfinite JSON constants are not allowed in enum mapping plans.")

    try:
        decoded = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=no_constant
        )
        plan = EnumMappingRequest.model_validate(decoded)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Enum mapping plan requires bounded UTF-8 JSON.") from exc
    document = plan.model_dump(mode="json")
    if len(canonical(document)) > 2 * 1024 * 1024:
        raise ValueError("Enum mapping plan exceeds its 2 MiB canonical source profile.")
    return {
        "source_plan": document,
        "source_plan_sha256": hashlib.sha256(canonical(document)).hexdigest(),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "origin": "operator-declared",
        "review_required": True,
        "native_or_portable_binding": "not established",
    }
