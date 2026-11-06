import { python } from "./native-connection-fixture";
export function seedDefaultBatch(directory: string, extra = 0) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from pathlib import Path
from tests.test_native_default_batch import local,request,batch_files,changes
from tests.test_caf_native_correlation import caf_source
from bms_tool.native_signal_compiler import SignalCompilerService
storage,service,snapshot,query,opened=local(Path(sys.argv[1]),batch_files(extra=int(sys.argv[2])));body=request(query,opened,changes(opened)[:16]);output,review=service.preview(body)
_,_,other,_,_=local(Path(sys.argv[1]),target={'address':'127.0.0.1:47929','router':None,'dnet':None})
print(json.dumps({'id':snapshot['id'],'other':other['id'],'query':query,'source':opened,'signal':SignalCompilerService(storage).source(snapshot['id']),'body':body,'review':review,'output':base64.b64encode(output).decode(),'caf':base64.b64encode(caf_source().original).decode()}))
`,
      directory,
      String(extra),
    ),
  );
}
