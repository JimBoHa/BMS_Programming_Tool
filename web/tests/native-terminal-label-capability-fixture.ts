import { python } from "./native-connection-fixture";
export function seedLabelCapabilities(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_terminal_capabilities import source
from tests.test_native_terminal_labels import observed_shape
from tests.test_moi_terminal_output_namespace import with_output
from bms_tool.native_terminal_label_capabilities import PROFILE
rows={}
for kind in ['ucs2','unknown','unverified','output','serial','ascii']:
 files=observed_shape(encoding=0 if kind=='ascii' else 4);metadata={}
 if kind=='unknown':files[11],files[12]=b'Unknown saved directory',b'Opaque values'
 if kind=='unverified':metadata['source_identity_matches']=False
 if kind=='output':files=with_output(files)
 if kind=='serial':metadata['connector_config']={'transport':'mstp','serial_port':'owned-unopened'}
 _,records,_,request=source(Path(sys.argv[1]),files=files,**metadata)
 report=records.capabilities(request|{'capability_profile':PROFILE})
 rows[kind]={'id':request['capture_id'],'report':report,'archive':{k:report[k] for k in ['capture_id','snapshot_sha256','sha256','target','files']}}
print(json.dumps(rows))
`,
      directory,
    ),
  );
}
