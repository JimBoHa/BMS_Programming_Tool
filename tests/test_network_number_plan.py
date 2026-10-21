"""Authored topology declarations, never site results or address inference."""

import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.network_number_plan import PROFILE, canonical, digest, review, template, validate_plan
from fastapi.testclient import TestClient


def attachment(id="a", domain="campus", network="bus-a", number=3001, **changes):
    return {
        "id": id,
        "label": "Authored " + id,
        "domain_key": domain,
        "physical_network_key": network,
        "network_number": number,
        "medium": "mstp",
        "role": "router-port",
        "endpoint_key": "router-" + id,
        "port_key": "mstp-1",
        "policy": "generic",
        "assignment_state": "existing",
        "notes": "Authored declaration, not observed hardware",
    } | changes


def plan(*rows, **changes):
    return template() | {"assignments": list(rows), "declarations_complete": True} | changes


def codes(result, severity=None):
    return {
        row["code"] for row in result["findings"] if severity is None or row["severity"] == severity
    }


def test_one_declared_network_via_multiple_routers_and_ports_is_valid():
    rows = [
        attachment("a"),
        attachment("b"),
        attachment("c", endpoint_key="router-a", port_key="mstp-2"),
    ]
    result = review(plan(*rows))
    assert result["status"] == "no-conflicts-in-declarations"
    assert result["findings"] == [] and result["declared_physical_networks"] == 1
    assert not result["physical_topology_verified"] and not result["inventory_verified"]
    assert not result["field_scans"] and not result["controller_writes"]


def test_same_number_on_distinct_declared_networks_conflicts_only_inside_one_domain():
    result = review(plan(attachment("a"), attachment("b", network="bus-b")))
    finding = next(
        row for row in result["findings"] if row["code"] == "number-on-distinct-networks"
    )
    assert finding["domain_key"] == "campus" and finding["network_number"] == 3001
    assert finding["physical_network_keys"] == ["bus-a", "bus-b"]
    assert finding["assignment_ids"] == ["a", "b"]
    assert result["status"] == "conflicts"
    separate = review(
        plan(attachment("a"), attachment("b", domain="separate-internetwork", network="bus-b"))
    )
    assert separate["status"] == "no-conflicts-in-declarations"
    assert separate["declared_domains"] == ["campus", "separate-internetwork"]


def test_declared_engine_and_router_same_bus_must_have_matching_numbers():
    result = review(
        plan(
            attachment("a", role="router-port"),
            attachment(
                "b",
                number=3002,
                role="engine-remote-field-integration",
                endpoint_key="engine-a",
                port_key="integration-3",
            ),
        )
    )
    assert codes(result, "error") == {"network-number-mismatch"}
    finding = result["findings"][0]
    assert finding["physical_network_key"] == "bus-a" and finding["network_numbers"] == [3001, 3002]


@pytest.mark.parametrize(
    "change", [{"network": "bus-b", "number": 3002}, {"number": 3002}, {"network": "bus-b"}]
)
def test_same_declared_endpoint_and_port_has_no_conflicting_network_assignments(change):
    a = attachment("a", endpoint_key="same-router", port_key="side-1")
    b = attachment("b", endpoint_key="same-router", port_key="side-1", **change)
    assert "endpoint-port-conflict" in codes(review(plan(a, b)), "error")
    b["domain_key"] = "unrelated-domain"
    assert "endpoint-port-conflict" not in codes(review(plan(a, b)))


def test_addresses_and_subnets_never_infer_network_identity():
    # Different literal IP-looking keys can still describe the same declared network.
    a = attachment("a", medium="bacnet-ip", endpoint_key="192.0.2.1:47808")
    b = attachment("b", medium="bacnet-ip", endpoint_key="198.51.100.2:47808")
    assert review(plan(a, b))["status"] == "no-conflicts-in-declarations"
    # Same IP-looking prefix does not merge explicitly different networks.
    b.update(endpoint_key="192.0.2.2:47808", physical_network_key="distinct-backbone")
    assert "number-on-distinct-networks" in codes(review(plan(a, b)))
    # Unknown relationships remain unknown even with identical numbers/endpoints.
    a.update(physical_network_key=None, endpoint_key="same-hint", port_key=None)
    b.update(physical_network_key=None, endpoint_key="same-hint", port_key=None)
    result = review(plan(a, b))
    assert codes(result, "error") == set()
    assert codes(result, "unknown") == {"unknown-physical-network", "incomplete-endpoint-port"}


def test_unknown_numbers_do_not_become_zero_or_collide_with_known_assignments():
    result = review(
        plan(attachment("a", number=None), attachment("b", network="bus-b", number=None))
    )
    assert result["status"] == "incomplete" and result["counts"]["unknown"] == 2
    assert codes(result) == {"unknown-network-number"}
    assert result["plan"]["assignments"][0]["network_number"] is None


@pytest.mark.parametrize("number", [1, 2, 1999, 2000, 65000, 65534])
def test_generic_assignable_boundaries_include_numbers_not_universally_reserved(number):
    assert review(plan(attachment(number=number)))["status"] == "no-conflicts-in-declarations"


@pytest.mark.parametrize("number", [0, 65535])
def test_local_and_global_destination_contexts_are_not_physical_network_numbers(number):
    result = review(plan(attachment(number=number)))
    assert codes(result, "error") == {"not-a-physical-network-number"}
    assert result["plan"]["assignments"][0]["network_number"] == number


@pytest.mark.parametrize("number", [2000, 65000])
@pytest.mark.parametrize("medium", ["bacnet-ip", "mstp"])
def test_r15_new_remote_field_reservations_are_exactly_scoped(number, medium):
    row = attachment(
        number=number, medium=medium, policy="jci-r15-remote-field", assignment_state="new"
    )
    assert codes(review(plan(row)), "error") == {"jci-r15-new-reserved-number"}
    row["assignment_state"] = "existing"
    result = review(plan(row))
    assert result["status"] == "no-conflicts-in-declarations"
    assert codes(result, "info") == {"jci-r15-existing-number-review"}
    row["assignment_state"] = "unknown"
    assert codes(review(plan(row)), "unknown") == {"jci-r15-assignment-state-unknown"}
    row.update(assignment_state="new", policy="generic")
    assert review(plan(row))["findings"] == []


@pytest.mark.parametrize("medium", ["unknown", "other"])
def test_r15_profile_needs_supported_declared_medium_and_never_extrapolates(medium):
    result = review(
        plan(
            attachment(
                number=2000, medium=medium, policy="jci-r15-remote-field", assignment_state="new"
            )
        )
    )
    assert codes(result, "unknown") == {"jci-profile-medium-unconfirmed"}
    assert not codes(result, "error")


def test_contradictory_media_and_route_hints_remain_explicit():
    result = review(plan(attachment("a"), attachment("b", medium="bacnet-ip")))
    assert codes(result, "error") == {"physical-medium-mismatch"}
    result = review(plan(attachment(role="route-advertisement")))
    assert result["status"] == "incomplete" and codes(result) == {"route-observation-only"}
    assert "Advertised routes" in result["scope"]


def test_empty_and_partial_inventory_never_claims_global_availability():
    assert codes(review(template())) == {"no-assignments", "inventory-not-declared-complete"}
    result = review(plan(attachment(), declarations_complete=False))
    assert result["status"] == "incomplete"
    assert "global available-number" in result["scope"]
    assert "available_numbers" not in result


def test_exact_case_sensitive_keys_are_operator_identity_not_label_or_number():
    a = attachment("a", network="Bus")
    b = attachment("b", network="bus")
    assert "number-on-distinct-networks" in codes(review(plan(a, b)))
    b["domain_key"] = "Campus"
    assert review(plan(a, b))["status"] == "no-conflicts-in-declarations"


def test_exact_source_and_content_hashes_retain_plan_and_operator_provenance():
    value = plan(attachment())
    snapshot = copy.deepcopy(value)
    result = review(value)
    assert value == snapshot  # review never edits/renumbers submitted declarations
    assert result["plan"] == validate_plan(snapshot).model_dump()
    assert result["plan_sha256"] == digest(result["plan"])
    assert (
        result["content_sha256"]
        == hashlib.sha256(
            canonical({k: v for k, v in result.items() if k != "content_sha256"})
        ).hexdigest()
    )
    assert result["source_profile"] == PROFILE
    assert "Operator-declared" in result["provenance"]
    assert (
        PROFILE["sources"][2]["sha256"]
        == "18c323a65edec4fe29120bab29d38303bf57e9b21fe1b1a108eb597c077aee37"
    )
    assert PROFILE["sha256"] == digest(
        {key: value for key, value in PROFILE.items() if key != "sha256"}
    )
    value["assignments"][0]["network_number"] = 3002
    assert review(value)["plan_sha256"] != result["plan_sha256"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(profile_sha256="0" * 64),
        lambda d: d.update(version=True),
        lambda d: d.update(version=2),
        lambda d: d.pop("format"),
        lambda d: d.update(name=" "),
        lambda d: d.update(declarations_complete=1),
        lambda d: d.update(extra="not supported"),
        lambda d: d["assignments"][0].update(domain_key=""),
        lambda d: d["assignments"][0].update(physical_network_key="contains spaces"),
        lambda d: d["assignments"][0].update(endpoint_key="x" * 81),
        lambda d: d["assignments"][0].update(network_number=True),
        lambda d: d["assignments"][0].update(network_number=3001.0),
        lambda d: d["assignments"][0].update(network_number="3001"),
        lambda d: d["assignments"][0].update(network_number=-1),
        lambda d: d["assignments"][0].update(network_number=65536),
        lambda d: d["assignments"][0].update(network_number=float("nan")),
        lambda d: d["assignments"][0].update(network_number=float("inf")),
        lambda d: d["assignments"][0].update(medium="inferred-ip-subnet"),
        lambda d: d["assignments"][0].update(policy="all-jci-releases"),
        lambda d: d["assignments"][0].update(notes="x" * 2001),
        lambda d: d["assignments"].append(copy.deepcopy(d["assignments"][0])),
    ],
)
def test_strict_bounded_and_stale_source_requests_are_rejected(mutate):
    value = plan(attachment())
    mutate(value)
    with pytest.raises(ValueError):
        validate_plan(value)


def test_record_and_byte_limits_with_valid_largest_inventory():
    rows = [attachment(str(i), network="network-" + str(i), number=i + 1) for i in range(512)]
    assert review(plan(*rows))["status"] == "no-conflicts-in-declarations"
    with pytest.raises(ValueError):
        validate_plan(plan(*rows, attachment("extra")))
    with pytest.raises(ValueError, match="2 MiB"):
        validate_plan(template() | {"notes": "x" * (2 * 1024 * 1024)})


def test_real_api_token_guards_json_roundtrip_and_no_field_activity(tmp_path):
    value = plan(attachment("a"), attachment("b", network="bus-b"))
    with TestClient(create_app(tmp_path)) as client:
        catalog = client.get("/api/network-number-plan/catalog")
        assert catalog.status_code == 200 and catalog.json()["profile"] == PROFILE
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for route in ("review", "validate"):
            assert (
                client.post("/api/network-number-plan/" + route, json={"plan": value}).status_code
                == 403
            )
        validated = client.post(
            "/api/network-number-plan/validate", headers=token, json={"plan": value}
        )
        assert validated.status_code == 200, validated.text
        value = json.loads(json.dumps(validated.json()["plan"]))
        result = client.post("/api/network-number-plan/review", headers=token, json={"plan": value})
        assert result.status_code == 200 and result.json()["status"] == "conflicts"
        assert result.json()["plan_sha256"] == validated.json()["plan_sha256"]
        assert (
            client.post(
                "/api/network-number-plan/review",
                headers=token,
                json={"plan": value, "apply": True},
            ).status_code
            == 422
        )
        value["profile_sha256"] = "0" * 64
        assert (
            client.post(
                "/api/network-number-plan/review", headers=token, json={"plan": value}
            ).status_code
            == 422
        )
        status = client.get("/api/bacnet/status").json()
        assert not status["connected"] and status["commands"] == []
        assert (
            client.post(
                "/api/network-number-plan/review", json={}, headers={"Host": "untrusted.example"}
            ).status_code
            == 403
        )
