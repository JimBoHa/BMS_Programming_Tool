"""Source inspection must not promote metadata or model names into write support."""

import hashlib

import pytest
from bms_tool.application_capabilities import operation_capabilities
from bms_tool.moi_application import MoiApplication

from .test_controller_application import authored_application
from .test_moi_identity import source
from .test_native_signal_compiler import signal_files


def captured(data, *, vendor=5, model="UNLISTED-CONTROLLER", config=None, **identity):
    receipt = {
        "id": "a" * 32,
        "sha256": hashlib.sha256(data).hexdigest(),
        "received_at": "2026-01-05T12:00:00Z",
        "target": {"address": "127.0.0.1:49291", "device": "device,5136", "object_id": "file,31"},
        "connector_config": config or {"local_address": "127.0.0.1:49290"},
        "device_identity": {
            "object-identifier": "device,5136",
            "object-name": "Authored controller",
            "vendor-identifier": vendor,
            "model-name": model,
            "firmware-revision": "observed-firmware",
            **identity,
        },
    }
    return operation_capabilities(receipt, data, MoiApplication(data).summary())


def row(report, key):
    return next(item for item in report["operations"] if item["id"] == key)


@pytest.mark.parametrize("model", ["UNLISTED-CONTROLLER", "UNLISTED-OTHER"])
@pytest.mark.parametrize("compressed", [False, True])
def test_source_recognition_credits_narrow_compiler_without_model_inventory(model, compressed):
    report = captured(source(model=model, compressed=compressed), model=model)
    assert row(report, "identity-compile")["status"] == "source-qualified"
    assert row(report, "name-compile")["status"] == "source-qualified"
    assert row(report, "identity-transfer")["status"] == "preflight-required"
    assert report["native_identity_matches_capture"]
    assert report["native_identity"]["format_versions"] == {"acs": 62, "dmcs": 62}
    assert not report["can_apply"] and not report["field_actions"]
    assert row(report, "general-logic")["status"] == "unavailable"
    assert row(report, "release-packages")["status"] == "not-evaluated"
    assert row(report, "physical-acceptance")["status"] == "not-inferred"


def test_readable_diagram_does_not_establish_identity_compiler_support():
    report = captured(authored_application())
    assert row(report, "diagram-read")["status"] == "source-qualified"
    assert row(report, "identity-compile")["status"] == "unsupported-source"
    assert row(report, "identity-transfer")["status"] == "unsupported-source"
    assert report["native_identity"] is None


@pytest.mark.parametrize(
    "identity",
    [
        {"object-identifier": "device,5137"},
        {"object-name": "Other controller"},
        {"model-name": "OTHER-MODEL"},
    ],
)
def test_native_root_must_match_actual_captured_identity_before_connected_qualification(identity):
    report = captured(source(), **identity)
    assert row(report, "identity-compile")["status"] == "source-qualified"
    assert row(report, "identity-transfer")["status"] == "source-mismatch"
    assert not report["native_identity_matches_capture"]


@pytest.mark.parametrize(
    "config",
    [
        {"transport": "mstp", "port": "authored-pseudoterminal"},
        {"local_address": "127.0.0.1:49290", "bbmd_address": "127.0.0.1:49292"},
    ],
)
def test_an_acquired_file_does_not_establish_native_transfer_over_another_transport(config):
    report = captured(source(), config=config)
    assert row(report, "file-read")["status"] == "observed"
    assert row(report, "identity-compile")["status"] == "source-qualified"
    assert row(report, "identity-transfer")["status"] == "transport-unavailable"


def test_vendor_identity_is_not_inferred_from_a_readable_moi_file():
    report = captured(source(), vendor=999)
    assert row(report, "identity-compile")["status"] == "source-qualified"
    assert row(report, "identity-transfer")["status"] == "protocol-unconfirmed"


@pytest.mark.parametrize("compressed", [False, True])
def test_actual_real_fields_credit_local_copy_but_never_invent_native_saved_settings(compressed):
    report = captured(signal_files(compressed=compressed)[3], model="UNLISTED-MODEL")
    assert row(report, "signal-default-copy")["status"] == "source-qualified"
    assert "2 recognized" in row(report, "signal-default-copy")["basis"]
    assert row(report, "effective-default-compile")["status"] == "native-backup-required"
    assert row(report, "default-transfer")["status"] == "preflight-required"
    assert not report["can_apply"] and not report["field_actions"]


@pytest.mark.parametrize("profile", ["mstp", "bbmd", "vendor", "mismatch"])
def test_default_capabilities_keep_offline_compilation_and_field_preflight_independent(profile):
    options = {"model": "UNLISTED-MODEL"}
    if profile == "mstp":
        options["config"] = {"transport": "mstp", "port": "authored-port"}
    elif profile == "bbmd":
        options["config"] = {"local_address": "127.0.0.1:49290", "bbmd_address": "127.0.0.1:49292"}
    elif profile == "vendor":
        options["vendor"] = 999
    else:
        options["object-name"] = "Other controller"
    report = captured(signal_files()[3], **options)
    assert row(report, "signal-default-copy")["status"] == "source-qualified"
    assert row(report, "effective-default-compile")["status"] == (
        {"vendor": "protocol-unconfirmed", "mismatch": "source-mismatch"}.get(
            profile, "native-backup-required"
        )
    )
    assert row(report, "default-transfer")["status"] == (
        {"vendor": "protocol-unconfirmed", "mismatch": "source-mismatch"}.get(
            profile, "transport-unavailable"
        )
    )
    assert not report["can_apply"] and not report["field_actions"]


def test_identity_source_without_real_defaults_does_not_gain_default_authoring_by_model():
    report = captured(source())
    for key in ("signal-default-copy", "effective-default-compile", "default-transfer"):
        assert row(report, key)["status"] == "unsupported-source"
