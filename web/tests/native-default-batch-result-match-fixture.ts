import { python } from "./caf-native-fixture";
export function seedBatchResultMatch(directory: string, kind = "valid") {
  return JSON.parse(
    python(
      `
import asyncio,base64,json,sys,pytest,struct
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_default_batch_result_match import comparison_source
from tests.test_native_default_transfer import real_slot
from tests.test_caf_graph import make_graph
from bms_tool.native_default_batch_result_match import NativeDefaultBatchResultMatch
from bms_tool.native_default_batch import NativeDefaultBatch
from bms_tool.native_signal_compiler import SignalCompilerService
async def main():
 patch=pytest.MonkeyPatch();gen=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(gen)
 try:
  peer,_,_,native,target=link;kind=sys.argv[2]
  receipt,args=await comparison_source(link,recovery=kind=='recovery',historical=kind=='historical',current_routed=kind=='routed')
  if kind in ('selected','unselected','reencoded'):
   if kind=='reencoded':
    encoded=bytearray(peer.files[3]);encoded[4:8]=(1234).to_bytes(4,'little');peer.files[3]=bytes(encoded)
   else:real_slot(peer.files,17 if kind=='selected' else 0,struct.pack('>f',19 if kind=='selected' else 47))
   current=await native.capture(**target,operation_id='capture-comparison-fixture-change')
   snapshot,_=native.storage.load(current['id']);args.update(capture_id=current['id'],snapshot_sha256=snapshot['evidence_sha256'])
  report=NativeDefaultBatchResultMatch(native.default_batch_recovery.records).compare(args)
  source=SignalCompilerService(native.storage).source(args['capture_id'])
  opened=NativeDefaultBatch(native.default_batch_recovery.records).source({k:args[k] for k in ['capture_id','snapshot_sha256']})
  print(json.dumps(dict(id=receipt['intent']['id'],request=args,receipt=receipt,report=report,source=source,opened=opened,caf=base64.b64encode(make_graph()).decode())))
 finally:await gen.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
      kind,
    ),
  );
}
