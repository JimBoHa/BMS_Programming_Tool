import { python } from "./caf-native-fixture";
export function seedBatchRecoveryTransfer(directory: string, kind = "valid") {
  return JSON.parse(
    python(
      `
import asyncio,json,sys,pytest,struct,copy
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_default_batch_recovery_transfer import original_and_proposal
from tests.test_native_default_batch_transfer import applying
from tests.test_native_default_transfer import real_slot
from bms_tool.native_default_batch import NativeDefaultBatch
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_signal_compiler import SignalCompilerService
async def main():
 patch=pytest.MonkeyPatch();generator=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(generator)
 try:
  peer,bacnet,_,native,target=link
  parent,prepared,args=await original_and_proposal(link)
  source=SignalCompilerService(native.storage).source(args['capture_id'])
  opened=NativeDefaultBatch(NativeBackupRecords(native.storage)).source({k:args[k] for k in ['capture_id','snapshot_sha256']})
  controller=dict(**target,interfaceOpen=True,ownedCommands=0,interfaceKey=json.dumps(bacnet.config))
  review=await native.preview_default_batch(**args)
  if sys.argv[2]=='fresh':real_slot(peer.files,0,struct.pack('>f',47))
  if sys.argv[2] in ('uncertain','historical','later-unknown'):peer.mode='drop-end'
  receipt=await native.apply_default_batch(**applying(review,operation_id='apply-previous-batch-fixture'))
  if sys.argv[2] in ('historical','later-unknown'):
   peer.mode='normal'
   receipt=await native.reconcile(operation_id='readback-previous-batch-fixture',receipt_id=receipt['intent']['id'])
   if sys.argv[2]=='later-unknown':
    native.storage.event(receipt['intent']['id'],'readback',{'status':'unknown','authored':'Later inconclusive observation'})
    receipt=native.storage.receipt(receipt['intent']['id'])
  print(json.dumps(dict(parent=parent,prepared=prepared,proposal=prepared['proposal'],source=source,opened=opened,controller=controller,review=review,receipt=receipt)))
 finally:await generator.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
      kind,
    ),
  );
}
