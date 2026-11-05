import { python } from "./native-connection-fixture";
export function seedBinaryLedger(directory: string) {
  return JSON.parse(
    python(
      `
import asyncio,json,sys
from pathlib import Path
from tests.test_native_binary_terminal_ledger import seed_binary_records,binary_body
from tests.test_native_terminal_ledger import terminal_body
from tests.test_native_input_ledger import authored_body
from tests.test_change_ledger import native
from bms_tool.app import create_app
from bms_tool.native_binary_terminal_ledger import binary_terminal_reference
from bms_tool.native_terminal_ledger import terminal_reference
from bms_tool.native_input_ledger import input_reference
p=Path(sys.argv[1]);receipt=asyncio.run(seed_binary_records(p));app=create_app(p)
bad=binary_body();bad['compilation']['terminal_compilation']['profile']='unsupported/3';invalid=native(app,number=201,**bad)
uncertain=native(app,number=202,**binary_body())
print(json.dumps({'id':receipt['intent']['id'],'metadata':binary_terminal_reference(receipt['intent'])['native_binary_terminal'],'invalid':invalid['id'],'uncertain':uncertain['id'],'legacy':input_reference(authored_body())['native_input'],'terminal':terminal_reference(terminal_body())['native_terminal']}))
`,
      directory,
    ),
  );
}
