import { python } from "./native-connection-fixture";
export function seedCapacity(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys
from pathlib import Path
from contextlib import aclosing
import pytest
from tests.test_native_applications import native_link
from tests.test_native_capacity_evidence import prepare
from tests.test_native_default_transfer import NativeRouter
async def one(name,routed,capacity):
 with pytest.MonkeyPatch.context() as patch:
  async with aclosing(native_link.__wrapped__(Path(sys.argv[1])/name,patch)) as generator:
   link=await anext(generator);peer,_,_,native,target=link;transport=None
   if routed:
    host,port=target['address'].rsplit(':',1);transport,router=await asyncio.get_running_loop().create_datagram_endpoint(lambda:NativeRouter((host,int(port))),local_addr=('127.0.0.1',0));target={'address':'3001:7','device':'device,5136','router':router.endpoint,'dnet':3001}
   try:
    service,query=await prepare(link,target=target);peer.application_capacity=capacity;report=await service.read(query);source=report['source'];controller={**report['target'],'name':report['identity']['object-name'],'model':report['identity']['model-name'],'interfaceKey':json.dumps(report['connector_config'],separators=(',',':')),'interfaceOpen':True,'ownedCommands':0,'verifiedAt':'2026-01-02T00:00:00Z'}
    return {'report':report,'source':source,'query':query,'archive':{k:source[k] for k in ['capture_id','snapshot_sha256','sha256','files','target']},'controller':controller}
   finally:
    if transport:transport.close()
async def main():print(json.dumps({'direct':await one('direct',False,131072),'routed':await one('routed',True,131072),'over':await one('over',False,1)}))
asyncio.run(main())
`,
      directory,
    ),
  );
}
