"""Fresh inverse transfer binds immutable parent proof and preserves original writer gates."""

from unittest.mock import AsyncMock

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import seal
from bms_tool.native_binary_terminal_recovery_transfer import (
    KEYS,
    PROFILE,
    BinaryTerminalRecoveryPreview,
    recovery_origin,
    validate_plan,
)
from bms_tool.native_inputs import InputPreview, NativeInputCompiler
from fastapi.testclient import TestClient

from .test_native_binary_terminal_recovery import setup
from .test_native_inputs import config


def prepared(tmp_path):
    app = create_app(tmp_path)
    _, recovery, request, _, files, _ = setup(tmp_path)
    draft = recovery.prepare(request)
    options = BinaryTerminalRecoveryPreview(
        **draft["source"]["target"],
        operation_id="review-terminal-inverse",
        capture_id=request["capture_id"],
        snapshot_sha256=request["snapshot_sha256"],
        edit=draft["proposal"]["edit"],
        binary_terminal_recovery_parent_receipt=request["receipt_id"],
        binary_terminal_recovery_origin_sha256=draft["origin_sha256"],
    )
    _, compilation = NativeInputCompiler(files).compile(options.edit)
    return app.state.native_applications, options, compilation, draft


def test_local_origin_derivation_binds_exact_proposal_target_and_current_compilation(tmp_path):
    service, options, compilation, draft = prepared(tmp_path)
    lineage = recovery_origin(service, options, compilation)
    assert set(lineage) == KEYS
    assert (
        lineage["binary_terminal_recovery_profile"] == PROFILE
        and lineage["binary_terminal_recovery_lineage_enforced"]
    )
    assert lineage["binary_terminal_recovery_origin"] == draft["origin"]
    validate_plan(
        {"operation_profile": "native-local-universal-input-transfer/3", **lineage}, options
    )
    assert not service.plans
    normal = InputPreview(
        **options.model_dump(
            exclude={
                "binary_terminal_recovery_parent_receipt",
                "binary_terminal_recovery_origin_sha256",
            }
        )
    )
    assert recovery_origin(service, normal, compilation) == {}
    validate_plan({"operation_profile": "native-local-universal-input-transfer/3"}, normal)


@pytest.mark.parametrize(
    "fault",
    [
        "origin",
        "parent",
        "route",
        "edit",
        "object",
        "ref",
        "old-slot",
        "destination",
        "compiler",
        "input-edit",
        "configuration",
        "counter-keys",
        "counter-type",
        "counter-range",
        "compilation-shape",
        "terminal-shape",
        "guard",
    ],
)
def test_substituted_proposals_or_compilations_refuse_local_origin(tmp_path, fault):
    service, options, compilation, _ = prepared(tmp_path)
    if fault == "origin":
        options.binary_terminal_recovery_origin_sha256 = "0" * 64
    elif fault == "parent":
        options.binary_terminal_recovery_parent_receipt = "0" * 32
    elif fault == "route":
        options.address = "127.0.0.2:47819"
    elif fault == "edit":
        options.edit.slot = 2
    elif fault == "object":
        compilation["object_id"] = "binary-input,999"
    elif fault == "ref":
        compilation["record_ref"] = "other/0_101"
    elif fault == "old-slot":
        compilation["terminal_compilation"]["old_slot"] = 1
    elif fault == "destination":
        compilation["terminal_compilation"]["destination_slot"] = True
    elif fault == "compiler":
        compilation["terminal_compilation"]["profile"] = "tagged-moi-local-terminal-copy/1"
    elif fault == "input-edit":
        compilation["input_edit"]["slot"] = 2
    elif fault == "configuration":
        compilation["stored_configuration"]["polarity"] = 0
    elif fault == "counter-keys":
        compilation["captured_counter_values"].pop("15")
    elif fault == "counter-type":
        compilation["captured_counter_values"]["15"] = True
    elif fault == "counter-range":
        compilation["captured_counter_values"]["15"] = 4294967296
    elif fault == "compilation-shape":
        compilation = None
    elif fault == "terminal-shape":
        compilation["terminal_compilation"] = None
    elif fault == "guard":
        compilation["configuration_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        recovery_origin(service, options, compilation)


@pytest.mark.parametrize("key", sorted(KEYS))
def test_removed_lineage_cannot_demote_a_recovery_plan(tmp_path, key):
    service, options, compilation, _ = prepared(tmp_path)
    body = {
        "operation_profile": "native-local-universal-input-transfer/3",
        **recovery_origin(service, options, compilation),
    }
    del body[key]
    with pytest.raises(ValueError):
        validate_plan(body, options)


def test_ordinary_options_cannot_accept_recovery_metadata_and_recovery_options_require_it(tmp_path):
    service, options, compilation, _ = prepared(tmp_path)
    body = {
        "operation_profile": "native-local-universal-input-transfer/3",
        **recovery_origin(service, options, compilation),
    }
    normal = InputPreview(
        **options.model_dump(
            exclude={
                "binary_terminal_recovery_parent_receipt",
                "binary_terminal_recovery_origin_sha256",
            }
        )
    )
    with pytest.raises(ValueError):
        validate_plan(body, normal)
    with pytest.raises(ValueError):
        validate_plan({"operation_profile": body["operation_profile"]}, options)
    body["binary_terminal_recovery_profile"] = "unknown"
    with pytest.raises(ValueError):
        validate_plan(body, options)


@pytest.mark.parametrize(
    "kind", ["allocate", "mode", "remove-allocated", "terminal", "encoded-terminal"]
)
def test_recovery_preview_model_accepts_only_a_strict_terminal_action(tmp_path, kind):
    _, options, _, _ = prepared(tmp_path)
    data = options.model_dump()
    data["edit"]["action"] = kind
    if kind == "allocate":
        data["edit"].update(configuration=config(), name="New input", configuration_sha256=None)
    elif kind == "mode":
        data["edit"]["configuration"] = config()
    elif kind == "remove-allocated":
        data["edit"]["allocation_receipt"] = "a" * 32
    InputPreview.model_validate(
        {
            k: v
            for k, v in data.items()
            if k
            not in {
                "binary_terminal_recovery_parent_receipt",
                "binary_terminal_recovery_origin_sha256",
            }
        }
    )
    with pytest.raises(ValueError, match="exact derived terminal edit"):
        BinaryTerminalRecoveryPreview.model_validate(data)


def test_recovery_origin_hash_is_not_only_a_label(tmp_path):
    service, options, compilation, _ = prepared(tmp_path)
    body = {
        "operation_profile": "native-local-universal-input-transfer/3",
        **recovery_origin(service, options, compilation),
    }
    body["binary_terminal_recovery_origin"]["previous_slot"] = 2
    assert (
        seal(body["binary_terminal_recovery_origin"])
        != options.binary_terminal_recovery_origin_sha256
    )
    with pytest.raises(ValueError):
        validate_plan(body, options)


def test_explicit_http_review_keeps_session_schema_and_typed_dispatch(tmp_path, monkeypatch):
    _, options, _, _ = prepared(tmp_path)
    app = create_app(tmp_path)
    dispatch = AsyncMock(return_value={"schema_dispatch_only": True})
    monkeypatch.setattr(app.state.native_applications, "preview_binary_terminal_recovery", dispatch)
    endpoint = "/api/bacnet/controller/native-application/input/binary-terminal/recovery/preview"
    with TestClient(app) as client:
        body = options.model_dump()
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(endpoint, json=body).status_code == 403
        for change in [
            {"can_apply": True},
            {"token": "A" * 32},
            {"binary_terminal_recovery_parent_receipt": True},
            {"binary_terminal_recovery_origin_sha256": "bad"},
        ]:
            assert client.post(endpoint, headers=headers, json=body | change).status_code == 422
        dispatch.assert_not_awaited()
        response = client.post(endpoint, headers=headers, json=body)
        assert response.status_code == 200 and response.json() == {"schema_dispatch_only": True}
        dispatch.assert_awaited_once_with(**body)
        assert not client.get("/api/session").json()["field_network_open"]


def test_fresh_counter_values_do_not_rebind_configuration_or_origin(tmp_path):
    service, options, compilation, draft = prepared(tmp_path)
    compilation["captured_counter_values"] = {"15": 4294967295, "33": 0}
    lineage = recovery_origin(service, options, compilation)
    assert lineage["binary_terminal_recovery_origin_sha256"] == draft["origin_sha256"]
    assert lineage["binary_terminal_recovery_origin"] == draft["origin"]


@pytest.mark.parametrize("counter", [-1, 4294967296, 1.0, True, None, "77"])
def test_fresh_counter_map_requires_exact_unsigned32_values(tmp_path, counter):
    service, options, compilation, _ = prepared(tmp_path)
    compilation["captured_counter_values"]["15"] = counter
    with pytest.raises(ValueError):
        recovery_origin(service, options, compilation)


@pytest.mark.parametrize(
    "lineage",
    [
        {"recovery_parent_receipt": "a" * 32, "recovery_origin_sha256": "b" * 64},
        {
            "encoded_analog_recovery_parent_receipt": "a" * 32,
            "encoded_analog_recovery_origin_sha256": "b" * 64,
        },
    ],
)
def test_http_preview_refuses_other_recovery_namespaces(tmp_path, lineage):
    _, options, _, _ = prepared(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/controller/native-application/input/binary-terminal/recovery/preview",
                headers=headers,
                json=options.model_dump() | lineage,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/bacnet/controller/native-application/input/preview",
                headers=headers,
                json=options.model_dump(),
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
