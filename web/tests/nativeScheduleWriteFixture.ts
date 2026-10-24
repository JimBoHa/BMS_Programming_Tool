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
uvicorn.run(create_app(),host='127.0.0.1',port=int(sys.argv[1]),access_log=False)
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
/** Exact state ownership permits faulting one actual intent without touching shared history. */
export const test = base.extend<
  {},
  { nativeScheduleWriteServer: { url: string; directory: string } }
>({
  nativeScheduleWriteServer: [
    async ({}, use) => {
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
    { scope: "worker" },
  ],
  baseURL: async ({ nativeScheduleWriteServer }, use) =>
    use(nativeScheduleWriteServer.url),
});
