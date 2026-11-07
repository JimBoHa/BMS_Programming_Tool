import { python } from "./native-connection-fixture";
export {
  enter,
  inspect,
  analyze,
} from "./native-connection-capability-fixture";
export function seedOrderCapabilities(directory: string) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from pathlib import Path
from unittest.mock import patch
from tests.test_native_execution_order import setup,many_source
from tests.test_native_wire_compiler import wire_files
from tests.test_caf_graph import make_graph
from bms_tool import native_order_transfer
cases={}
for kind in ['valid','raw','activity','serial','bbmd','chain','unknown','unverified','refused','large']:
 files=wire_files(compressed=kind!='raw',diagram_class=536 if kind=='activity' else 575,wires=[(0,85,1,7000),(1,85,2,7000),(2,85,3,7000)] if kind=='chain' else None);metadata={}
 if kind=='serial':metadata['connector_config']={'transport':'mstp','serial_port':'authored-none'}
 if kind=='bbmd':metadata['connector_config']={'local_address':'127.0.0.1:47819','bbmd_address':'127.0.0.1:47820'}
 if kind=='unknown':files[11]=b'Authored unknown saved directory'
 if kind=='unverified':metadata['source_identity_matches']=False
 if kind=='large':files[3]=many_source(512)
 storage,service,snapshot,_=setup(Path(sys.argv[1]),files,**metadata)
 q={'capture_id':snapshot['id'],'snapshot_sha256':snapshot['evidence_sha256']}
 if kind=='refused':
  with patch.object(native_order_transfer,'compile_order',side_effect=ValueError('Authored transfer prerequisite refusal')):report=service.records.capabilities(q|{'capability_profile':'native-backup-operation-capabilities/22'})
 else:report=service.records.capabilities(q|{'capability_profile':'native-backup-operation-capabilities/22'})
 previous=service.records.capabilities(q|{'capability_profile':'native-backup-operation-capabilities/14'})
 cases[kind]={'id':snapshot['id'],'query':q,'report':report,'previous':previous,'archive':{k:report[k] for k in ['capture_id','snapshot_sha256','sha256','files','target']}}
print(json.dumps({'cases':cases,'caf':base64.b64encode(make_graph()).decode()}))
`,
      directory,
    ),
  );
}
