import { python } from "./caf-native-fixture";
export function seedBatchEvidence(directory: string, kind = "valid") {
  return JSON.parse(
    python(
      `
import asyncio,base64,json,sys,pytest
from pathlib import Path
from tests.test_native_applications import native_link
from tests.test_native_default_batch_evidence import evidence_source
from tests.test_caf_graph import make_graph
from bms_tool.native_default_batch_evidence import NativeDefaultBatchEvidence
from bms_tool.native_default_batch import NativeDefaultBatch
from bms_tool.native_signal_compiler import SignalCompilerService
async def main():
 patch=pytest.MonkeyPatch();gen=native_link.__wrapped__(Path(sys.argv[1]),patch);link=await anext(gen)
 try:
  native=link[3];receipt,args,report=await evidence_source(link,sys.argv[2])
  raw,metadata=NativeDefaultBatchEvidence(native.default_batch_recovery.records).export(args)
  source=SignalCompilerService(native.storage).source(args['capture_id'])
  opened=NativeDefaultBatch(native.default_batch_recovery.records).source({k:args[k] for k in ['capture_id','snapshot_sha256']})
  print(json.dumps(dict(id=receipt['intent']['id'],request=args,receipt=receipt,report=report,source=source,opened=opened,bundle=base64.b64encode(raw).decode(),metadata=metadata,caf=base64.b64encode(make_graph()).decode())))
 finally:await gen.aclose();patch.undo()
asyncio.run(main())
`,
      directory,
      kind,
    ),
  );
}

export function alteredBatchEvidence(fixture: any, fault: string) {
  return JSON.parse(
    python(
      `
import base64,io,json,stat,sys,zipfile
from bms_tool.application_store import encoded
from bms_tool.moi_identity import seal,sha
raw=base64.b64decode(sys.argv[1]);metadata=json.loads(sys.argv[2]);fault=sys.argv[3]
with zipfile.ZipFile(io.BytesIO(raw)) as archive:members={name:archive.read(name) for name in archive.namelist()}
manifest=json.loads(members.pop('manifest.json'))
if fault=='manifest-authority':manifest['can_apply']=True
elif fault=='manifest-source':manifest['current_capture_id']='a'*32
elif fault=='manifest-snapshot':manifest['captures'][metadata['current_capture_id']]='a'*64
elif fault=='manifest-member-hash':manifest['members']['proof.json']['sha256']='a'*64
elif fault=='manifest-member-bytes':manifest['members']['proof.json']['bytes']+=1
elif fault=='manifest-extra':manifest['unknown']=True
elif fault in ('proof-body','intent-body','comparison-body'):
 name={'proof-body':'proof.json','intent-body':'intent.json','comparison-body':'comparison.json'}[fault]
 body=json.loads(members[name]);body['unexpected']=True;members[name]=encoded(body)
 manifest['members'][name]={'bytes':len(members[name]),'sha256':sha(members[name])}
elif fault=='member-path':
 members['../intent.json']=members.pop('intent.json');manifest['members']['../intent.json']=manifest['members'].pop('intent.json')
manifest['evidence_sha256']='a'*64 if fault=='manifest-seal' else seal({k:v for k,v in manifest.items() if k!='evidence_sha256'})
manifest_bytes=encoded(manifest);metadata['manifest_sha256']=sha(manifest_bytes)
output=io.BytesIO()
with zipfile.ZipFile(output,'w',zipfile.ZIP_STORED) as archive:
 archive.writestr('manifest.json',manifest_bytes)
 for name,data in sorted(members.items()):
  if fault=='symlink' and name=='proof.json':
   info=zipfile.ZipInfo(name);info.external_attr=(stat.S_IFLNK|0o777)<<16;archive.writestr(info,data)
  else:archive.writestr(name,data)
raw=output.getvalue();metadata.update(bytes=len(raw),bundle_sha256=sha(raw))
print(json.dumps(dict(bundle=base64.b64encode(raw).decode(),metadata=metadata)))
`,
      fixture.bundle,
      JSON.stringify(fixture.metadata),
      fault,
    ),
  );
}
