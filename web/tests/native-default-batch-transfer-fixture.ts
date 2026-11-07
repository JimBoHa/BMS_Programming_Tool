import { python } from "./caf-native-fixture";
export function seedBatchTransfer(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys,struct,pytest,base64
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_caf_graph import make_graph
from tests.test_native_default_batch_transfer import review_native,applying
from tests.test_native_default_transfer import real_slot
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.native_default_batch import NativeDefaultBatch
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_batch_ledger import batch_reference
async def main():
 patch=pytest.MonkeyPatch();generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator)
 try:
  peer,_,_,native,_=link
  proposal,review=await review_native(link)
  source=SignalCompilerService(native.storage).source(proposal['capture_id'])
  opened=NativeDefaultBatch(NativeBackupRecords(native.storage)).source({k:proposal[k] for k in ['capture_id','snapshot_sha256']})
  real_slot(peer.files,0,struct.pack('>f',45))
  receipt=await native.apply_default_batch(**applying(review));assert receipt['result']['status']=='verified',receipt
  print(json.dumps(dict(id=receipt['intent']['id'],caf=base64.b64encode(make_graph()).decode(),source=source,proposal=proposal,review=review,opened=opened,receipt=receipt,recorded=batch_reference(receipt['intent'])['native_default_batch'])))
 finally:await generator.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
    ),
  );
}
