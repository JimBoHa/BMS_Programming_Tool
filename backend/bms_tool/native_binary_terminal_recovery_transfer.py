"""Parent-bound binary terminal recovery through the existing profile-3 writer."""

from pydantic import Field, model_validator

from .moi_identity import seal
from .native_backup_records import NativeBackupRecords
from .native_binary_terminal import PROFILE as TERMINAL_PROFILE
from .native_binary_terminal_recovery import NativeBinaryTerminalRecovery
from .native_inputs import InputPreview

PROFILE = "native-binary-terminal-recovery-transfer/1"
KEYS = {
    "binary_terminal_recovery_profile",
    "binary_terminal_recovery_parent_receipt",
    "binary_terminal_recovery_origin",
    "binary_terminal_recovery_origin_sha256",
    "binary_terminal_recovery_lineage_enforced",
}


class BinaryTerminalRecoveryPreview(InputPreview):
    binary_terminal_recovery_parent_receipt: str = Field(pattern=r"^[a-f0-9]{32}$")
    binary_terminal_recovery_origin_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def terminal_only(self):
        if self.edit.action != "binary-terminal":
            raise ValueError("A terminal recovery review requires its exact derived terminal edit.")
        return self


def recovery_origin(service, options, compilation):
    if not isinstance(options, BinaryTerminalRecoveryPreview):
        return {}
    prepared = NativeBinaryTerminalRecovery(NativeBackupRecords(service.storage)).prepare(
        {
            "receipt_id": options.binary_terminal_recovery_parent_receipt,
            "capture_id": options.capture_id,
            "snapshot_sha256": options.snapshot_sha256,
        }
    )
    proposal, origin = prepared["proposal"], prepared["origin"]
    if type(compilation) is not dict or type(compilation.get("terminal_compilation")) is not dict:
        raise ValueError("The fresh binary terminal compilation is unavailable.")
    selected = compilation["terminal_compilation"]
    counters = compilation.get("captured_counter_values")
    if (
        proposal is None
        or prepared["already_recorded"]
        or prepared["origin_sha256"] != options.binary_terminal_recovery_origin_sha256
        or seal(prepared["source"]["target"])
        != seal({**service.target(options), "device": options.device})
        or seal(proposal["edit"]) != seal(options.edit.model_dump())
        or compilation.get("profile") != TERMINAL_PROFILE
        or seal(compilation.get("input_edit")) != seal(proposal["edit"])
        or compilation.get("configuration_sha256") != origin["current_configuration_sha256"]
        or seal(compilation.get("stored_configuration"))
        != seal(prepared["inverse_compilation"]["stored_configuration"])
        # Counter values are fresh runtime observations, not the electrical configuration.
        or type(counters) is not dict
        or counters.keys() != prepared["inverse_compilation"]["captured_counter_values"].keys()
        or any(
            type(value) is not int or not 0 <= value <= 4294967295 for value in counters.values()
        )
        or compilation.get("object_id") != origin["object_id"]
        or compilation.get("record_ref") != origin["record_ref"]
        or selected.get("profile") != "tagged-moi-local-terminal-copy/3"
        or seal([selected.get("old_slot"), selected.get("destination_slot")])
        != seal([origin["current_slot"], origin["previous_slot"]])
    ):
        raise ValueError("The fresh terminal edit differs from its verified recovery origin.")
    return {
        "binary_terminal_recovery_profile": PROFILE,
        "binary_terminal_recovery_parent_receipt": options.binary_terminal_recovery_parent_receipt,
        "binary_terminal_recovery_origin": origin,
        "binary_terminal_recovery_origin_sha256": prepared["origin_sha256"],
        "binary_terminal_recovery_lineage_enforced": True,
    }


def validate_plan(body, options):
    present = KEYS.intersection(body)
    if not present and not isinstance(options, BinaryTerminalRecoveryPreview):
        return
    if (
        present != KEYS
        or not isinstance(options, BinaryTerminalRecoveryPreview)
        or body.get("operation_profile") != TERMINAL_PROFILE
        or body.get("binary_terminal_recovery_profile") != PROFILE
        or body.get("binary_terminal_recovery_lineage_enforced") is not True
        or type(body.get("binary_terminal_recovery_origin")) is not dict
        or body.get("binary_terminal_recovery_parent_receipt")
        != options.binary_terminal_recovery_parent_receipt
        or body.get("binary_terminal_recovery_origin_sha256")
        != options.binary_terminal_recovery_origin_sha256
        or seal(body.get("binary_terminal_recovery_origin"))
        != options.binary_terminal_recovery_origin_sha256
        or body.get("binary_terminal_recovery_origin", {}).get("parent_receipt_id")
        != options.binary_terminal_recovery_parent_receipt
    ):
        raise ValueError(
            "Terminal recovery lineage changed or was removed; prepare and review again."
        )
