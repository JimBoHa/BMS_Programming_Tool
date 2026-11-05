import { python } from "./native-connection-fixture";
export {
  openTerminalLedger,
  openTerminalEvidence,
} from "./native-terminal-ledger-fixture";
export function seed(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import asyncio,copy,json,sys
from tests.test_native_terminal_recovery_ledger import seed_recovery_records
from bms_tool.app import create_app
from bms_tool.native_terminal_ledger import terminal_reference
from bms_tool.native_terminal_recovery_ledger import terminal_recovery_reference
p=Path(sys.argv[1]);parent,child=asyncio.run(seed_recovery_records(p));app=create_app(p);storage=app.state.native_applications.storage
bad=copy.deepcopy(child['intent'])
for key in ['evidence_sha256','profile','created_at']:bad.pop(key,None)
bad['id']='f'*32;bad['terminal_recovery_profile']='unsupported/1'
invalid=storage.intent(bad)
terminal=terminal_reference(child['intent'])['native_terminal']
metadata=terminal_recovery_reference(child['intent'],terminal)['native_terminal_recovery']
print(json.dumps({'id':child['intent']['id'],'parent':parent['intent']['id'],'invalid':invalid['id'],'terminal':terminal,'metadata':metadata,'device':'device,5136'}))`,
      directory,
    ),
  );
}
