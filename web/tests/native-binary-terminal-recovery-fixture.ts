import { python } from "./native-connection-fixture";
import { expect, type Page, type Locator } from "@playwright/test";
import { chooseWorkspaceTask } from "./workspace-navigation";

export function seed(directory: string, variant = "standard") {
  return JSON.parse(
    python(
      `
from pathlib import Path
import json,sys
from tests.test_native_binary_terminal_recovery import setup, saved_unsigned, changed_saved, without_optional
from tests.test_native_terminal_labels import observed_shape
from tests.test_native_signal_compiler import retained
from bms_tool.native_inputs import NativeInputCompiler
from bms_tool.app import create_app
variant=sys.argv[2]
original=observed_shape(compressed=True)
if variant=='no-optional':original=without_optional(original,(15,33,84))
if variant=='fresh-counters':
 original,first=saved_unsigned(original,15,77)
 original,second=saved_unsigned(original,33,90000)
storage,recovery,query,before,files,_=setup(Path(sys.argv[1]),files=original)
if variant in ('fresh-counters','already'):
 if variant=='fresh-counters':files=changed_saved(changed_saved(files,first,4294967295),second,0)
 else:files={**files,3:NativeInputCompiler(original).app.source}
 current=retained(storage,files,identity=before['identity'])
 query|={'capture_id':current['id'],'snapshot_sha256':current['evidence_sha256']}
app=create_app(Path(sys.argv[1]));service=app.state.native_applications
source=service.binary_input_source(capture_id=query['capture_id'],snapshot_sha256=query['snapshot_sha256'])
report=recovery.prepare(query)
parent=storage.receipt(query['receipt_id'])['intent']
output,local=service.input_copy(**report['proposal']) if report['proposal'] else (None,None)
from bms_tool.native_binary_terminal_recovery_transfer import BinaryTerminalRecoveryPreview,recovery_origin
lineage=None
if report['proposal']:
 options=BinaryTerminalRecoveryPreview(**report['source']['target'],**report['proposal'],operation_id='authored-recovery-contract',binary_terminal_recovery_parent_receipt=parent['id'],binary_terminal_recovery_origin_sha256=report['origin_sha256'])
 lineage=recovery_origin(service,options,local['compilation'])
import base64
print(json.dumps({'id':query['capture_id'],'parent':parent,'report':report,'source':source,'text':json.dumps(report,ensure_ascii=False),'lineage':lineage,'output':base64.b64encode(output).decode() if output else None}))`,
      directory,
      variant,
    ),
  );
}
export async function offline(page: Page, f: any, caf = false) {
  await page.goto("/");
  if (caf)
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "binary-recovery.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(
          python(
            "from tests.test_caf_graph import make_graph;import base64;print(base64.b64encode(make_graph()).decode())",
          ),
          "base64",
        ),
      });
  else
    await page
      .getByRole("button", { name: "New application", exact: true })
      .click();
  await chooseWorkspaceTask(page, "Points & I/O");
  const inputs = page.getByRole("region", {
    name: "Native input configuration",
    exact: true,
  });
  await inputs
    .getByLabel("Retained native input source", { exact: true })
    .selectOption(f.id);
  await inputs.getByLabel("Engineering range high", { exact: true }).fill("9.");
  const binary = inputs.getByLabel("Binary input terminal movement", {
    exact: true,
  });
  await binary.locator(":scope > summary").click();
  await expect(
    binary.getByLabel("Configured binary input", { exact: true }),
  ).toBeVisible();
  await binary
    .getByLabel("Configured binary input", { exact: true })
    .selectOption("binary-input,101");
  await binary
    .getByLabel("Binary terminal destination", { exact: true })
    .selectOption("2");
  return { inputs, binary };
}
export async function prepare(binary: Locator, parentId: string) {
  const recovery = binary.getByLabel("Previous configured binary terminal", {
    exact: true,
  });
  if ((await recovery.getAttribute("open")) === null)
    await recovery.locator(":scope > summary").click();
  await recovery
    .getByLabel("Previous configured binary transfer receipt", { exact: true })
    .selectOption(parentId);
  await recovery
    .getByRole("button", {
      name: "Prepare previous binary terminal",
      exact: true,
    })
    .click();
  return recovery;
}

import { spawn } from "node:child_process";
import path from "node:path";
/** A separately owned peer exposes changing saved binary counters without any site address. */
export async function binaryRecoveryPeer() {
  const root = path.resolve(".."),
    child = spawn(
      path.join(root, ".venv/bin/python"),
      [
        "-u",
        "-c",
        `
import asyncio,json,sys
from tests.test_native_applications import NativePeer,port
from tests.test_native_binary_terminal_transfer import binary_peer,with_counter,tick
from tests.test_native_binary_terminal_recovery import saved_unsigned
from tests.test_native_default_transfer import NativeRouter
from bms_tool.native_binary_terminal import BinaryTerminalCompiler
from bms_tool.native_inputs import NativeInputCompiler
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
async def main():
 p=port();app=NativePeer.from_object_list([DeviceObject(objectIdentifier=('device',5136),objectName='Authored controller',vendorIdentifier=5),NetworkPortObject(f'127.0.0.1:{p}',objectIdentifier=('network-port',1),objectName='Owned binary recovery peer')]);app.setup()
 binary_peer((app,None,None,None,None));app.files,first=with_counter(app.files);app.files,second=saved_unsigned(app.files,33,90000)
 transport,proxy=await asyncio.get_running_loop().create_datagram_endpoint(lambda:NativeRouter(('127.0.0.1',p)),local_addr=('127.0.0.1',0))
 print('READY '+json.dumps({'direct':f'127.0.0.1:{p}','router':proxy.endpoint}),flush=True)
 def command():
  line=sys.stdin.readline().strip()
  if not line:return
  if line.startswith('mode '):app.mode=line[5:]
  elif line.startswith('counters '):
   _,a,b=line.split();tick(app,first,int(a));tick(app,second,int(b))
  elif line!='stats':raise AssertionError('Unknown owned binary command')
  row=BinaryTerminalCompiler(NativeInputCompiler(app.files)).source()['inputs'][0]
  print('RESULT '+json.dumps({'command':line,'events':app.events,'router_errors':proxy.errors,'counters':row['captured_counter_values'],'slot':row['slot']}),flush=True)
 asyncio.get_running_loop().add_reader(sys.stdin.fileno(),command)
 try:await asyncio.Event().wait()
 finally:transport.close();app.close()
asyncio.run(main())
`,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
        },
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
  let errors = "",
    buffer = "";
  const pending: {
    command: string;
    resolve: (v: any) => void;
    reject: (e: Error) => void;
    timer: ReturnType<typeof setTimeout>;
  }[] = [];
  child.stderr.on("data", (value) => {
    errors = (errors + value).slice(-8192);
  });
  const endpoints = await new Promise<{ direct: string; router: string }>(
    (resolve, reject) => {
      let ready = false;
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("Owned binary peer startup: " + errors));
      }, 10000);
      child.stdout.on("data", (value) => {
        buffer += String(value);
        while (buffer.includes("\n")) {
          const end = buffer.indexOf("\n"),
            line = buffer.slice(0, end);
          buffer = buffer.slice(end + 1);
          if (line.startsWith("READY ") && !ready) {
            ready = true;
            clearTimeout(timer);
            resolve(JSON.parse(line.slice(6)));
          } else if (line.startsWith("RESULT ")) {
            const data = JSON.parse(line.slice(7)),
              index = pending.findIndex((p) => p.command === data.command);
            if (index >= 0) {
              const [p] = pending.splice(index, 1);
              clearTimeout(p.timer);
              p.resolve(data);
            }
          }
        }
      });
      child.once("error", reject);
      child.once("exit", (code) => {
        clearTimeout(timer);
        if (!ready)
          reject(new Error(`Owned binary peer exited ${code}: ${errors}`));
        for (const p of pending.splice(0)) {
          clearTimeout(p.timer);
          p.reject(new Error("Owned binary peer exited: " + errors));
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
                "Owned binary peer command timeout: " + command + ": " + errors,
              ),
            ),
          5000,
        );
        pending.push({ command, resolve, reject, timer });
        child.stdin.write(command + "\n");
      }),
    close: () => child.kill("SIGTERM"),
  };
}
