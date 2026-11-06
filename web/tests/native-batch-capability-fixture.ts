import { python } from "./native-connection-fixture";
export { inspect, analyze } from "./native-connection-capability-fixture";

export function seedBatchCapabilities(directory: string) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from pathlib import Path
from unittest.mock import patch
from tests.test_native_batch_capabilities import source,analyze
from tests.test_native_default_batch import batch_files
from tests.test_moi_parameters import parameters_source
from tests.test_moi_effective_enum import enum_files
from tests.test_native_boolean_copies import boolean_files
from tests.test_caf_native_correlation import caf_source
from bms_tool.moi_default_batch import EffectiveDefaultBatchCompiler
results={}
for kind in ['valid','serial','unknown','unverified','large','empty','refused','boolean','enum']:
 files=batch_files(extra=20 if kind=='large' else 0)
 metadata={}
 if kind=='serial':metadata['connector_config']={'transport':'mstp','serial_port':'authored-none'}
 if kind=='unknown':files[11]=b'Authored unknown saved directory'
 if kind=='unverified':metadata['source_identity_matches']=False
 if kind=='empty':
  files=dict(zip((3,11,12),parameters_source(),strict=True))
  metadata['identity']={'object-name':'Authored controller','vendor-identifier':5,'model-name':'UNLISTED-MODEL'}
 if kind in ('boolean','enum'):
  files=enum_files(saved=0) if kind=='enum' else boolean_files(real_signals=False)
  metadata['identity']={'object-name':'Authored controller','vendor-identifier':5,'model-name':'UNLISTED-MODEL'}
 storage,records,snapshot,query=source(Path(sys.argv[1]),files,**metadata)
 if kind=='refused':
  with patch.object(EffectiveDefaultBatchCompiler,'compile',side_effect=ValueError('Authored bounded batch refusal')):report=analyze(records,query)
 else:report=analyze(records,query)
 previous=records.capabilities(query|{'capability_profile':'native-backup-operation-capabilities/19'})
 results[kind]={'id':snapshot['id'],'report':report,'previous':previous,'archive':{k:report[k] for k in ['capture_id','snapshot_sha256','sha256','files','target']}}
print(json.dumps({'cases':results,'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
    ),
  );
}
