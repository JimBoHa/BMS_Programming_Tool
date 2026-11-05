import { python } from "./native-connection-fixture";

export function seedTerminalLabels(directory: string, binary = true) {
  return JSON.parse(
    python(
      `
import base64,json,sys
from pathlib import Path
from bms_tool.moi_identity import seal
from bms_tool.native_terminal_labels import EncodedNativeTerminalCopies,EncodedEffectiveNativeTerminalCopies
from tests.test_native_terminal_labels import observed_shape
from tests.test_native_terminal_copies import setup,proposal
p=Path(sys.argv[1]);binary=sys.argv[2]=='true'
_,old,files,q=setup(p,files=observed_shape(binary=binary,compressed=True))
def bundle(effective):
 s=(EncodedEffectiveNativeTerminalCopies if effective else EncodedNativeTerminalCopies)(old.records)
 source=s.source(q);body=proposal(s,q);output,review=s.preview(body)
 numeric=json.loads(json.dumps(review));numeric['exact_numbers']={'real':1.0,'negative_zero':-0.0,'large':1152921504606846977,'unicode':{'\\ue000':1.0,'\\U00010000':2.0}}
 numeric['review_sha256']=seal({k:v for k,v in numeric.items() if k!='review_sha256'})
 return {'source':source,'proposal':body,'review':review,'text':json.dumps(review),'numeric':json.dumps(numeric),'output':base64.b64encode(output).decode(),'archive':{k:source[k] for k in ('capture_id','snapshot_sha256','sha256','files','target')}}
print(json.dumps({'id':q['capture_id'],'archive':bundle(False),'effective':bundle(True)}))
`,
      directory,
      String(binary),
    ),
  );
}
