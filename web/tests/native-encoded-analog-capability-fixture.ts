import { python } from "./native-connection-fixture";
export function seedEncodedAnalogCapabilities(directory: string) {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_terminal_capabilities import source
from tests.test_native_terminal_labels import observed_shape
from tests.test_native_encoded_terminal_input import nonlinear,replaced
from tests.test_controller_application import encoded
from tests.test_moi_terminal_output_namespace import with_output
from bacpypes3.primitivedata import Unsigned,Real
from bms_tool.native_encoded_analog_capabilities import PROFILE
rows={}
for kind in ['ucs2','ascii','linear','unknown','unverified','serial','output','binary','configuration','endpoint']:
 files=observed_shape(encoding=0 if kind=='ascii' else 4,binary=kind=='binary');metadata={}
 if kind not in ('binary','linear'):files=nonlinear(files)
 if kind=='unknown':files[11],files[12]=b'Unknown saved directory',b'Opaque values'
 if kind=='unverified':metadata['source_identity_matches']=False
 if kind=='serial':metadata['connector_config']={'transport':'mstp','serial_port':'owned-unopened'}
 if kind=='output':files=with_output(files)
 if kind=='configuration':files=replaced(files,{518:encoded(Unsigned(1))})
 if kind=='endpoint':files=replaced(files,{1295:encoded(Real(0))})
 _,records,_,request=source(Path(sys.argv[1]),files=files,**metadata)
 report=records.capabilities(request|{'capability_profile':PROFILE})
 rows[kind]={'id':request['capture_id'],'report':report,'archive':{k:report[k] for k in ['capture_id','snapshot_sha256','sha256','target','files']}}
print(json.dumps(rows))
`,
      directory,
    ),
  );
}
