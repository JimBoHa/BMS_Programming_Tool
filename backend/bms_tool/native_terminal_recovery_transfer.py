"""Parent-bound analog terminal recovery through the existing profile-2 writer."""

from pydantic import Field, model_validator

from .moi_identity import seal
from .native_backup_records import NativeBackupRecords
from .native_inputs import TERMINAL_PROFILE, InputPreview
from .native_terminal_recovery import NativeTerminalRecovery

PROFILE = "native-analog-terminal-recovery-transfer/1"
KEYS = {
    "terminal_recovery_profile",
    "recovery_parent_receipt",
    "recovery_origin",
    "recovery_origin_sha256",
    "terminal_recovery_lineage_enforced",
}


class TerminalRecoveryPreview(InputPreview):
    recovery_parent_receipt: str = Field(pattern=r"^[a-f0-9]{32}$")
    recovery_origin_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def terminal_only(self):
        if self.edit.action != "terminal":
            raise ValueError("A terminal recovery review requires its exact derived terminal edit.")
        return self


def recovery_origin(service, options, compilation):
    if not isinstance(options, TerminalRecoveryPreview):
        return {}
    prepared = NativeTerminalRecovery(NativeBackupRecords(service.storage)).prepare(
        {
            "receipt_id": options.recovery_parent_receipt,
            "capture_id": options.capture_id,
            "snapshot_sha256": options.snapshot_sha256,
        }
    )
    proposal, origin = prepared["proposal"], prepared["origin"]
    selected = compilation.get("terminal_compilation", {})
    if (
        proposal is None
        or prepared["already_recorded"]
        or prepared["origin_sha256"] != options.recovery_origin_sha256
        or seal(prepared["source"]["target"])
        != seal({**service.target(options), "device": options.device})
        or seal(proposal["edit"]) != seal(options.edit.model_dump())
        or compilation.get("profile") != TERMINAL_PROFILE
        or seal(compilation.get("input_edit")) != seal(proposal["edit"])
        or compilation.get("object_id") != origin["object_id"]
        or compilation.get("record_ref") != origin["record_ref"]
        or selected.get("profile") != "tagged-moi-local-terminal-copy/2"
        or seal([selected.get("old_slot"), selected.get("destination_slot")])
        != seal([origin["current_slot"], origin["previous_slot"]])
    ):
        raise ValueError("The fresh terminal edit differs from its verified recovery origin.")
    return {
        "terminal_recovery_profile": PROFILE,
        "recovery_parent_receipt": options.recovery_parent_receipt,
        "recovery_origin": origin,
        "recovery_origin_sha256": prepared["origin_sha256"],
        "terminal_recovery_lineage_enforced": True,
    }


def validate_plan(body, options):
    present = KEYS.intersection(body)
    if not present and not isinstance(options, TerminalRecoveryPreview):
        return
    if (
        present != KEYS
        or not isinstance(options, TerminalRecoveryPreview)
        or body.get("operation_profile") != TERMINAL_PROFILE
        or body.get("terminal_recovery_profile") != PROFILE
        or body.get("terminal_recovery_lineage_enforced") is not True
        or type(body.get("recovery_origin")) is not dict
        or body.get("recovery_parent_receipt") != options.recovery_parent_receipt
        or body.get("recovery_origin_sha256") != options.recovery_origin_sha256
        or seal(body.get("recovery_origin")) != options.recovery_origin_sha256
        or body.get("recovery_origin", {}).get("parent_receipt_id")
        != options.recovery_parent_receipt
    ):
        raise ValueError(
            "Terminal recovery lineage changed or was removed; prepare and review again."
        )
