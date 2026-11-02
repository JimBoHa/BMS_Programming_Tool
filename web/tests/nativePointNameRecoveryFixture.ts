import { python } from "./caf-native-fixture";

export function seedPointRecovery(directory: string) {
  return JSON.parse(
    python(
      `
import sys,json,base64
from tests.test_native_point_name_recovery import setup
from tests.test_caf_native_correlation import caf_source
from bms_tool.native_point_names import PointNameCompiler
identity={'device':'device,5136','object-name':'Authored controller','vendor-identifier':5,'model-name':'UNLISTED-MODEL'}
s,service,request,before,files=setup(sys.argv[1],identity=identity)
manifest=s.load(request['capture_id'])[0]
capture=manifest|{'snapshot_evidence_sha256':manifest['evidence_sha256'],'source_identity_matches':True,'instance_edit_supported':True}
print(json.dumps({'request':request,'capture':capture,'field':PointNameCompiler(files).fields()[0],'receipt':s.receipt(request['receipt_id']),'report':service.prepare(request),'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
    ),
  );
}
