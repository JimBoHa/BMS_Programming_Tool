"""Encoding-preserving typed analog moves use exact bytes and preserve absent endpoints."""

import pytest
from bacpypes3.primitivedata import Enumerated, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_encoded_terminal_input import (
    PROFILE,
    EncodedAnalogTerminalCompiler,
    validate_evidence,
)
from bms_tool.native_inputs import (
    NativeInputCompiler,
    archive,
    input_operation_profile,
    replace_properties,
    verify_input_preservation,
)
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_native_connection_copies import filesystem
from .test_native_signal_compiler import slot
from .test_native_terminal_copies import literal_effective, setup
from .test_native_terminal_input import terminal_edit
from .test_native_terminal_labels import literal, observed_shape


def nonlinear(files):
    app = MoiIdentity(files[3])
    rows = []
    for record in app.records:
        if app.reader.scalar(record, 32527) == "controller/0_101":
            rows.append(
                native_record(
                    240,
                    101,
                    [
                        (pid, app.data[v["value_start_offset"] : v["value_end_offset"] - 1])
                        for pid, v in record["properties"].items()
                        if pid not in (1295, 1296)
                    ],
                )
            )
        else:
            rows.append(app.data[record["offset"] : record["end_offset"]])
    return {**files, 3: archive(app, rows)}


def edit(compiler, **changes):
    return terminal_edit(compiler) | {"action": "encoded-terminal", **changes}


def replaced(files, values):
    app = MoiIdentity(files[3])
    selected = next(r for r in app.records if app.reader.scalar(r, 32527) == "controller/0_101")
    return {
        **files,
        3: archive(
            app,
            [
                replace_properties(app, r, values)
                if r is selected
                else app.data[r["offset"] : r["end_offset"]]
                for r in app.records
            ],
        ),
    }


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_exact_literal_image_typed_scaling_and_absence_profile(encoding, compressed, missing):
    files = observed_shape(binary=False, encoding=encoding, compressed=compressed)
    if missing:
        files = nonlinear(files)
    c = NativeInputCompiler(files)
    request = edit(c)
    output, report = c.compile(request)
    assert report["profile"] == input_operation_profile(request) == PROFILE
    assert MoiIdentity(output).data == literal(
        literal_effective(MoiIdentity(files[3]).data), binary=False, encoding=encoding
    )
    assert report["stored_configuration"] == c.source()["inputs"][0]["configuration"]
    assert report["configuration_storage"]["linear_output_endpoints_present"] is not missing
    assert report["terminal_compilation"]["profile"] == "tagged-moi-local-terminal-copy/3"
    assert report["terminal_compilation"]["device_type_character_encoding"] == encoding
    if missing:
        assert (
            report["stored_configuration"]["output_low"] is None
            and report["stored_configuration"]["output_high"] is None
        )
    proof = verify_input_preservation(files, {**files, 3: output}, request)
    assert proof["profile"] == PROFILE and proof["other_configuration_preserved"]
    source = EncodedAnalogTerminalCompiler(c).source()
    assert not source["controller_queries"] and not source["field_transfer_enabled"]
    assert source["inputs"][0]["configuration_error"] is None
    validate_evidence(
        {
            "operation_profile": PROFILE,
            "input_edit": request,
            "compilation": report,
            "payload_sha256": sha(output),
        }
    )
    if encoding == 4:
        with pytest.raises(ValueError):
            c.compile(terminal_edit(c))


@pytest.mark.parametrize(
    "pid,value",
    [(518, Real(1)), (69, Unsigned(0)), (65, Real(float("inf"))), (1293, Enumerated(0))],
    ids=["enum-as-real", "real-as-unsigned", "nonfinite", "endpoint-enum"],
)
def test_unknown_configuration_type_has_no_qualified_move(pid, value):
    files = replaced(observed_shape(binary=False), {pid: encoded(value)})
    c = NativeInputCompiler(files)
    row = EncodedAnalogTerminalCompiler(c).source()["inputs"][0]
    assert row["configuration_error"] and row["configuration_sha256"] is None
    with pytest.raises(ValueError):
        c.compile(edit(c))


@pytest.mark.parametrize(
    "change",
    [
        {"action": "terminal"},
        {"slot": True},
        {"slot": 3.0},
        {"slot": 1},
        {"slot": 4},
        {"configuration_sha256": "0" * 64},
        {"name": "replacement"},
        {"allocation_receipt": "a" * 32},
    ],
)
def test_old_action_noop_stale_or_additional_authority_is_refused(change):
    c = NativeInputCompiler(observed_shape(binary=False))
    with pytest.raises(ValueError):
        c.compile(edit(c, **change))


def test_saved_binding_override_is_refused_before_field_review():
    files = observed_shape(binary=False)
    payload = (1).to_bytes(4, "big")
    files = {
        3: files[3],
        11: files[11] + slot(101, 240, 519, 2, len(files[12])),
        12: files[12] + payload + bytes([header_crc(payload) ^ 255]),
    }
    c = NativeInputCompiler(files)
    with pytest.raises(ValueError, match="saved settings would override"):
        c.compile(edit(c))


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "action",
        "compiler",
        "seal",
        "charset",
        "configuration-type",
        "real32",
        "presence",
    ],
)
def test_evidence_requires_exact_profile_pairing_and_typed_configuration(fault):
    c = NativeInputCompiler(observed_shape(binary=False))
    request = edit(c)
    out, report = c.compile(request)
    body = {
        "operation_profile": PROFILE,
        "input_edit": request,
        "compilation": report,
        "payload_sha256": sha(out),
    }
    if fault == "profile":
        report["profile"] = "native-local-universal-input-transfer/2"
    if fault == "action":
        body["input_edit"]["action"] = "terminal"
    if fault == "compiler":
        report["terminal_compilation"]["profile"] = "tagged-moi-local-terminal-copy/2"
    if fault == "seal":
        report["terminal_compilation"]["compilation_sha256"] = "0" * 64
    if fault == "charset":
        report["terminal_compilation"]["device_type_character_encoding"] = False
    if fault == "configuration-type":
        report["stored_configuration"]["setup"] = True
    if fault == "real32":
        report["stored_configuration"]["minimum"] = 0.1
    if fault == "presence":
        report["configuration_storage"]["present_properties"] = [True]
    with pytest.raises(ValueError):
        validate_evidence(body)


def test_local_source_copy_export_stays_disconnected_and_identity_bound(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    storage, _, files, query = setup(tmp_path, files=nonlinear(observed_shape(binary=False)))
    request = {k: query[k] for k in ("capture_id", "snapshot_sha256")}
    before = filesystem(storage.directory)

    def forbidden(*a, **k):
        pytest.fail("Local encoded analog operation accessed the field")

    for name in ("require", "connect", "disconnect", "release", "_read"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        route = "/api/bacnet/controller/native-application/input/encoded-terminal/source"
        assert client.post(route, json=request).status_code == 403
        source = client.post(route, json=request, headers=headers)
        assert source.status_code == 200, source.text
        assert source.json()["profile"] == PROFILE
        c = NativeInputCompiler(files)
        body = request | {"edit": edit(c)}
        preview = client.post(
            "/api/bacnet/controller/native-application/input/copy/preview",
            json=body,
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        value = preview.json()
        assert value["profile"] == PROFILE
        output = client.post(
            "/api/bacnet/controller/native-application/input/copy/export",
            json=body | {"expected_review_sha256": value["review_sha256"]},
            headers=headers,
        )
        assert output.status_code == 200 and sha(output.content) == value["output_sha256"]
        assert not client.get("/api/session").json()["field_network_open"]
    assert filesystem(storage.directory) == before and not app.state.native_applications.plans
