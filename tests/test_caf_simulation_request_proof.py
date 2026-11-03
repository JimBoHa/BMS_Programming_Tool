"""Request identity is independent of a source-qualified artifact's self-hash."""

import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_simulation import CafSimulationProfile, simulation_request_sha256
from fastapi.testclient import TestClient

from .test_caf_simulation import make_caf, pack


def golden():
    return {
        "format": "bms.caf-simulation-profile",
        "version": 2,
        "source_sha256": "a" * 64,
        "entries": [
            {"ref": 'é🙂/"\\', "property_id": "3113", "value": "\t\r\n/"},
            {"ref": "opaque", "property_id": "999", "value": None},
            {"ref": "input", "property_id": "3113", "value": "-0.0"},
        ],
    }


def test_literal_compact_utf8_vector_preserves_unicode_escaping_nulls_and_signed_text():
    # Independent literal bytes: no production canonicalizer creates this oracle.
    literal = (
        '{"entries":[{"property_id":"3113","ref":"é🙂/\\"\\\\","value":"\\t\\r\\n/"},'
        '{"property_id":"999","ref":"opaque","value":null},'
        '{"property_id":"3113","ref":"input","value":"-0.0"}],'
        '"format":"bms.caf-simulation-profile","source_sha256":"' + "a" * 64 + '","version":2}'
    )
    parsed = json.loads(literal)
    assert parsed["entries"] == [
        {"property_id": row["property_id"], "ref": row["ref"], "value": row["value"]}
        for row in golden()["entries"]
    ]
    assert simulation_request_sha256(golden()) == hashlib.sha256(literal.encode()).hexdigest()


@pytest.mark.parametrize(
    "fault",
    [
        "format",
        "source",
        "version",
        "bool-version",
        "entries",
        "row",
        "ref",
        "property",
        "value",
        "missing-value",
        "surrogate",
        "large",
        "count",
        "extra",
    ],
)
def test_descriptor_refuses_coercions_ambiguous_unicode_and_resource_overflow(fault):
    profile = golden()
    if fault == "format":
        profile["format"] += "/unknown"
    elif fault == "source":
        profile["source_sha256"] = "A" * 64
    elif fault == "version":
        profile["version"] = "2"
    elif fault == "bool-version":
        profile["version"] = True
    elif fault == "entries":
        profile["entries"] = {}
    elif fault == "row":
        profile["entries"][0] = []
    elif fault == "ref":
        profile["entries"][0]["ref"] = 123
    elif fault == "property":
        profile["entries"][0]["property_id"] = None
    elif fault == "value":
        profile["entries"][0]["value"] = False
    elif fault == "missing-value":
        profile["entries"][0].pop("value")
    elif fault == "surrogate":
        profile["entries"][0]["value"] = "\ud800"
    elif fault == "large":
        profile["entries"][0]["value"] = "x" * (2 * 1024 * 1024)
    elif fault == "count":
        profile["entries"] *= 3334
    else:
        profile["can_apply"] = True
    with pytest.raises(ValueError):
        simulation_request_sha256(profile)


def test_order_source_version_and_exact_raw_spelling_are_distinct_requests():
    profile = golden()
    seen = {simulation_request_sha256(profile)}
    for mutate in [
        lambda p: p["entries"].reverse(),
        lambda p: p.update(version=1),
        lambda p: p.update(source_sha256="b" * 64),
        lambda p: p["entries"][2].update(value="0.0"),
        lambda p: p["entries"][0].update(ref='é🙂/"\\'),
    ]:
        changed = copy.deepcopy(profile)
        mutate(changed)
        seen.add(simulation_request_sha256(changed))
    assert len(seen) == 6
    for row in profile["entries"]:
        row["display_metadata"] = "Not value or identity authority"
    assert simulation_request_sha256(profile) in seen


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("kind", ["noop", "mixed", "reordered", "empty", "unicode"])
def test_local_api_binds_validated_complete_ordered_profile_without_weakening_native_guards(
    tmp_path, version, kind
):
    raw = make_caf()
    if kind == "empty":
        raw = pack(f'<objects xmlns="{NS}"/>'.encode())
    if kind == "unicode":
        raw = pack(CafArchive(raw).xml.replace(b"8-1/526_1", "é🙂/526_1".encode()))
    with TestClient(create_app(tmp_path)) as client:
        token = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        sha = client.post("/api/caf", headers=token, files={"file": ("authored.caf", raw)}).json()[
            "sha256"
        ]
        profile = CafSimulationProfile(raw, profile_version=version).export_profile()
        if kind in ("mixed", "unicode"):
            profile["entries"][0]["value"] = "+7.25e1"
            profile["entries"][2]["value"] = "true"
            if version == 2:
                profile["entries"][3]["value"] = "65536"
        if kind == "reordered":
            profile["entries"].reverse()
        descriptor = {
            "entries": [
                {"property_id": r["property_id"], "ref": r["ref"], "value": r["value"]}
                for r in profile["entries"]
            ],
            "format": profile["format"],
            "source_sha256": sha,
            "version": version,
        }
        expected = hashlib.sha256(
            json.dumps(descriptor, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        base = f"/api/caf/{sha}/simulation"
        missing = client.post(base, json={"profile": profile})
        assert (
            missing.status_code == 403
            and "X-Studio-Simulation-Request-Sha256" not in missing.headers
        )
        response = client.post(base, headers=token, json={"profile": profile})
        assert response.status_code == 200, response.text
        assert (
            response.headers["X-Studio-Simulation-Request-Sha256"]
            == expected
            == simulation_request_sha256(profile)
        )
        assert (
            response.headers["X-Studio-Artifact-Sha256"]
            == hashlib.sha256(response.content).hexdigest()
        )
        assert response.headers["X-Studio-Source-Sha256"] == sha and response.headers[
            "X-Studio-Simulation-Version"
        ] == str(version)
        if kind in ("noop", "reordered", "empty"):
            assert response.content == raw
        if profile["entries"]:
            bad = copy.deepcopy(profile)
            bad["entries"][0]["class_id"] = "unknown"
            refused = client.post(base, headers=token, json={"profile": bad})
            assert (
                refused.status_code == 422
                and "X-Studio-Simulation-Request-Sha256" not in refused.headers
            )
        assert not client.get("/api/session").json()["field_network_open"]
