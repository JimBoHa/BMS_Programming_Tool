import { python } from "./caf-native-fixture";
export function seedBatchRecovery(directory: string, kind = "valid") {
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
  if sys.argv[2]=='already':
   import tests.test_native_default_batch_transfer as bt
   from tests.test_moi_wire_sources import D
   original_edits=bt.edits
   patch.setattr(bt,'edits',lambda opened:[c for c in original_edits(opened) if c['record_ref']!=D])
  proposal,review=await review_native(link)
  source=SignalCompilerService(native.storage).source(proposal['capture_id'])
  opened=NativeDefaultBatch(NativeBackupRecords(native.storage)).source({k:proposal[k] for k in ['capture_id','snapshot_sha256']})
  real_slot(peer.files,0,struct.pack('>f',45))
  historical=sys.argv[2] in ('historical','later-unknown')
  if historical:peer.mode='drop-end'
  receipt=await native.apply_default_batch(**applying(review))
  if historical:
   assert receipt['pending'] and receipt['result']['status']=='unknown',receipt
   peer.mode='normal'
   receipt=await native.reconcile(operation_id='reconcile-original-batch-recovery',receipt_id=receipt['intent']['id'])
   assert not receipt['pending'] and receipt['latest_readback']['status']=='verified',receipt
   if sys.argv[2]=='later-unknown':
    native.storage.event(receipt['intent']['id'],'readback',{'status':'unknown','authored':'Later inconclusive observation'})
    receipt=native.storage.receipt(receipt['intent']['id'])
  else:assert receipt['result']['status']=='verified',receipt
  if sys.argv[2]=='already':peer.files[12]=native.storage.load(receipt['intent']['backup_id'])[1][12]
  if sys.argv[2]=='partial':real_slot(peer.files,17,struct.pack('>f',3.5))
  if sys.argv[2]=='recompressed':
   import gzip
   from bms_tool.moi_identity import MoiIdentity
   peer.files[3]=gzip.compress(MoiIdentity(peer.files[3]).data,mtime=555)
  captured=await native.capture(**link[4],operation_id='capture-current-for-batch-recovery')
  snapshot,_=native.storage.load(captured['id'])
  query={'capture_id':captured['id'],'snapshot_sha256':snapshot['evidence_sha256']}
  source=SignalCompilerService(native.storage).source(captured['id'])
  opened=NativeDefaultBatch(NativeBackupRecords(native.storage)).source(query)
  recovery=native.default_batch_recovery.prepare(dict(receipt_id=receipt['intent']['id'],**query))
  print(json.dumps(dict(recovery=recovery,id=receipt['intent']['id'],caf=base64.b64encode(make_graph()).decode(),source=source,proposal=proposal,review=review,opened=opened,receipt=receipt,recorded=batch_reference(receipt['intent'])['native_default_batch'])))
 finally:await generator.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
      kind,
    ),
  );
}
