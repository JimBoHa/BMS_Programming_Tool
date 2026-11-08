import { python } from "./native-connection-fixture";
export function snapshotRestoreFixture(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,copy,gzip,json,sys,pytest,base64
from pathlib import Path
from contextlib import aclosing
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_snapshot_restore_ledger import restore_reference
from tests.test_native_applications import native_link
from tests.test_native_snapshot_restore import prepared,apply_request,literal_saved_image
async def one(kind):
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1])/kind,patch)) as generator:
   link=await anext(generator);peer,bacnet,store,native,target=link
   old,historical,review=await prepared(link)
   original,files=native.storage.load(old['id'])
   archive=NativeBackupRecords.envelope(original,files)
   output,inspected=native.restore_source({'restore_capture_id':old['id'],'restore_snapshot_sha256':old['evidence_sha256']})
   controller={**archive['target'],'name':review['identity']['object-name'],'model':review['identity']['model-name'],'interfaceKey':json.dumps(bacnet.config,separators=(',',':')),'interfaceOpen':True,'ownedCommands':0,'verifiedAt':'2026-01-02T00:00:00Z'}
   before=copy.deepcopy(peer.files)
   if kind!='verified':peer.mode='drop-end'
   receipt=await native.apply_snapshot_restore(**apply_request(review))
   assert receipt['result']['status']==('verified' if kind=='verified' else 'unknown'),receipt
   reconciled=None
   if kind!='verified':
    peer.mode='normal'
    if kind=='recovered-original':
     peer.files=before;peer.files[3]=gzip.compress(literal_saved_image(modules=4,real=22.5),mtime=0)
    reconciled=await native.reconcile(operation_id='contract-retained-restore-readback',receipt_id=receipt['intent']['id'])
    assert reconciled['latest_readback']['status']==('recovered_original' if kind=='recovered-original' else 'verified'),reconciled
   row={'source':'native','native_change_kind':'application-restore','id':receipt['intent']['id'],'target':{**receipt['intent']['target'],'device':receipt['intent']['identity']['device']},**restore_reference(receipt['intent'])}
   return dict(archive=archive,inspected=inspected,review=review,receipt=receipt,reconciled=reconciled,controller=controller,row=row,artifact=base64.b64encode(output).decode())
async def main():print(json.dumps({kind:await one(kind) for kind in ['verified','uncertain','recovered-original']}))
asyncio.run(main())
`,
      directory,
    ),
  );
}
