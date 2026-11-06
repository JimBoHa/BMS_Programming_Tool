"""Parent-bound analog terminal recovery through the existing profile-4 writer."""

from pydantic import Field, model_validator

from .moi_identity import seal
from .native_backup_records import NativeBackupRecords
from .native_encoded_analog_recovery import NativeEncodedAnalogRecovery
from .native_encoded_terminal_input import PROFILE as TERMINAL_PROFILE
from .native_inputs import InputPreview

PROFILE = "native-encoded-analog-terminal-recovery-transfer/1"
KEYS = {
    "encoded_analog_recovery_profile",
    "encoded_analog_recovery_parent_receipt",
    "encoded_analog_recovery_origin",
    "encoded_analog_recovery_origin_sha256",
    "encoded_analog_recovery_lineage_enforced",
}


class EncodedAnalogRecoveryPreview(InputPreview):
    encoded_analog_recovery_parent_receipt: str = Field(pattern=r"^[a-f0-9]{32}$")
    encoded_analog_recovery_origin_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def terminal_only(self):
        if self.edit.action != "encoded-terminal":
            raise ValueError("A terminal recovery review requires its exact derived terminal edit.")
        return self


def recovery_origin(service, options, compilation):
    if not isinstance(options, EncodedAnalogRecoveryPreview):
        return {}
    prepared = NativeEncodedAnalogRecovery(NativeBackupRecords(service.storage)).prepare(
        {
            "receipt_id": options.encoded_analog_recovery_parent_receipt,
            "capture_id": options.capture_id,
            "snapshot_sha256": options.snapshot_sha256,
        }
    )
    proposal, origin = prepared["proposal"], prepared["origin"]
    selected = compilation.get("terminal_compilation", {})
    if (
        proposal is None
        or prepared["already_recorded"]
        or prepared["origin_sha256"] != options.encoded_analog_recovery_origin_sha256
        or seal(prepared["source"]["target"])
        != seal({**service.target(options), "device": options.device})
        or seal(proposal["edit"]) != seal(options.edit.model_dump())
        or compilation.get("profile") != TERMINAL_PROFILE
        or seal(compilation.get("input_edit")) != seal(proposal["edit"])
        or compilation.get("configuration_sha256") != origin["current_configuration_sha256"]
        or seal(compilation.get("stored_configuration"))
        != seal(prepared["inverse_compilation"]["stored_configuration"])
        or seal(compilation.get("configuration_storage"))
        != seal(prepared["inverse_compilation"]["configuration_storage"])
        or compilation.get("object_id") != origin["object_id"]
        or compilation.get("record_ref") != origin["record_ref"]
        or selected.get("profile") != "tagged-moi-local-terminal-copy/3"
        or seal([selected.get("old_slot"), selected.get("destination_slot")])
        != seal([origin["current_slot"], origin["previous_slot"]])
    ):
        raise ValueError("The fresh terminal edit differs from its verified recovery origin.")
    return {
        "encoded_analog_recovery_profile": PROFILE,
        "encoded_analog_recovery_parent_receipt": options.encoded_analog_recovery_parent_receipt,
        "encoded_analog_recovery_origin": origin,
        "encoded_analog_recovery_origin_sha256": prepared["origin_sha256"],
        "encoded_analog_recovery_lineage_enforced": True,
    }


def validate_plan(body, options):
    present = KEYS.intersection(body)
    if not present and not isinstance(options, EncodedAnalogRecoveryPreview):
        return
    if (
        present != KEYS
        or not isinstance(options, EncodedAnalogRecoveryPreview)
        or body.get("operation_profile") != TERMINAL_PROFILE
        or body.get("encoded_analog_recovery_profile") != PROFILE
        or body.get("encoded_analog_recovery_lineage_enforced") is not True
        or type(body.get("encoded_analog_recovery_origin")) is not dict
        or body.get("encoded_analog_recovery_parent_receipt")
        != options.encoded_analog_recovery_parent_receipt
        or body.get("encoded_analog_recovery_origin_sha256")
        != options.encoded_analog_recovery_origin_sha256
        or seal(body.get("encoded_analog_recovery_origin"))
        != options.encoded_analog_recovery_origin_sha256
        or body.get("encoded_analog_recovery_origin", {}).get("parent_receipt_id")
        != options.encoded_analog_recovery_parent_receipt
    ):
        raise ValueError(
            "Terminal recovery lineage changed or was removed; prepare and review again."
        )
