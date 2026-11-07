import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../..", import.meta.url));
export function seedOrderRecoveryProposal(directory: string, kind = "match") {
  return JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        `
import asyncio,base64,json,os,sys,pytest
from pathlib import Path
import bms_tool
from tests.test_native_applications import native_link
from tests.test_native_order_result_match import order_match_source
from tests.test_caf_graph import make_graph
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_order_result_match import NativeOrderResultMatch
from bms_tool.native_order_recovery_proposal import NativeOrderRecoveryProposal
installed=os.environ.get('BMS_TEST_INSTALLED_TARGET')
if installed:assert Path(bms_tool.__file__).resolve().is_relative_to(Path(installed).resolve())
async def main():
 patch=pytest.MonkeyPatch();gen=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(gen)
 try:
  native=link[3];kind=sys.argv[2]
  receipt,args=await order_match_source(link,historical=kind=='historical',routed=kind=='routed',kind=kind if kind in ('saved','order','reencoded') else 'match')
  records=NativeBackupRecords(native.storage);comparison=NativeOrderResultMatch(records).compare(args)
  proposal=NativeOrderRecoveryProposal(records).prepare(args) if comparison['state']=='application-and-order-match' else None
  snapshot,files=native.storage.load(args['capture_id'])
  print(json.dumps(dict(id=args['capture_id'],receipt=receipt,request=args,report=comparison,source=records.envelope(snapshot,files),opened=comparison['source'],proposal=proposal,caf=base64.b64encode(make_graph()).decode())))
 finally:await gen.aclose();patch.undo()
asyncio.run(main())
`,
        directory,
        kind,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [
            process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
            root,
          ].join(path.delimiter),
        },
        encoding: "utf8",
      },
    ),
  );
}
