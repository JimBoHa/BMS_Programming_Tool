"""Profile-two native terminal transfers through owned protocol peers only."""

import copy

from bms_tool.native_inputs import NativeInputCompiler

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_input_transfer import apply, install_input_peer, preview
from .test_native_inputs import source
from .test_native_terminal_input import terminal_edit


async def test_existing_analog_terminal_transfer_has_full_published_and_saved_readback(native_link):
    peer, service = install_input_peer(native_link, initialize=False)
    peer.files = source(existing=True)
    original = copy.deepcopy(peer.files)
    _, plan = await preview(native_link, terminal_edit(NativeInputCompiler(peer.files)), "terminal")
    assert plan["operation_profile"] == "native-local-universal-input-transfer/2"
    result = await service.apply_input(**apply(plan, "terminal"))
    assert result["result"]["status"] == "verified", result
    assert result["intent"]["operation_profile"] == plan["operation_profile"]
    assert result["intent"]["input_edit"]["action"] == "terminal"
    published = {
        p["property"]: p["actual"] for p in result["result"]["published_input"]["properties"]
    }
    assert published[31] == "UI IN3" and published[519] == 3
    assert peer.files[11] == original[11] and peer.files[12] == original[12]
    assert NativeInputCompiler(peer.files).source()["inputs"][0]["slot"] == 3
    writes = [e for e in peer.events if e[0] == "write"]
    receipt = await service.reconcile(
        operation_id="terminal-readback", receipt_id=result["intent"]["id"]
    )
    assert receipt["events"][-1]["detail"]["status"] == "verified", receipt
    assert [e for e in peer.events if e[0] == "write"] == writes
    assert [e for e in peer.events if e == ("state", "start-restore")] == [
        ("state", "start-restore")
    ]
