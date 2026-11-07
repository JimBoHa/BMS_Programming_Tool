import { python } from "./caf-native-fixture";
export function seedBatchRecoveryLedger(directory: string, mode = "verified") {
  return JSON.parse(
    python(
      `
import asyncio,base64,json,sys
from pathlib import Path
from tests.test_native_default_batch_recovery_ledger import retained_recovery
from tests.test_change_ledger import query
from tests.test_caf_graph import make_graph
from bms_tool.app import create_app
async def main():
 receipt,parent=await retained_recovery(Path(sys.argv[1]),sys.argv[2])
 app=create_app(Path(sys.argv[1]));report=await query(app,source='native',text=receipt['intent']['id'])
 row=next(r for r in report['rows'] if r['id']==receipt['intent']['id'])
 print(json.dumps(dict(id=receipt['intent']['id'],parent=parent['intent']['id'],row=row,receipt=receipt,caf=base64.b64encode(make_graph()).decode())))
asyncio.run(main())
`,
      directory,
      mode,
    ),
  );
}
