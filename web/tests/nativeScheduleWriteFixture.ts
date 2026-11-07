import { test as base } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { createServer } from "node:net";
import path from "node:path";
export { expect } from "@playwright/test";
export type { Page, APIRequestContext } from "@playwright/test";

const startup = `
import hashlib,json,os,sys
from pathlib import Path
import bms_tool
from bms_tool import resources
installed=os.environ.get('BMS_TEST_INSTALLED_TARGET','')
if installed:
 root=Path(installed).resolve()
 assert Path(bms_tool.__file__).resolve().is_relative_to(root)
 assert not resources.source_checkout()
 assert resources.web_directory().is_relative_to(root)
 manifest=json.loads((root/'bms_tool/data/distribution.json').read_text())
 expected=os.environ.get('BMS_EXPECTED_SOURCE')
 if expected:assert manifest['source_commit']==expected
 for name,digest in manifest['ui_files'].items():assert hashlib.sha256((root/'bms_tool/web_assets'/name).read_bytes()).hexdigest()==digest
print(json.dumps({'native_schedule_write_fixture':'installed' if installed else 'source','package':bms_tool.__file__,'web':str(resources.web_directory())}),flush=True)
from bms_tool.app import create_app
import uvicorn
app=create_app()
if os.environ.get('BMS_TEST_HOLD_PULSE_IMPORT')=='1':
 # Delay delivery after the browser's original multipart upload has been processed.
 # Replaying multipart with route.fetch can change file bytes in WebKit.
 import asyncio
 from starlette.responses import Response
 @app.middleware('http')
 async def hold_pulse_import(request,call_next):
  response=await call_next(request)
  directory=Path(os.environ['BMS_STUDIO_DATA']);gate=directory/'hold-pulse-import'
  if request.url.path=='/api/accumulator-prescale/import' and gate.is_file():
   body=b''.join([chunk async for chunk in response.body_iterator])
   data=json.loads(body)
   (directory/'pulse-import-processed.json').write_text(json.dumps({'status':response.status_code,'file_sha256':data.get('file_sha256'),'response_sha256':hashlib.sha256(body).hexdigest()}))
   while gate.is_file():await asyncio.sleep(.005)
   return Response(body,status_code=response.status_code,headers=dict(response.headers),background=response.background)
  return response
if os.environ.get('BMS_TEST_BUNDLE_INSPECTION')=='1':
 # Inspect the original multipart request once. Capture/hold only its response;
 # browser route.fetch can replay multipart differently in WebKit.
 import asyncio
 from starlette.responses import Response
 @app.middleware('http')
 async def observe_bundle_inspection(request,call_next):
  response=await call_next(request)
  if request.url.path=='/api/bacnet/controller/native-application/default-batch/result/inspect-evidence':
   body=b''.join([chunk async for chunk in response.body_iterator])
   directory=Path(os.environ['BMS_STUDIO_DATA'])
   with (directory/'bundle-inspection-response-observations.jsonl').open('a') as evidence:
    evidence.write(json.dumps({'method':request.method,'path':request.url.path,'status':response.status_code,'bytes':len(body)})+chr(10))
   if request.method!='POST':
    return Response(body,status_code=response.status_code,headers=dict(response.headers),background=response.background)
   (directory/'bundle-inspection-original-response.json').write_bytes(body)
   gate=directory/'hold-bundle-inspection'
   while gate.is_file():await asyncio.sleep(.005)
   replacement=directory/'bundle-inspection-response-override.json'
   if replacement.is_file():body=replacement.read_bytes()
   (directory/'bundle-inspection-response.json').write_bytes(body)
   headers=dict(response.headers);headers.pop('content-length',None)
   return Response(body,status_code=response.status_code,headers=headers,background=response.background)
  return response
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[1]),access_log=False)
`;
async function freePort(): Promise<number> {
  const socket = createServer();
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const address = socket.address(),
        port = address && typeof address !== "string" ? address.port : 0;
      socket.close(() => resolve(port));
    });
  });
}
/** Each test owns its history, capture quota and fault-injection files. */
export const test = base.extend<{
  nativeScheduleWriteServer: { url: string; directory: string };
  holdPulseImport: boolean;
  observeBundleInspection: boolean;
}>({
  holdPulseImport: [false, { option: true }],
  observeBundleInspection: [false, { option: true }],
  nativeScheduleWriteServer: [
    async ({ holdPulseImport, observeBundleInspection }, use) => {
      const root = path.resolve(".."),
        port = await freePort(),
        directory = mkdtempSync(
          path.join(tmpdir(), "bms-native-write-fixture-"),
        ),
        installed = process.env.BMS_TEST_INSTALLED_TARGET?.trim()
          ? path.resolve(process.env.BMS_TEST_INSTALLED_TARGET.trim())
          : "",
        url = `http://127.0.0.1:${port}`,
        child = spawn(
          path.join(root, ".venv/bin/python"),
          ["-u", "-c", startup, String(port)],
          {
            cwd: installed ? directory : root,
            env: {
              ...process.env,
              BMS_STUDIO_DATA: directory,
              BMS_TEST_INSTALLED_TARGET: installed,
              BMS_TEST_HOLD_PULSE_IMPORT: holdPulseImport ? "1" : "",
              BMS_TEST_BUNDLE_INSPECTION: observeBundleInspection ? "1" : "",
              PYTHONPATH:
                installed ||
                [path.join(root, "backend"), root].join(path.delimiter),
            },
            stdio: ["ignore", "pipe", "pipe"],
          },
        );
      let errors = "";
      child.stdout.on("data", (data) => process.stdout.write(data));
      child.stderr.on("data", (data) => (errors += data.toString()));
      child.on("error", (error) => (errors += String(error)));
      try {
        const deadline = Date.now() + 10000;
        let ready = false;
        while (Date.now() < deadline && child.exitCode === null) {
          try {
            ready = (await fetch(url + "/api/session")).ok;
          } catch {
            /* startup */
          }
          if (ready) break;
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (!ready)
          throw new Error(
            "Owned native write server failed to start: " + errors,
          );
        await use({ url, directory });
      } finally {
        if (child.exitCode === null) {
          const stopped = new Promise<void>((resolve) =>
            child.once("exit", () => resolve()),
          );
          child.kill("SIGTERM");
          let timer: ReturnType<typeof setTimeout>;
          await Promise.race([
            stopped,
            new Promise((resolve) => (timer = setTimeout(resolve, 3000))),
          ]);
          clearTimeout(timer!);
          if (child.exitCode === null) child.kill("SIGKILL");
        }
      }
    },
    { scope: "test" },
  ],
  baseURL: async ({ nativeScheduleWriteServer }, use) =>
    use(nativeScheduleWriteServer.url),
});
