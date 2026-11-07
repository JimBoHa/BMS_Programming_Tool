import { python } from "./caf-native-fixture";
export function seedOrderResultMatch(directory: string, kind = "match") {
  return JSON.parse(
    python(
      `
import asyncio,base64,json,sys,pytest
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_order_result_match import order_match_source
from tests.test_caf_graph import make_graph
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_order_result_match import NativeOrderResultMatch
async def main():
 patch=pytest.MonkeyPatch();gen=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(gen)
 try:
  native=link[3];kind=sys.argv[2]
  receipt,args=await order_match_source(link,historical=kind=='historical',routed=kind=='routed',kind=kind if kind in ('saved','order','reencoded') else 'match')
  records=NativeBackupRecords(native.storage);report=NativeOrderResultMatch(records).compare(args)
  snapshot,files=native.storage.load(args['capture_id'])
  source=records.envelope(snapshot,files)
  print(json.dumps(dict(id=args['capture_id'],receipt=receipt,request=args,report=report,source=source,opened=report['source'],caf=base64.b64encode(make_graph()).decode())))
 finally:await gen.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
      kind,
    ),
  );
}
