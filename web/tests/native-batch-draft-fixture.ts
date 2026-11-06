import { python } from "./native-connection-fixture";
export function seedBatchDraftSources(directory: string, count = 33) {
  return JSON.parse(
    python(
      `
import json,sys
from pathlib import Path
from tests.test_native_default_batch import local
from bms_tool.native_signal_compiler import SignalCompilerService
rows=[]
for _ in range(int(sys.argv[2])):
 storage,service,snapshot,query,opened=local(Path(sys.argv[1]))
 rows.append({'id':snapshot['id'],'source':opened,'signal':SignalCompilerService(storage).source(snapshot['id'])})
print(json.dumps(rows))
`,
      directory,
      String(count),
    ),
  );
}
