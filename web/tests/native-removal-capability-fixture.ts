import { seed as connectionSeed } from "./native-connection-capability-fixture";
import { python } from "./native-connection-fixture";
export {
  enter,
  inspect,
  analyze,
} from "./native-connection-capability-fixture";

export function seed(directory: string) {
  const f = connectionSeed(directory);
  return {
    ...f,
    ...JSON.parse(
      python(
        `
from pathlib import Path
import json,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_removal_capabilities import PROFILE
from tests.test_native_signal_compiler import retained
from tests.test_native_connection_removal import removal_files
s=ApplicationStore(Store(sys.argv[1]));records=NativeBackupRecords(s);snap,_=s.load(sys.argv[2])
query={'capture_id':snap['id'],'snapshot_sha256':snap['evidence_sha256'],'capability_profile':PROFILE}
report=records.capabilities(query)
empty=retained(s,removal_files(wires=[]),identity=snap['identity'])
print(json.dumps({'report':report,'request':query,'empty':empty['id']}))
`,
        directory,
        f.id,
      ),
    ),
  };
}
