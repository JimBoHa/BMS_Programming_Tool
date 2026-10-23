"""Independent role sets, exact source bindings and finite electrical witnesses."""

import copy
import csv
import hashlib
import io
import json

import pytest
from bms_tool import physical_capacity as cap
from bms_tool.hydronic_io import (
    PROFILE,
    Binding,
    HydronicPlanner,
    ReviewRequest,
    Topology,
    csv_report,
    derive,
)
from bms_tool.models import Node, Program
from bms_tool.plant_signals import PROFILE as PLANT_PROFILE
from bms_tool.plant_signals import PlantSignals, ReviewKey, digest, encoded, verify_report
from bms_tool.plant_signals import ReviewRequest as PlantRequest
from bms_tool.storage import Store
from pydantic import ValidationError


def topology(loop="primary-only", arrangement="headered", strategy="decoupler-flow", *, n=1):
    value = {
        "loop": loop,
        "primary_arrangement": arrangement,
        "chillers": n,
        "primary_speed": "variable",
        "units": {"flow": "gpm", "pressure": "psi", "temperature": "degF"},
    }
    if arrangement == "headered":
        value.update(primary_pumps=n, equally_sized_primary=True, isolation_command="binary")
    if loop == "primary-secondary":
        value.update(
            secondary_pumps=n, equally_sized_secondary=True, primary_speed_measurement=strategy
        )
    return value


def role_plan(value):
    return derive({"profile_sha256": PROFILE["sha256"], "topology": value})


def make_case(directory, value=None, *, network=False):
    value = value or topology()
    plant = PlantSignals(Store(directory))
    authored = role_plan(value)
    nodes, remote, assignments, remote_assignments, bindings, links = [], [], [], [], [], []
    for index, role in enumerate(authored["roles"]):
        identifier = role["id"].replace(".", "_")
        nodes.append(
            Node(
                id=identifier,
                kind=role["direction"].capitalize(),
                label=role["label"],
                unit=role["unit"],
                value_type=role["value_type"],
            )
        )
        entry = {
            "role_id": role["id"],
            "instance_id": "main",
            "node_id": identifier,
            "transport": "network" if network else "physical",
        }
        if network:
            sender = role["direction"] == "output"
            remote_id = identifier + "_remote"
            remote.append(
                Node(
                    id=remote_id,
                    kind="Input" if sender else "Output",
                    label="Explicit remote endpoint",
                    unit=role["unit"],
                    value_type=role["value_type"],
                )
            )
            assignments.append(
                {
                    "instance_id": "main",
                    "node_id": identifier,
                    "role": "network-source" if sender else "network-destination",
                }
            )
            remote_assignments.append(
                {
                    "instance_id": "remote",
                    "node_id": remote_id,
                    "role": "network-destination" if sender else "network-source",
                }
            )
            local = {"instance_id": "main", "node_id": identifier}
            other = {"instance_id": "remote", "node_id": remote_id}
            link = {
                "id": "link" + str(index),
                "source": local if sender else other,
                "target": other if sender else local,
            }
            links.append(link)
            entry["network_link_ids"] = [link["id"]]
        else:
            assignments.append(
                {
                    "instance_id": "main",
                    "node_id": identifier,
                    "role": "sensor" if role["direction"] == "input" else "command",
                    "terminal_key": "T" + str(index),
                }
            )
            mode = "input-contact" if role["value_type"] == "boolean" else "input-voltage"
            if role["direction"] == "output":
                mode = "output-triac" if role["value_type"] == "boolean" else "output-voltage"
            entry.update(physical_host_id="controller", mode=mode)
        bindings.append(entry)
    main = Program(
        id="hydraulic-source",
        name="Exact declared hydraulic interfaces",
        revision=3,
        nodes=nodes,
        metadata={"opaque": [9007199254740993, -0.0]},
    )
    source = plant.import_source(main.model_dump_json().encode())
    declaration = {
        "id": "plant",
        "name": "Declared hydraulic subset",
        "hosts": [
            {"id": "mainhost", "label": "Main declared host", "declared_model": "FX-PCG2611-0"}
        ],
        "instances": [
            {
                "id": "main",
                "label": "Hydraulic subsystem",
                "source_id": source["id"],
                "host_id": "mainhost",
                "subsystems": ["chiller", "pchwp", "schwp"],
            }
        ],
        "assignments": assignments,
        "links": links,
    }
    if network:
        source_remote = plant.import_source(
            Program(id="remote-source", name="Declared remote sources and consumers", nodes=remote)
            .model_dump_json()
            .encode()
        )
        declaration["hosts"].append({"id": "remotehost", "label": "Remote declared host"})
        declaration["instances"].append(
            {
                "id": "remote",
                "label": "Explicit remote subsystem",
                "source_id": source_remote["id"],
                "host_id": "remotehost",
                "subsystems": ["other"],
            }
        )
        declaration["assignments"] += remote_assignments
    reviewed = plant.review(PlantRequest(profile_sha256=PLANT_PROFILE["sha256"], plan=declaration))
    assert reviewed["analysis"]["status"] == "software_consistent"
    key = {"id": reviewed["id"], "content_sha256": reviewed["content_sha256"]}
    request = {
        "profile_sha256": PROFILE["sha256"],
        "topology": value,
        "plant_review": key,
        "capacity_catalog_sha256": cap.CATALOG["catalog_sha256"],
        "bindings": bindings,
        "physical_hosts": []
        if network
        else [
            {
                "id": "controller",
                "label": "Explicit base controller",
                "plant_host_id": "mainhost",
                "kind": "controller",
                "model": "FX-PCG2611-0",
            }
        ],
    }
    return HydronicPlanner(plant, None), request, main


@pytest.mark.parametrize(
    "loop,arrangement,strategy,extra",
    [
        ("primary-only", "headered", None, {"plant.minimum_flow_bypass", "primary.flow"}),
        ("primary-only", "dedicated", None, {"plant.minimum_flow_bypass", "primary.flow"}),
        (
            "primary-secondary",
            "headered",
            "decoupler-flow",
            {"primary.flow", "secondary.flow", "decoupler.flow"},
        ),
        ("primary-secondary", "headered", "flow-difference", {"primary.flow", "secondary.flow"}),
        (
            "primary-secondary",
            "headered",
            "temperature-difference",
            {
                "primary.flow",
                "secondary.flow",
                "primary.supply_temperature",
                "secondary.supply_temperature",
            },
        ),
        ("primary-secondary", "dedicated", "decoupler-flow", {"secondary.flow", "decoupler.flow"}),
        ("primary-secondary", "dedicated", "flow-difference", {"primary.flow", "secondary.flow"}),
        (
            "primary-secondary",
            "dedicated",
            "temperature-difference",
            {"secondary.flow", "primary.supply_temperature", "secondary.supply_temperature"},
        ),
    ],
)
@pytest.mark.parametrize("count", [1, 2, 8])
def test_independent_complete_role_sets_for_four_layouts_and_strategies(
    loop, arrangement, strategy, extra, count
):
    value = topology(loop, arrangement, strategy, n=count)
    result = role_plan(value)
    expected = {"building.dp"} | extra
    for i in range(1, count + 1):
        expected.update({f"chiller.{i}.enable", f"primary.{i}.enable", f"primary.{i}.speed"})
        if arrangement == "headered":
            expected.add(f"chiller.{i}.isolation")
        if loop == "primary-secondary":
            expected.update({f"secondary.{i}.enable", f"secondary.{i}.speed"})
    assert {r["id"] for r in result["roles"]} == expected
    assert result == role_plan(value) and encoded(result) == encoded(role_plan(value))
    assert csv_report(result) == csv_report(role_plan(value))
    assert result["content_sha256"] == digest(
        {k: v for k, v in result.items() if k != "content_sha256"}
    )
    assert not result["control_program_generated"] and not result["field_queries"]


def test_independent_quantities_shared_measurements_and_optional_proving():
    value = topology("primary-secondary", "headered", "flow-difference", n=2)
    value.update(
        primary_pumps=3,
        secondary_pumps=4,
        monitoring=["primary-flow", "secondary-flow", "chiller-status"],
        prove_on=["chiller"],
    )
    result = role_plan(value)
    roles = {r["id"]: r for r in result["roles"]}
    assert len([r for r in roles if r.startswith("primary.") and r.endswith(".enable")]) == 3
    assert len([r for r in roles if r.startswith("secondary.") and r.endswith(".enable")]) == 4
    assert {r["use"] for r in roles["primary.flow"]["reasons"]} == {
        "primary-speed-control",
        "primary-flow-staging",
        "optional-monitor",
    }
    assert {r["use"] for r in roles["secondary.flow"]["reasons"]} == {
        "primary-speed-control",
        "secondary-flow-staging",
        "optional-monitor",
    }
    assert {r["use"] for r in roles["chiller.1.status"]["reasons"]} == {
        "selected-prove-on",
        "optional-monitor",
    }
    assert len(result["unresolved_sequence_assumptions"]) == 2
    assert "temperature-strategy-flow-staging" in {r["id"] for r in result["source_conflicts"]}


@pytest.mark.parametrize(
    "mutation",
    [
        {"chillers": True},
        {"chillers": 0},
        {"chillers": 9},
        {"primary_pumps": 1.0},
        {"equally_sized_primary": 1},
        {"equally_sized_primary": False},
        {"primary_speed": "constant"},
        {"primary_pumps": None},
        {"isolation_command": None},
        {"secondary_pumps": 1},
        {"primary_speed_measurement": "decoupler-flow"},
        {"monitoring": ["secondary-status"]},
        {"prove_on": ["secondary"]},
        {"monitoring": ["primary-flow", "primary-flow"]},
        {"units": {"flow": "%", "pressure": "psi", "temperature": "degF"}},
    ],
)
def test_invalid_or_irrelevant_choices_refused(mutation):
    value = topology()
    value.update(mutation)
    with pytest.raises(ValidationError):
        Topology.model_validate(value)


def test_dedicated_rejects_headered_options_and_secondary_needs_all_choices():
    value = topology(arrangement="dedicated")
    value["primary_pumps"] = 1
    with pytest.raises(ValidationError):
        Topology.model_validate(value)
    value = topology("primary-secondary")
    value["equally_sized_secondary"] = 1
    with pytest.raises(ValidationError):
        Topology.model_validate(value)
    with pytest.raises(ValueError, match="profile changed"):
        derive({"profile_sha256": "0" * 64, "topology": topology()})


@pytest.mark.parametrize(
    "loop,arrangement",
    [
        ("primary-only", "headered"),
        ("primary-only", "dedicated"),
        ("primary-secondary", "headered"),
        ("primary-secondary", "dedicated"),
    ],
)
@pytest.mark.parametrize("network", [False, True])
def test_exact_bindings_original_source_bytes_and_physical_network_separation(
    tmp_path, loop, arrangement, network
):
    service, request, source = make_case(tmp_path, topology(loop, arrangement), network=network)
    raw = service.review(request)
    report = json.loads(raw)
    assert report["status"] == "declared-subset-consistent" and report["logical_bindings_complete"]
    original = report["plant_reference"]["original_review_json"].encode()
    plant, _ = verify_report(original)
    assert any(
        s["source_json"].encode() == source.model_dump_json().encode() for s in plant["sources"]
    )
    assert b"9007199254740993" in original and b"-0.0" in original
    assert hashlib.sha256(original).hexdigest() == report["plant_reference"]["raw_sha256"]
    assert service.export({"content_sha256": report["content_sha256"]}, "json") == raw
    csv_data = service.export({"content_sha256": report["content_sha256"]}, "csv")
    assert csv_data == service.export({"content_sha256": report["content_sha256"]}, "csv")
    assert len(list(csv.DictReader(io.StringIO(csv_data.decode())))) == len(
        report["role_plan"]["roles"]
    )
    assert len(report["capacity_reviews"]) == (0 if network else 1)
    if network:
        assert all(
            b["network_evidence"] and b["physical_host_id"] is None
            for b in report["binding_results"]
        )
    else:
        witness = report["capacity_reviews"][0]["capacity_review"]
        assert witness["declared_channels"] == len(request["bindings"])
        assert witness["status"] == "count-mode-fit"
    assert not report["hardware_verified"] and not report["whole_application_fit_established"]


@pytest.mark.parametrize(
    "field,changed,code",
    [
        ("direction", "output", "direction-mismatch"),
        ("value_type", "boolean", "type-mismatch"),
        ("unit", "kPa", "unit-mismatch"),
    ],
)
def test_exact_node_metadata_cannot_be_relabelled_as_matching(tmp_path, field, changed, code):
    service, request, _ = make_case(tmp_path)
    # Modify the exact imported portable source and regenerate a legitimate PLANT review.
    old = service.plant.export_review(ReviewKey(**request["plant_review"]), "json")
    plant = json.loads(old)
    p = Program.model_validate_json(plant["sources"][0]["source_json"])
    node = next(n for n in p.nodes if n.id == "building_dp")
    setattr(
        node,
        {"direction": "kind"}.get(field, field),
        changed.capitalize() if field == "direction" else changed,
    )
    imported = service.plant.import_source(p.model_dump_json().encode())
    plan = plant["plan"]
    plan["instances"][0]["source_id"] = imported["id"]
    if field == "direction":
        next(a for a in plan["assignments"] if a["node_id"] == node.id)["role"] = "command"
    view = service.plant.review(PlantRequest(profile_sha256=PLANT_PROFILE["sha256"], plan=plan))
    request["plant_review"] = {"id": view["id"], "content_sha256": view["content_sha256"]}
    report = json.loads(service.review(request))
    assert code in {d["code"] for d in report["diagnostics"]}
    assert report["status"] == "unresolved" and not report["logical_bindings_complete"]


@pytest.mark.parametrize(
    "mode,code",
    [("input-contact", "numeric-mode-mismatch"), ("output-voltage", "mode-direction-mismatch")],
)
def test_explicit_electrical_modes_cannot_be_inferred_from_analog_labels(tmp_path, mode, code):
    service, request, _ = make_case(tmp_path)
    request["bindings"][0]["mode"] = mode
    report = json.loads(service.review(request))
    assert code in {r["code"] for r in report["diagnostics"]}


def test_duplicate_endpoint_and_role_and_network_capacity_claims_refused(tmp_path):
    service, request, _ = make_case(tmp_path)
    request["bindings"][1]["node_id"] = request["bindings"][0]["node_id"]
    with pytest.raises(ValidationError, match="endpoint"):
        ReviewRequest.model_validate(request)
    request["bindings"][1]["node_id"] = "other"
    request["bindings"][1]["role_id"] = request["bindings"][0]["role_id"]
    with pytest.raises(ValidationError, match="one binding"):
        ReviewRequest.model_validate(request)
    with pytest.raises(ValidationError):
        Binding.model_validate(
            {
                "role_id": "primary.flow",
                "instance_id": "main",
                "node_id": "flow",
                "transport": "network",
                "physical_host_id": "base",
                "network_link_ids": ["flowlink"],
            }
        )


def test_module_requires_explicit_parent_and_never_adds_capacity_to_base(tmp_path):
    service, request, _ = make_case(tmp_path)
    request["physical_hosts"].append(
        {
            "id": "module",
            "label": "Declared SA module",
            "plant_host_id": "mainhost",
            "kind": "module",
            "model": "FX-PCX3711-0",
            "parent_controller_id": "controller",
        }
    )
    next(b for b in request["bindings"] if b["role_id"] == "primary.flow")["physical_host_id"] = (
        "module"
    )
    report = json.loads(service.review(request))
    assert report["status"] == "declared-subset-consistent"
    counts = {
        r["physical_host"]["id"]: r["capacity_review"]["declared_channels"]
        for r in report["capacity_reviews"]
    }
    assert counts == {"controller": 6, "module": 1}
    request["physical_hosts"][1]["parent_controller_id"] = "absent"
    with pytest.raises(ValueError, match="parent"):
        service.review(request)


def test_capacity_shortfall_unknown_models_and_source_stale_guards(tmp_path, monkeypatch):
    service, request, _ = make_case(tmp_path)
    request["physical_hosts"][0]["model"] = "FX-PCV1615-0"
    plant_raw = service.plant.export_review(ReviewKey(**request["plant_review"]), "json")
    p = json.loads(plant_raw)
    p["plan"]["hosts"][0]["declared_model"] = "FX-PCV1615-0"
    view = service.plant.review(
        PlantRequest(profile_sha256=PLANT_PROFILE["sha256"], plan=p["plan"])
    )
    request["plant_review"] = {"id": view["id"], "content_sha256": view["content_sha256"]}
    report = json.loads(service.review(request))
    assert "capacity-count-mode-shortfall" in {d["code"] for d in report["diagnostics"]}
    assert report["capacity_reviews"][0]["capacity_review"]["declared_channels"] == 7
    key = {"content_sha256": report["content_sha256"]}
    monkeypatch.setitem(cap.CATALOG, "catalog_sha256", "0" * 64)
    with pytest.raises(ValueError, match="catalog changed"):
        service.export(key, "json")


def test_exact_network_link_set_not_a_name_or_partial_fanout_match(tmp_path):
    service, request, _ = make_case(tmp_path, network=True)
    request["bindings"][0]["network_link_ids"] = ["made_up"]
    report = json.loads(service.review(request))
    assert "network-link-set-mismatch" in {d["code"] for d in report["diagnostics"]}
    request["plant_review"]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source changed"):
        service.review(request)


def test_missing_roles_explicit_no_spare_claim_and_original_source_after_new_revision(tmp_path):
    service, request, source = make_case(tmp_path)
    request["bindings"].pop()
    report = json.loads(service.review(request))
    assert any(d["code"] == "missing-binding" for d in report["diagnostics"])
    source.revision += 1
    service.plant.import_source(source.model_dump_json().encode())
    assert json.loads(service.review(request))["plant_reference"] == report["plant_reference"]
    assert (
        not report["whole_application_fit_established"]
        and "occupancy unknown" in report["capacity_scope"]
    )


def test_exact_survey_reference_revalidated_on_export_without_application_occupancy(tmp_path):
    service, request, _ = make_case(tmp_path)
    original = {
        "content_sha256": "a" * 64,
        "identity": {"model": "FX-PCG2611-0"},
        "target": {"device_instance": 15},
        "modules": [],
        "imported": True,
    }

    class Hardware:
        def report(self, identifier):
            if identifier != "b" * 32:
                raise ValueError("Stored hardware report missing")
            return original

    service.hardware = Hardware()
    request["physical_hosts"][0]["survey_reference"] = {
        "id": "b" * 32,
        "content_sha256": "a" * 64,
        "host": "base",
    }
    report = json.loads(service.review(request))
    capacity_review = report["capacity_reviews"][0]["capacity_review"]
    assert capacity_review["survey_binding"]["occupancy_applied"] is False
    original["content_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="survey hash changed"):
        service.export({"content_sha256": report["content_sha256"]}, "csv")


def test_unknown_exact_model_never_inherits_capacity_and_retained_export_seals(tmp_path):
    service, request, _ = make_case(tmp_path)
    original = json.loads(service.plant.export_review(ReviewKey(**request["plant_review"]), "json"))
    original["plan"]["hosts"][0]["declared_model"] = "FX-PCG2611-UNKNOWN"
    view = service.plant.review(
        PlantRequest(profile_sha256=PLANT_PROFILE["sha256"], plan=original["plan"])
    )
    request["plant_review"] = {"id": view["id"], "content_sha256": view["content_sha256"]}
    request["physical_hosts"][0]["model"] = "FX-PCG2611-UNKNOWN"
    body = service.review(request)
    report = json.loads(body)
    assert report["capacity_reviews"][0]["capacity_review"]["status"] == "unknown-model"
    assert "capacity-unknown-model" in {row["code"] for row in report["diagnostics"]}
    assert report["status"] == "unresolved"
    key = {"content_sha256": report["content_sha256"]}
    service.reviews[report["content_sha256"]] = body.replace(
        b'"hardware_verified":false', b'"hardware_verified":true', 1
    )
    with pytest.raises(ValueError, match="seal/profile"):
        service.export(key, "json")


@pytest.mark.parametrize(
    "kind", ["duplicate-base", "unused-module", "missing-parent", "wrong-kind"]
)
def test_physical_identity_ownership_cannot_duplicate_or_infer_expansions(tmp_path, kind):
    service, request, _ = make_case(tmp_path)
    extra = {
        "id": "other",
        "label": "Explicit extra declaration",
        "plant_host_id": "mainhost",
        "kind": "module",
        "model": "FX-PCX3711-0",
        "parent_controller_id": "controller",
    }
    if kind == "duplicate-base":
        extra = request["physical_hosts"][0] | {"id": "other"}
    elif kind == "missing-parent":
        extra["parent_controller_id"] = "absent"
    request["physical_hosts"].append(extra)
    if kind == "wrong-kind":
        request["physical_hosts"][1]["model"] = "FX-PCG2611-0"
        request["bindings"][0]["physical_host_id"] = "other"
        report = json.loads(service.review(request))
        assert report["status"] == "unresolved"
        assert "physical-kind-mismatch" in {r["code"] for r in report["diagnostics"]}
    else:
        with pytest.raises(ValueError):
            service.review(request)


def test_all_optional_monitors_and_proving_remain_single_roles_with_bounded_maximum():
    from typing import get_args

    from bms_tool.hydronic_io import MONITORS

    value = topology("primary-secondary", "headered", "temperature-difference", n=8)
    value.update(monitoring=list(get_args(MONITORS)), prove_on=["chiller", "primary", "secondary"])
    report = role_plan(value)
    assert len(report["roles"]) == len({r["id"] for r in report["roles"]}) <= 256
    assert not report["unresolved_sequence_assumptions"]
    for role in report["roles"]:
        assert role["reasons"] and role["direction"] in ("input", "output")
        assert all(r["source"] == "chilled-2025" for r in role["reasons"])
    assert not report["control_program_generated"]


def test_duplicate_exact_survey_host_refused_instead_of_double_counting(tmp_path):
    service, request, _ = make_case(tmp_path)
    request["physical_hosts"].append(
        {
            "id": "module",
            "label": "Authored module",
            "plant_host_id": "mainhost",
            "kind": "module",
            "model": "FX-PCX3711-0",
            "parent_controller_id": "controller",
            "survey_reference": {
                "id": "a" * 32,
                "content_sha256": "b" * 64,
                "host": "sa",
                "sa_mac": 3,
            },
        }
    )
    request["physical_hosts"].append(request["physical_hosts"][-1] | {"id": "module2"})
    next(b for b in request["bindings"] if b["role_id"] == "primary.flow")["physical_host_id"] = (
        "module"
    )
    with pytest.raises(ValueError, match="same exact survey host"):
        service.review(request)


def test_resealed_plant_interface_tampering_fails_original_source_regeneration(tmp_path):
    service, request, _ = make_case(tmp_path)
    raw = service.plant.export_review(ReviewKey(**request["plant_review"]), "json")
    changed = json.loads(raw)
    changed["analysis"]["io_schedule"][0]["unit"] = "kPa"
    changed["content_sha256"] = digest({k: v for k, v in changed.items() if k != "content_sha256"})
    service.plant.reviews[request["plant_review"]["id"]] = encoded(changed) + b"\n"
    request["plant_review"]["content_sha256"] = changed["content_sha256"]
    with pytest.raises(ValueError, match="regeneration"):
        service.review(request)


def test_csv_preserves_exact_source_identity_and_escapes_formula_labels(tmp_path):
    service, request, program = make_case(tmp_path)
    original = json.loads(service.plant.export_review(ReviewKey(**request["plant_review"]), "json"))
    program.name = "=UNVERIFIED_EXTERNAL_LABEL"
    source = service.plant.import_source(program.model_dump_json().encode())
    original["plan"]["instances"][0]["source_id"] = source["id"]
    view = service.plant.review(
        PlantRequest(profile_sha256=PLANT_PROFILE["sha256"], plan=original["plan"])
    )
    request["plant_review"] = {"id": view["id"], "content_sha256": view["content_sha256"]}
    report = json.loads(service.review(request))
    rows = list(
        csv.DictReader(
            io.StringIO(
                service.export({"content_sha256": report["content_sha256"]}, "csv").decode()
            )
        )
    )
    assert all(r["program_name"] == "'=UNVERIFIED_EXTERNAL_LABEL" for r in rows)
    assert all(
        r["source_id"] == source["id"] and r["physical_model"] == "FX-PCG2611-0" for r in rows
    )
    assert all(
        r["capacity_scope"].endswith("occupancy unknown") and r["hardware_verified"] == "false"
        for r in rows
    )


def test_explicit_unicode_units_are_exact_source_tokens_without_conversion(tmp_path):
    choice = topology("primary-secondary", "dedicated", "temperature-difference")
    choice["units"] = {"flow": "L/s", "pressure": "kPa", "temperature": "°C"}
    service, request, _ = make_case(tmp_path, choice, network=True)
    raw = service.review(request)
    report = json.loads(raw)
    assert report["status"] == "declared-subset-consistent" and "°C".encode() in raw
    assert {r["unit"] for r in report["role_plan"]["roles"] if r["id"].endswith("temperature")} == {
        "°C"
    }
    wrong = copy.deepcopy(request)
    wrong["topology"]["units"]["temperature"] = "degC"
    observed = json.loads(service.review(wrong))
    assert observed["status"] == "unresolved"
    assert len([d for d in observed["diagnostics"] if d["code"] == "unit-mismatch"]) == 2


@pytest.mark.parametrize(
    "role_id,mode,module",
    [
        ("primary.flow", "input-current", False),
        ("primary.flow", "input-resistance", False),
        ("primary.1.speed", "output-current", False),
        ("chiller.1.enable", "output-fet", True),
        ("chiller.1.enable", "output-relay", True),
    ],
)
def test_declared_alternative_electrical_modes_use_actual_separate_device_pools(
    tmp_path, role_id, mode, module
):
    service, request, _ = make_case(tmp_path)
    selected = next(b for b in request["bindings"] if b["role_id"] == role_id)
    selected["mode"] = mode
    if module:
        request["physical_hosts"].append(
            {
                "id": "module",
                "label": "Explicit alternate-mode module",
                "plant_host_id": "mainhost",
                "kind": "module",
                "model": "FX-PCX3711-0",
                "parent_controller_id": "controller",
            }
        )
        selected["physical_host_id"] = "module"
    report = json.loads(service.review(request))
    assert report["status"] == "declared-subset-consistent"
    witnesses = {r["physical_host"]["id"]: r["capacity_review"] for r in report["capacity_reviews"]}
    host = "module" if module else "controller"
    demand = next(d for d in witnesses[host]["demands"] if d["mode"] == mode)
    assert demand["quantity"] == demand["matched"] == 1
    assert sum(v["declared_channels"] for v in witnesses.values()) == 7
    assert not report["whole_application_fit_established"]


@pytest.mark.parametrize("field", ["instance_id", "node_id"])
def test_missing_exact_endpoint_is_visible_and_not_counted_as_valid_capacity(tmp_path, field):
    service, request, _ = make_case(tmp_path)
    selected = next(b for b in request["bindings"] if b["role_id"] == "primary.flow")
    selected[field] = "absent"
    report = json.loads(service.review(request))
    assert report["status"] == "unresolved" and not report["logical_bindings_complete"]
    assert "missing-endpoint" in {d["code"] for d in report["diagnostics"]}
    assert report["capacity_reviews"][0]["capacity_review"]["declared_channels"] == 6
