import { python } from "./native-connection-fixture";
export {
  enter,
  analyze,
  inspect,
} from "./native-connection-capability-fixture";

export function seedCombinedCapabilities(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import base64,json,sys
from tests.test_native_combined_capabilities import source
from tests.test_native_default_wire_transfer import combined_files
from tests.test_native_signal_compiler import retained
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_combined_capabilities import PROFILE
from tests.test_caf_native_correlation import caf_source
s,records,snapshot,query=source(Path(sys.argv[1]));report=records.capabilities(query|{'capability_profile':PROFILE})
old=records.capabilities(query|{'capability_profile':'native-backup-operation-capabilities/18'})
files=combined_files();files[11]=b'Authored unknown saved selectors'
unknown=retained(s,files,identity=snapshot['identity'])
serial=retained(s,combined_files(),identity=snapshot['identity'],connector_config={'transport':'mstp','serial_port':'authored-none'})
results={}
for name,snap in [('valid',snapshot),('unknown',unknown),('serial',serial)]:
 r=records.capabilities({'capture_id':snap['id'],'snapshot_sha256':snap['evidence_sha256'],'capability_profile':PROFILE})
 results[name]={'id':snap['id'],'report':r,'archive':{k:r[k] for k in ['capture_id','snapshot_sha256','sha256','files','target']}}
print(json.dumps({'cases':results,'legacy':old,'query':query,'id':snapshot['id'],'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
    ),
  );
}
