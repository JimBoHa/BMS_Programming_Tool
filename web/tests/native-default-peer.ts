import { spawn } from "node:child_process";
import path from "node:path";

const root = path.resolve("..");
export async function nativeDefaultPeer(
  mode = "consume",
  datatype:
    | "real"
    | "boolean"
    | "wire"
    | "wire-recovery"
    | "instance"
    | "point-name" = "real",
) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys,struct
from tests.test_native_applications import NativePeer,port
from tests.test_native_signal_compiler import signal_files
from tests.test_native_default_transfer import controller_storage,real_slot,NativeRouter
from tests.test_native_boolean_copies import boolean_files,FIRST
from tests.test_native_boolean_transfer import storage_outcome,boolean_slot
from tests.test_native_wire_compiler import wire_files
from bms_tool.mstp import header_crc
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
async def main():
 p=port();app=NativePeer.from_object_list([DeviceObject(objectIdentifier=('device',5136),objectName='Authored controller',vendorIdentifier=5),NetworkPortObject(f'127.0.0.1:{p}',objectIdentifier=('network-port',1),objectName='Owned native default peer')]);app.setup()
 if sys.argv[2]=='wire-recovery':
  from tests.test_native_wire_recovery import FANOUT
  app.files=wire_files(target_class=538,wires=FANOUT);app.metadata['object-name']='Authored native wire controller';app.mode='normal' if sys.argv[1]=='consume' else sys.argv[1]
 elif sys.argv[2]=='point-name':
  from tests.test_native_point_names import point_files,attach_point_reads
  app.files=point_files();attach_point_reads(app,published_old=sys.argv[1]=='published-old')
 elif sys.argv[2]=='wire':
  app.files=wire_files(target_class=538);app.metadata['object-name']='Authored native wire controller';app.mode='normal' if sys.argv[1]=='consume' else sys.argv[1]
 elif sys.argv[2]=='instance':
  from tests.test_native_instance_recovery_transfer import controller_storage as instance_storage
  app.files=signal_files();instance_storage(app);app.mode='normal' if sys.argv[1]=='consume' else sys.argv[1]
 elif sys.argv[2]=='boolean':app.files=boolean_files();storage_outcome(app,mode=sys.argv[1])
 else:app.files=signal_files();controller_storage(app,mode=sys.argv[1])
 router_type=NativeRouter
 if sys.argv[2]=='instance':
  from tests.test_native_instance_recovery_transfer import InstanceRouter
  router_type=InstanceRouter
 transport,proxy=await asyncio.get_running_loop().create_datagram_endpoint(lambda:router_type(('127.0.0.1',p)),local_addr=('127.0.0.1',0))
 print('READY '+json.dumps({'direct':f'127.0.0.1:{p}','router':proxy.endpoint}),flush=True)
 def command():
  line=sys.stdin.readline().strip()
  if not line:return
  if line=='selected43':real_slot(app.files,-10,struct.pack('>f',43))
  elif line=='restore42':
   import types
   app.do_ReinitializeDeviceRequest=types.MethodType(NativePeer.do_ReinitializeDeviceRequest,app);controller_storage(app,bits='42280000')
  elif line=='second17':real_slot(app.files,-5,struct.pack('>f',17.5))
  elif line=='wire-other-fresh':
   real_slot(app.files,0,struct.pack('>f',45));raw=bytearray(app.files[12]);raw[10:12]=b'\\x00'+bytes([header_crc(b'\\x00')^255]);app.files[12]=bytes(raw)
  elif line=='wire-application-changed':
   import gzip
   app.files[3]=gzip.compress(gzip.decompress(app.files[3]).replace(b'Opaque metadata retained',b'Unsafe metadata retained'),mtime=0)
  elif line=='boolean-selected-false':boolean_slot(app.files,FIRST,False)
  elif line=='boolean-restore-true':
   import types
   app.do_ReinitializeDeviceRequest=types.MethodType(NativePeer.do_ReinitializeDeviceRequest,app);storage_outcome(app,value=True)
  elif line=='boolean-second-true':boolean_slot(app.files,'controller/boolean-21',True)
  elif line=='repair':
   if sys.argv[2]=='boolean':boolean_slot(app.files,FIRST,False)
   else:real_slot(app.files,-10,bytes.fromhex('3dcccccd'))
  elif line.startswith('mode '):app.mode=line[5:]
  elif line!='stats':raise AssertionError('Unknown authored command')
  print('RESULT '+json.dumps({'command':line,'events':app.events,'instance':app.instance,'router_errors':proxy.errors,'request_types':[r['type'] for r in proxy.requests]}|({'discovery_requests':proxy.discovery_requests,'discovery_responses':proxy.discovery_responses} if sys.argv[2]=='instance' else {})),flush=True)
 asyncio.get_running_loop().add_reader(sys.stdin.fileno(),command)
 try:await asyncio.Event().wait()
 finally:transport.close();app.close()
asyncio.run(main())
`,
      mode,
      datatype,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let stderr = "",
    output = "";
  const replies: {
    command: string;
    resolve: (data: any) => void;
    reject: (error: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  }[] = [];
  child.stderr!.on("data", (value) => {
    stderr = (stderr + String(value)).slice(-8192);
  });
  const endpoints = await new Promise<{ direct: string; router: string }>(
    (resolve, reject) => {
      let ready = false;
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("Native peer startup: " + stderr));
      }, 10000);
      child.stdout!.on("data", (value) => {
        output += String(value);
        while (output.includes("\n")) {
          const end = output.indexOf("\n"),
            line = output.slice(0, end);
          output = output.slice(end + 1);
          if (line.startsWith("READY ") && !ready) {
            ready = true;
            clearTimeout(timer);
            resolve(JSON.parse(line.slice(6)));
          } else if (line.startsWith("RESULT ")) {
            const data = JSON.parse(line.slice(7)),
              index = replies.findIndex(
                (item) => item.command === data.command,
              );
            if (index >= 0) {
              const [reply] = replies.splice(index, 1);
              clearTimeout(reply.timer);
              reply.resolve(data);
            }
          }
        }
      });
      child.once("error", reject);
      child.once("exit", (code) => {
        clearTimeout(timer);
        if (!ready) reject(new Error(`Native peer exited ${code}: ${stderr}`));
        for (const reply of replies.splice(0)) {
          clearTimeout(reply.timer);
          reply.reject(new Error("Native peer exited: " + stderr));
        }
      });
    },
  );
  return {
    ...endpoints,
    command: (command: string): Promise<any> =>
      new Promise((resolve, reject) => {
        const timer = setTimeout(
          () =>
            reject(
              new Error(
                "Native peer command timeout: " + command + ": " + stderr,
              ),
            ),
          5000,
        );
        replies.push({ command, resolve, reject, timer });
        child.stdin!.write(command + "\n");
      }),
    close: () => child.kill("SIGTERM"),
  };
}
