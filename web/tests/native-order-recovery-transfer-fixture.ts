import { python } from "./native-connection-fixture";
export function orderRecoveryTransferSeed(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,copy,json,sys,pytest,struct
from pathlib import Path
from contextlib import aclosing
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_order_recovery_ledger import recovery_reference
from tests.test_native_applications import native_link
from tests.test_native_order_recovery_transfer import original_and_proposal
from tests.test_native_order_transfer import applying
from tests.test_native_default_transfer import real_slot
async def one(kind):
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1])/kind,patch)) as generator:
   link=await anext(generator);peer,bacnet,store,native,target=link
   parent,prepared,args=await original_and_proposal(link,historical=kind=='historical')
   snapshot,files=native.storage.load(args['capture_id'])
   source=NativeBackupRecords.envelope(snapshot,files);opened=prepared['comparison']['source']
   review=await native.preview_order(**args)
   controller={**source['target'],'name':review['identity']['object-name'],'model':review['identity']['model-name'],'interfaceKey':json.dumps(bacnet.config,separators=(',',':')),'interfaceOpen':True,'ownedCommands':0,'verifiedAt':'2026-01-02T00:00:00Z'}
   real_slot(peer.files,0,struct.pack('>f',47))
   if kind=='uncertain':peer.mode='drop-end'
   receipt=await native.apply_order(**applying(review,operation_id='contract-previous-order-apply'))
   assert receipt['result']['status']==('unknown' if kind=='uncertain' else 'verified'),receipt
   reconciled=None
   if kind=='uncertain':
    peer.mode='normal';reconciled=await native.reconcile(operation_id='contract-previous-order-readback',receipt_id=receipt['intent']['id'])
   row={'source':'native','native_change_kind':'execution-order','id':receipt['intent']['id'],'object':receipt['intent']['order_edit']['diagram_ref'],'target':{**receipt['intent']['target'],'device':receipt['intent']['identity']['device']},**recovery_reference(receipt['intent'])}
   return dict(source=source,opened=opened,proposal=prepared['proposal'],prepared=prepared,parent=parent,review=review,receipt=receipt,reconciled=reconciled,controller=controller,row=row)
async def main():print(json.dumps({kind:await one(kind) for kind in ['verified','historical','uncertain']}))
asyncio.run(main())
`,
      directory,
    ),
  );
}
