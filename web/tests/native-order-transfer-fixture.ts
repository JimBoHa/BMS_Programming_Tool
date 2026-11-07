import { python } from "./native-connection-fixture";

export function orderTransferSeed(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,copy,json,sys,struct,types
from pathlib import Path
from contextlib import aclosing
import pytest
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_execution_order import NativeExecutionOrder,OrderSource
from bms_tool.moi_parameters import ParameterApplication
from tests.test_native_applications import native_link
from tests.test_native_order_transfer import order_review,applying
from tests.test_native_default_transfer import real_slot
async def one(name,mode):
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1])/name,patch)) as generator:
   link=await anext(generator);peer,bacnet,store,native,target=link
   proposal,review=await order_review(link)
   opened=NativeExecutionOrder(NativeBackupRecords(native.storage)).source({k:proposal[k] for k in OrderSource.model_fields})
   source={k:opened[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}
   controller={**source['target'],'name':review['identity']['object-name'],'model':review['identity']['model-name'],'interfaceKey':json.dumps(bacnet.config,separators=(',',':')),'interfaceOpen':True,'ownedCommands':0,'verifiedAt':'2026-01-02T00:00:00Z'}
   if mode=='recover':
    original=ParameterApplication(peer.files[3],peer.files[11],peer.files[12]).compile()[0];state=peer.do_ReinitializeDeviceRequest
    async def recovered(self,request):
     await state(request)
     if str(request.reinitializedStateOfDevice)=='end-restore':self.files[3]=original
    peer.do_ReinitializeDeviceRequest=types.MethodType(recovered,peer)
   else:real_slot(peer.files,0,struct.pack('>f',45))
   if mode=='uncertain':peer.mode='drop-end'
   receipt=await native.apply_order(**applying(review))
   assert receipt['result']['status']==('recovered_original' if mode=='recover' else 'unknown' if mode=='uncertain' else 'verified'),receipt
   reconciled=None
   if mode=='uncertain':
    peer.mode='normal';reconciled=await native.reconcile(operation_id='order-fixture-readback',receipt_id=receipt['intent']['id']);assert reconciled['latest_readback']['status']=='verified'
   return {'source':source,'opened':opened,'proposal':proposal,'review':review,'controller':controller,'receipt':receipt,'reconciled':reconciled}

async def main():
 print(json.dumps({'verified':await one('verified','normal'),'uncertain':await one('uncertain','uncertain'),'recovered':await one('recovered','recover')}))
asyncio.run(main())
`,
      directory,
    ),
  );
}
