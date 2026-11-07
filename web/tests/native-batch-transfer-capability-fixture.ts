import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
export { inspect, analyze } from "./native-connection-capability-fixture";
const root = fileURLToPath(new URL("../..", import.meta.url));
export function seedBatchTransferCapabilities(directory: string) {
  const code = `
import base64,json,sys
from pathlib import Path
from unittest.mock import patch
from tests.test_native_batch_capabilities import source
from tests.test_native_batch_transfer_capabilities import analyze
from tests.test_native_default_batch import batch_files
from tests.test_moi_parameters import parameters_source
from tests.test_moi_effective_enum import enum_files
from tests.test_native_boolean_copies import boolean_files
from tests.test_caf_native_correlation import caf_source
from bms_tool import native_default_batch_transfer
results={}
for kind in ['valid','serial','bbmd','unknown','unverified','large','empty','refused','boolean','enum','unfixed']:
 files=batch_files(extra=20 if kind=='large' else 0);metadata={}
 if kind=='serial':metadata['connector_config']={'transport':'mstp','serial_port':'authored-none'}
 if kind=='bbmd':metadata['connector_config']={'local_address':'127.0.0.1:47819','bbmd_address':'127.0.0.1:47820'}
 if kind=='unknown':files[11]=b'Authored unknown saved directory'
 if kind=='unverified':metadata['source_identity_matches']=False
 if kind=='empty':files=dict(zip((3,11,12),parameters_source(),strict=True))
 if kind in ('enum','unfixed'):files=enum_files(saved=0,slot=kind!='unfixed')
 if kind=='boolean':files=boolean_files(real_signals=False)
 if kind in ('empty','boolean','enum','unfixed'):metadata['identity']={'object-name':'Authored controller','vendor-identifier':5,'model-name':'UNLISTED-MODEL'}
 storage,records,snapshot,query=source(Path(sys.argv[1]),files,**metadata)
 if kind=='refused':
  with patch.object(native_default_batch_transfer,'compile_batch_defaults',side_effect=ValueError('Authored bounded transfer refusal')):report=analyze(records,query)
 else:report=analyze(records,query)
 previous=records.capabilities(query|{'capability_profile':'native-backup-operation-capabilities/20'})
 results[kind]={'id':snapshot['id'],'query':query,'report':report,'previous':previous,'archive':{k:report[k] for k in ['capture_id','snapshot_sha256','sha256','files','target']}}
print(json.dumps({'cases':results,'caf':base64.b64encode(caf_source().original).decode()}))
`;
  return JSON.parse(
    execFileSync(path.join(root, ".venv/bin/python"), ["-c", code, directory], {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [
          process.env.BMS_TEST_INSTALLED_TARGET || path.join(root, "backend"),
          root,
        ].join(path.delimiter),
      },
      encoding: "utf8",
      maxBuffer: 8 * 1024 * 1024,
    }),
  );
}
