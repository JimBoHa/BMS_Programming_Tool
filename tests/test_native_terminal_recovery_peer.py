"""A genuine owned UDP transfer produces the parent proof for local inverse preparation."""

from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.native_terminal_recovery import NativeTerminalRecovery

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_inputs import source
from .test_native_terminal_input import terminal_edit


async def test_actual_transfer_and_saved_capture_qualify_local_inverse_without_more_field_access(
    native_link,
):
    peer, service = install_input_peer(native_link, initialize=False)
    peer.files = source(existing=True)
    _, plan = await preview(
        native_link, terminal_edit(NativeInputCompiler(peer.files)), "inverse-parent"
    )
    result = await service.apply_input(**apply(plan, "inverse-parent"))
    assert result["result"]["status"] == "verified", result
    capture = await service.capture(**native_link[4], operation_id="capture-inverse-current")
    before = list(peer.events)
    report = NativeTerminalRecovery(NativeBackupRecords(service.storage)).prepare(
        {
            "receipt_id": result["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    assert report["proposal"]["edit"]["slot"] == 1 and report["origin"]["current_slot"] == 3
    assert peer.events == before and not service.plans
