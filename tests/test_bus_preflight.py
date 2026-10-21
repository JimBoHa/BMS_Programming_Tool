"""Authored planned buses and cables; no scanned site data or physical interfaces."""

import copy
import json

import pytest
from bms_tool.app import create_app
from bms_tool.bus_preflight import CATALOG, digest, review, template, validate_plan
from fastapi.testclient import TestClient


def bus(id="bus-a", **changes):
    return {
        "id": id,
        "name": "Authored " + id,
        "profile": "fx-2024",
        "kind": "sa",
        "segments": ["s1"],
        "inventory_complete": True,
        "nce_integral": "absent",
        "zfr1810_coordinators": "absent",
        "notes": "Authored physical bus assertion",
    } | changes


def device(id, role="iom", mac=4, **changes):
    return {
        "id": id,
        "label": "Authored " + id,
        "bus_id": "bus-a",
        "model": "FX-PCX3721-0",
        "generation": "legacy-dip128",
        "role": role,
        "mac": mac,
        "segment": "s1",
        "mode": "wired",
        "switch128": "off",
        "eol": "off",
        "notes": "Authored connection",
    } | changes


def host(**changes):
    return device("host", role="sa-host", mac=0, model="FX-PCV1630-0", eol="fixed-on") | changes


def sensor(**changes):
    return (
        device(
            "sensor",
            role="network-sensor",
            mac=199,
            model="NSB8BTN240-0",
            generation="refreshed-2025-12-08",
            switch128="not-applicable",
        )
        | changes
    )


def cable(a, b, kind="terminal", **changes):
    return {
        "id": a + "-" + b,
        "a": a,
        "b": b,
        "kind": kind,
        "length_m": 2.0,
        "straight_through": None,
        "notes": "Authored planned cable",
    } | changes


def plan(devices=None, links=None, buses=None):
    return template() | {
        "buses": [bus()] if buses is None else buses,
        "devices": [host(), device("iom")] if devices is None else devices,
        "links": [cable("host", "iom")] if links is None else links,
    }


def codes(result, severity=None):
    return {f["code"] for f in result["findings"] if severity is None or f["severity"] == severity}


def test_valid_declared_sa_chain_has_clean_address_graph_checks_without_electrical_approval():
    result = review(plan())
    assert not codes(result, "error")
    assert result["checks"] == {
        "address": "no-conflicts-in-declarations",
        "topology": "no-conflicts-in-declarations",
        "engineering": "incomplete",
    }
    assert "sa-host-only-termination" in codes(result, "info")
    assert (
        result["status"] == "incomplete"
        and not result["physical_wiring_verified"]
        and not result["field_operations"]
    )
    assert not result["operator_declarations_authenticated"]


def test_mac_scope_is_physical_bus_including_repeater_segments_not_site_global():
    value = plan()
    value["buses"].append(bus("bus-b"))
    value["devices"] += [host(bus_id="bus-b") | {"id": "host-b"}, device("iom-b", bus_id="bus-b")]
    value["links"].append(cable("host-b", "iom-b"))
    assert "duplicate-mac-on-bus" not in codes(review(value))
    value["buses"][0].update(kind="fc", segments=["s1", "s2"])
    value["devices"].append(device("duplicate", mac=4, segment="s2"))
    assert "duplicate-mac-on-bus" in codes(review(value), "error")
    value["devices"][-1]["role"] = "repeater-port"
    assert "duplicate-mac-on-bus" in codes(review(value), "error")


@pytest.mark.parametrize(
    "role,mac,model",
    [
        ("fit", 1, "Unknown FIT"),
        ("converter", 2, "TL-CWCVT-0"),
        ("display", 3, "Unknown display"),
        ("handheld-balancer", 198, "NS-ATV7003-0"),
    ],
)
def test_documented_tool_reserved_roles_are_not_assigned_to_ordinary_managers(role, mac, model):
    value = plan(
        [
            host(),
            device("tool", role, mac, model=model, generation=None, switch128="not-applicable"),
        ],
        [cable("host", "tool")],
    )
    assert not codes(review(value), "error")
    value["devices"][1].update(
        role="iom", model="FX-PCX3721-0", generation="legacy-dip128", switch128="off"
    )
    assert "manager-address-range" in codes(review(value), "error")


@pytest.mark.parametrize(
    "role,mac,code",
    [
        ("sa-host", 5, "sa-host-fixed-zero"),
        ("iom", 0, "manager-address-range"),
        ("converter", 3, "tool-display-reserved-address"),
        ("handheld-balancer", 199, "balancer-fixed-address"),
        ("network-sensor", 207, "sensor-model-address-range"),
        ("subordinate", 127, "sa-subordinate-range"),
        ("iom", 255, "broadcast-not-device"),
    ],
)
def test_bus_specific_role_and_range_errors(role, mac, code):
    node = sensor() if role == "network-sensor" else device("target", role, mac, model="Unknown")
    node.update(role=role, mac=mac)
    assert code in codes(review(plan([node], [], [bus()])), "error")


def test_sa_host_uses_zero_separately_from_upstream_controller_switches():
    node = host(switch128="on")
    result = review(plan([node], []))
    assert "wireless-switch-mode-conflict" not in codes(result)
    assert "sa-host-fixed-zero" not in codes(result)
    node.update(role="iom", model="FX-PCX3721-0")
    assert "model-role-conflict" not in codes(review(plan([node], [])))
    node["role"] = "sa-host"
    assert "model-role-conflict" in codes(review(plan([node], [])), "error")


def test_fc_subordinates_and_sa_downstream_field_controller_roles_are_distinct():
    assert "fc-subordinate-unsupported" in codes(
        review(plan([sensor()], [], [bus(kind="fc")])), "error"
    )
    node = device("ordinary-controller", role="field-controller", model="FX-PCV1630-0")
    assert "sa-endpoint-role-conflict" in codes(
        review(plan([host(), node], [cable("host", "ordinary-controller")])), "error"
    )
    node = host(role="fc-host", model="Unknown supervisor", mac=5)
    result = review(plan([node], [], [bus(kind="fc")]))
    assert "fc-host-nondefault-unverified" in codes(result, "unknown")
    assert "sa-host-fixed-zero" not in codes(result)


@pytest.mark.parametrize(
    "mode,switch,error",
    [
        ("wired", "off", False),
        ("wired", "on", True),
        ("wireless", "on", False),
        ("wireless", "off", True),
    ],
)
def test_legacy_switch128_selects_mode_without_adding_to_mac(mode, switch, error):
    node = device("legacy", mode=mode, switch128=switch, mac=21)
    result = review(plan([host(), node], [cable("host", "legacy")]))
    assert ("wireless-switch-mode-conflict" in codes(result, "error")) == error
    assert result["plan"]["devices"][1]["mac"] == 21
    if mode == "wireless":
        assert "wireless-topology-unverified" in codes(result, "unknown")


def test_unknown_suffix_generation_and_sensor_switches_are_never_legacy_mode_inferred():
    node = device("unknown", model="FX-PCV1630-99", switch128="on")
    result = review(plan([host(), node], [cable("host", "unknown")]))
    assert {"model-generation-unverified", "switch-interpretation-unverified"} <= codes(
        result, "unknown"
    )
    assert "wireless-switch-mode-conflict" not in codes(result)
    node.update(model="FX-PCV1630-0", generation=None)
    result = review(plan([host(), node], [cable("host", "unknown")]))
    assert "device-generation-unverified" in codes(result, "unknown")
    assert "wireless-switch-mode-conflict" not in codes(result)
    node = sensor(switch128="on")
    assert "wireless-switch-mode-conflict" not in codes(
        review(plan([host(), node], [cable("host", "sensor")]))
    )


@pytest.mark.parametrize(
    "number,context,code",
    [
        (4, "nce_integral", "nce-integral-address-reserved"),
        (120, "zfr1810_coordinators", "zfr1810-address-reserved"),
        (127, "zfr1810_coordinators", "zfr1810-address-reserved"),
    ],
)
def test_r15_conditional_reservations_do_not_expand_to_fx_or_unconfirmed_contexts(
    number, context, code
):
    node = device("manager", mac=number)
    b = bus(kind="fc", profile="metasys-r15") | {context: "present"}
    assert code in codes(review(plan([node], [], [b])), "error")
    b[context] = "unknown"
    assert code not in codes(review(plan([node], [], [b])), "error")
    assert any("context-unknown" in c for c in codes(review(plan([node], [], [b])), "unknown"))
    b.update(profile="fx-2024", **{context: "present"})
    assert code not in codes(review(plan([node], [], [b])))


def test_sa_single_host_single_segment_no_repeaters():
    value = plan()
    value["buses"][0]["segments"] = ["s1", "s2"]
    value["devices"].append(device("second-host", role="sa-host", model="FX-PCV1630-0", mac=0))
    assert {"sa-single-host", "sa-single-segment-no-repeaters"} <= codes(review(value), "error")
    value = plan(
        [host(), device("rp", role="repeater-port", model="Unknown repeater", mac=None)],
        [cable("host", "rp")],
    )
    assert "sa-single-segment-no-repeaters" in codes(review(value), "error")


@pytest.mark.parametrize(
    "edges,expected",
    [
        ([("host", "a"), ("host", "b"), ("host", "c")], "trunk-branch"),
        ([("host", "a"), ("a", "b"), ("b", "c"), ("c", "host")], "cyclic-plan"),
        ([("host", "a"), ("b", "c")], "disconnected-plan"),
    ],
)
def test_declared_graph_detects_branch_cycle_and_disconnection(edges, expected):
    nodes = [host(), device("a", mac=4), device("b", mac=5), device("c", mac=6)]
    result = review(plan(nodes, [cable(a, b) for a, b in edges]))
    assert expected in codes(result, "error")
    assert not result["physical_wiring_verified"]


def test_fc_eol_endpoints_differ_from_sa_host_only_acceptable_rule():
    nodes = [
        device("a", mac=5, eol="on"),
        device("b", mac=6, eol="off"),
        device("c", mac=7, eol="on"),
    ]
    value = plan(nodes, [cable("a", "b"), cable("b", "c")], [bus(kind="fc")])
    assert "fc-eol-position-conflict" not in codes(review(value))
    value["devices"][1]["eol"] = "on"
    assert "fc-eol-position-conflict" in codes(review(value), "error")
    value = plan()
    value["devices"][0]["eol"] = "off"
    assert "sa-host-eol-fixed-on" in codes(review(value), "error")


def service_plan(**sensor_changes):
    nodes = [
        host(),
        sensor(**sensor_changes),
        device("iom", mac=4),
        device(
            "tool",
            role="converter",
            mac=2,
            model="TL-CWCVT-0",
            generation=None,
            switch128="not-applicable",
        ),
    ]
    links = [
        cable("host", "sensor"),
        cable("sensor", "iom"),
        cable("sensor", "tool", kind="sensor-service", straight_through=True),
    ]
    return plan(nodes, links)


def test_exact_refreshed_sensor_service_leaf_is_not_false_trunk_branch_or_connector_mix():
    result = review(service_plan())
    assert "documented-sensor-service-leaf" in codes(result, "info")
    assert "trunk-branch" not in codes(result) and "sa-mixed-trunk-connectors" not in codes(result)
    assert not codes(result, "error")
    value = service_plan()
    value["links"][-1]["kind"] = "terminal"
    assert "trunk-branch" in codes(review(value), "error")


@pytest.mark.parametrize(
    "changes",
    [{"generation": None}, {"generation": "legacy-unconfirmed"}, {"model": "NSB8BTN240-UNKNOWN"}],
)
def test_unknown_sensor_generation_or_claimed_stub_stays_unresolved_without_blanket_branch_error(
    changes,
):
    value = service_plan(**changes)
    value["links"][-1].update(length_m=99, straight_through=False)
    result = review(value)
    assert "service-exception-unverified" in codes(result, "unknown")
    assert "documented-sensor-service-leaf" not in codes(result)
    assert "trunk-branch" not in codes(result) and "modular-cable-length" not in codes(result)


def test_sensor_service_daisy_chaining_and_ordinary_modular_chains_are_not_approved():
    value = service_plan()
    value["devices"].append(device("extra", mac=6))
    value["links"].append(cable("tool", "extra"))
    assert "service-port-daisy-chain" in codes(review(value), "error")
    value = plan(
        [
            host(),
            sensor(),
            device("tool", role="converter", mac=2, model="TL-CWCVT-0", generation=None),
        ],
        [
            cable("host", "sensor", kind="modular", straight_through=True),
            cable("sensor", "tool", kind="modular", straight_through=True),
        ],
    )
    assert "sa-modular-daisy-chain" in codes(review(value), "error")
    value["links"][0]["kind"] = "terminal"
    assert "sa-mixed-trunk-connectors" in codes(review(value), "error")


@pytest.mark.parametrize(
    "length,pinout,code",
    [
        (30.001, True, "modular-cable-length"),
        (1, False, "modular-crossover-invalid"),
        (None, None, "cable-length-unknown"),
    ],
)
def test_reviewed_six_pin_cable_bounds_and_unknowns(length, pinout, code):
    value = service_plan()
    value["links"][-1].update(length_m=length, straight_through=pinout)
    assert code in codes(review(value))


def test_sources_exact_revision_and_report_seals_preserve_original_declarations():
    value = plan()
    saved = copy.deepcopy(value)
    result = review(value)
    assert value == saved and result["plan"] == validate_plan(value).model_dump()
    assert result["plan_sha256"] == digest(result["plan"])
    assert result["content_sha256"] == digest(
        {k: v for k, v in result.items() if k != "content_sha256"}
    )
    assert CATALOG["sha256"] == digest({k: v for k, v in CATALOG.items() if k != "sha256"})
    assert CATALOG["sources"]["fx-2024"]["date"] == "2024-12-11"
    assert (
        CATALOG["sources"]["fx-2024"]["sha256"]
        == "30b55a915954c78a05ecea598ce1890494629ff78451660a2f440785774c2605"
    )
    assert "not PDF bytes" in CATALOG["sources"]["sensor-access"]["artifact"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(catalog_sha256="0" * 64),
        lambda d: d.update(version=True),
        lambda d: d.pop("format"),
        lambda d: d.update(extra=True),
        lambda d: d["devices"][1].update(mac=True),
        lambda d: d["devices"][1].update(mac=256),
        lambda d: d["devices"][1].update(mac=-1),
        lambda d: d["devices"][1].update(mac="4"),
        lambda d: d["devices"][1].update(bus_id="unknown-bus"),
        lambda d: d["devices"][1].update(segment="undeclared"),
        lambda d: d["buses"][0].update(inventory_complete=1),
        lambda d: d["buses"][0].update(segments=["s1", "s1"]),
        lambda d: d["links"][0].update(a="missing"),
        lambda d: d["links"][0].update(b="host"),
        lambda d: d["links"][0].update(length_m=float("inf")),
        lambda d: d["links"][0].update(length_m=-1),
        lambda d: d["links"][0].update(straight_through=1),
        lambda d: d["links"].append(copy.deepcopy(d["links"][0]) | {"id": "duplicate-pair"}),
        lambda d: d.update(notes="x" * 4001),
        lambda d: d["devices"].append(copy.deepcopy(d["devices"][0])),
    ],
)
def test_strict_schema_finite_identity_bounds_and_source_guards(mutate):
    value = plan()
    mutate(value)
    with pytest.raises(ValueError):
        validate_plan(value)


def test_all_bounded_collections_and_cross_bus_links():
    value = plan()
    value["buses"] = [bus(str(n)) for n in range(33)]
    with pytest.raises(ValueError):
        validate_plan(value)
    value = plan()
    value["devices"] = [device(str(n)) for n in range(257)]
    with pytest.raises(ValueError):
        validate_plan(value)
    value = plan()
    value["buses"].append(bus("other"))
    value["devices"][1]["bus_id"] = "other"
    with pytest.raises(ValueError):
        validate_plan(value)
    with pytest.raises(ValueError, match="2 MiB"):
        validate_plan(template() | {"notes": "x" * (2 * 1024 * 1024)})


def test_real_api_guards_and_portable_plan_reopen_without_field_actions(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        data = client.get("/api/bus-preflight/catalog").json()
        assert data["catalog"] == CATALOG
        value = service_plan()
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post("/api/bus-preflight/review", json={"plan": value}).status_code == 403
        normalized = client.post("/api/bus-preflight/validate", json={"plan": value}, headers=token)
        assert normalized.status_code == 200, normalized.text
        source = json.loads(json.dumps(normalized.json()["plan"]))
        result = client.post("/api/bus-preflight/review", json={"plan": source}, headers=token)
        assert result.status_code == 200, result.text
        assert result.json()["plan_sha256"] == normalized.json()["plan_sha256"]
        assert "documented-sensor-service-leaf" in codes(result.json())
        assert (
            client.post(
                "/api/bus-preflight/review", json={"plan": source, "apply": True}, headers=token
            ).status_code
            == 422
        )
        source["catalog_sha256"] = "0" * 64
        assert (
            client.post(
                "/api/bus-preflight/validate", json={"plan": source}, headers=token
            ).status_code
            == 422
        )
        assert not client.get("/api/bacnet/status").json()["connected"]


def test_fc_repeater_side_at_mid_segment_is_not_an_ordinary_trunk_branch():
    nodes = [
        device("a", mac=5, eol="on"),
        device("ra", role="repeater-port", mac=None, model="Unreviewed repeater", eol="off"),
        device("b", mac=6, eol="on"),
        device(
            "rb",
            role="repeater-port",
            mac=None,
            model="Unreviewed repeater",
            segment="s2",
            eol="on",
        ),
        device("c", mac=7, segment="s2", eol="on"),
    ]
    value = plan(
        nodes,
        [
            cable("a", "ra"),
            cable("ra", "b"),
            cable("ra", "rb", kind="repeater-bridge", length_m=None),
            cable("rb", "c"),
        ],
        [bus(kind="fc", segments=["s1", "s2"])],
    )
    result = review(value)
    assert "trunk-branch" not in codes(result) and "disconnected-plan" not in codes(result)
    assert "repeater-hardware-unverified" in codes(result, "unknown")
    assert not codes(result, "error")
    value["links"][2]["kind"] = "terminal"
    assert "cross-segment-cable" in codes(review(value), "error")


def test_unknown_bus_profile_never_approves_or_claims_release_specific_topology_failure():
    value = plan(buses=[bus(profile="unknown", segments=["s1", "s2"])])
    result = review(value)
    assert "bus-profile-unresolved" in codes(result, "unknown")
    assert "sa-single-segment-no-repeaters" in codes(result, "unknown")
    assert "sa-single-segment-no-repeaters" not in codes(result, "error")


def test_server_exports_preserve_integral_float_json_bytes_and_seals(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        value = service_plan()
        for endpoint in ("export-plan", "export-review"):
            assert (
                client.post("/api/bus-preflight/" + endpoint, json={"plan": value}).status_code
                == 403
            )
            response = client.post(
                "/api/bus-preflight/" + endpoint, json={"plan": value}, headers=token
            )
            assert response.status_code == 200
            assert b'"length_m":2.0' in response.content
            assert "attachment" in response.headers["content-disposition"]
            assert response.headers["content-type"].startswith("application/json")
            exported = json.loads(response.content)
            if endpoint == "export-review":
                assert exported["content_sha256"] == digest(
                    {key: item for key, item in exported.items() if key != "content_sha256"}
                )
                assert exported["plan_sha256"] == digest(exported["plan"])
            else:
                assert validate_plan(exported).model_dump() == validate_plan(value).model_dump()


def test_fx_conflicting_segment_counts_are_not_a_universal_metasys_limit():
    value = plan([device("a", mac=4)], [], [bus(kind="fc", segments=["s1", "s2", "s3", "s4"])])
    result = review(value)
    assert "fx-segment-limit-unresolved" in codes(result, "unknown")
    assert "fc-segment-count" not in codes(result)
    value["buses"][0]["profile"] = "metasys-r15"
    assert "fc-segment-count" in codes(review(value), "error")
