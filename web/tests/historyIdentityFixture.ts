import { test as base } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { createServer } from "node:net";
import path from "node:path";

export { expect } from "@playwright/test";
export type { Page, APIRequestContext } from "@playwright/test";

async function freePort(): Promise<number> {
  const socket = createServer();
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.listen(0, "127.0.0.1", () => {
      const address = socket.address();
      const port = address && typeof address !== "string" ? address.port : 0;
      socket.close(() => resolve(port));
    });
  });
}

/** Each worker owns its seeded SQLite server; no shared API history is cleared. */
export const test = base.extend<{}, { historyIdentityServer: string }>({
  historyIdentityServer: [
    async ({ browserName }, use) => {
      if (browserName !== "chromium" && browserName !== "webkit")
        throw new Error(
          "History identity fixture supports Chromium and WebKit lanes only.",
        );
      const root = path.resolve(".."),
        port = await freePort(),
        directory = mkdtempSync(path.join(tmpdir(), "bms-history-id-fixture-")),
        installed = process.env.BMS_TEST_INSTALLED_TARGET?.trim()
          ? path.resolve(process.env.BMS_TEST_INSTALLED_TARGET.trim())
          : "",
        url = `http://127.0.0.1:${port}`,
        child = spawn(
          path.join(root, ".venv/bin/python"),
          [
            path.join(root, "tests/history_identity_fixture.py"),
            "--port",
            String(port),
          ],
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
      child.stderr.on("data", (data) => {
        errors += data.toString();
      });
      child.on("error", (error) => {
        errors += String(error);
      });
      try {
        const deadline = Date.now() + 10000;
        let ready = false;
        while (Date.now() < deadline && child.exitCode === null) {
          try {
            ready = (await fetch(url + "/api/session")).ok;
          } catch {
            /* Server is starting. */
          }
          if (ready) break;
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (!ready)
          throw new Error("Isolated history server failed to start: " + errors);
        await use(url);
      } finally {
        if (child.exitCode === null) {
          const stopped = new Promise<void>((resolve) =>
            child.once("exit", () => resolve()),
          );
          child.kill("SIGTERM");
          let timer: ReturnType<typeof setTimeout>;
          await Promise.race([
            stopped,
            new Promise((resolve) => {
              timer = setTimeout(resolve, 3000);
            }),
          ]);
          clearTimeout(timer!);
          if (child.exitCode === null) child.kill("SIGKILL");
        }
      }
    },
    { scope: "worker" },
  ],
  baseURL: async ({ historyIdentityServer }, use) => use(historyIdentityServer),
});
