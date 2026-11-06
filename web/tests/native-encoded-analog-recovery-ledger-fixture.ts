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
from tests.test_native_encoded_analog_recovery_ledger import seed_recovery_records
from bms_tool.app import create_app
from bms_tool.native_encoded_analog_ledger import encoded_analog_terminal_reference
from bms_tool.native_encoded_analog_recovery_ledger import encoded_analog_recovery_reference
from tests.test_native_terminal_ledger import terminal_body
from tests.test_native_binary_terminal_ledger import binary_body
from tests.test_native_input_ledger import authored_body
from bms_tool.native_terminal_ledger import terminal_reference
from bms_tool.native_binary_terminal_ledger import binary_terminal_reference
from bms_tool.native_input_ledger import input_reference
p=Path(sys.argv[1]);parent,child=asyncio.run(seed_recovery_records(p));app=create_app(p);storage=app.state.native_applications.storage
bad=copy.deepcopy(child['intent'])
for key in ['evidence_sha256','profile','created_at']:bad.pop(key,None)
bad['id']='f'*32;bad['encoded_analog_recovery_profile']='unsupported/1'
invalid=storage.intent(bad)
storage.finish(invalid['id'],{'intent_sha256':invalid['evidence_sha256'],'status':'not_sent','may_have_applied':False,'error':'Authored invalid profile'})
unknown=copy.deepcopy(child['intent'])
for key in ['evidence_sha256','profile','created_at']:unknown.pop(key,None)
unknown['id']='e'*32;uncertain=storage.intent(unknown)
storage.finish(uncertain['id'],{'intent_sha256':uncertain['evidence_sha256'],'status':'unknown','may_have_applied':True,'error':'Authored unknown outcome'})
terminal=encoded_analog_terminal_reference(child['intent'])['native_encoded_analog_terminal']
metadata=encoded_analog_recovery_reference(child['intent'],terminal)['native_encoded_analog_recovery']
print(json.dumps({'id':child['intent']['id'],'parent':parent['intent']['id'],'invalid':invalid['id'],'terminal':terminal,'metadata':metadata,'device':'device,5136','uncertain':uncertain['id'],'legacy':input_reference(authored_body())['native_input'],'oldTerminal':terminal_reference(terminal_body())['native_terminal'],'binary':binary_terminal_reference(binary_body())['native_binary_terminal']}))`,
      directory,
    ),
  );
}
