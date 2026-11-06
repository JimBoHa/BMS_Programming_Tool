import { python } from "./native-connection-fixture";
export const first = "controller/signal-10",
  second = "controller/signal-11";
export function seedRealDrafts(directory: string) {
  return JSON.parse(
    python(
      `
import base64,gzip,json,struct,sys
from bms_tool.storage import Store
from bms_tool.application_store import ApplicationStore
from bms_tool.native_signal_compiler import SignalCompilerService
from tests.test_native_signal_compiler import retained,signal_files
from tests.test_controller_application import encoded,native_record
from tests.test_caf_native_correlation import caf_source
from bacpypes3.primitivedata import CharacterString,ObjectIdentifier,Real
s=ApplicationStore(Store(sys.argv[1]));service=SignalCompilerService(s)
a=retained(s);b=retained(s,target={'address':'127.0.0.1:47829','router':None,'dnet':None})
files=signal_files();raw=bytearray(gzip.decompress(files[3]));raw[10:14]=(int.from_bytes(raw[10:14],'little')+63).to_bytes(4,'little')
for index in range(100,163):
 r=native_record(526,index,[(32527,encoded(CharacterString('controller/extra-'+str(index)))),(75,encoded(ObjectIdentifier((2,index)))),(2390,encoded(CharacterString('Authored spare '+str(index)))),(3113,encoded(Real(3.5)))])
 raw.extend(struct.pack('<H',len(r)+2)+r)
files[3]=gzip.compress(raw,mtime=0);full=retained(s,files)
print(json.dumps({'a':{'id':a['id'],'source':service.source(a['id'])},'b':{'id':b['id'],'source':service.source(b['id'])},'full':{'id':full['id'],'source':service.source(full['id'])},'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
    ),
  );
}
