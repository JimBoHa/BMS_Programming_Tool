import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { mkdtempSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { withOwnedPowerProcess } from "./operationPowerOwnedProcess.mjs";
export { expect };
export type { Page, Locator } from "@playwright/test";
const root = fileURLToPath(new URL("../..", import.meta.url));
type Server = { origin: string; identity: string };

async function freePort() {
  const server = createServer();
  return new Promise<number>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string")
        return reject(new Error("Missing owned power fixture TCP port"));
      server.close((error) => (error ? reject(error) : resolve(address.port)));
    });
  });
}

export const test = base.extend<
  { powerIdentity: string },
  { powerServer: Server }
>({
  powerServer: [
    async ({ playwright }, use, worker) => {
      const state = mkdtempSync(path.join(tmpdir(), "bms-power-owned-ui-")),
        port = await freePort(),
        origin = `http://127.0.0.1:${port}`;
      const identityDir =
        process.env.BMS_UI_POWER_IDENTITY_DIR ||
        path.join(worker.project.outputDir, "power-fixture-identities");
      mkdirSync(identityDir, { recursive: true });
      const identity = path.resolve(
        identityDir,
        `${worker.project.name}-${worker.workerIndex}.json`,
      );
      const python =
        process.env.BMS_UI_POWER_PYTHON || path.join(root, ".venv/bin/python");
      const library = path.join(root, ".venv/lib"),
        versions = process.env.BMS_UI_POWER_DEPENDENCY_ROOT
          ? []
          : readdirSync(library).filter((name) =>
              /^python\d+\.\d+$/.test(name),
            );
      if (!process.env.BMS_UI_POWER_DEPENDENCY_ROOT && versions.length !== 1)
        throw new Error(
          "Power fixture requires one explicit Python dependency root",
        );
      const environment: NodeJS.ProcessEnv = {
        ...process.env,
        BMS_STUDIO_DATA: state,
        BMS_UI_POWER_SERVER_PORT: String(port),
        BMS_UI_POWER_HELPER_PATH: path.join(
          root,
          "web/tests/operation_power_server.py",
        ),
        BMS_UI_POWER_IDENTITY_PATH: identity,
        BMS_UI_POWER_DEPENDENCY_ROOT:
          process.env.BMS_UI_POWER_DEPENDENCY_ROOT ||
          path.join(library, versions[0], "site-packages"),
      };
      if (!process.env.BMS_TEST_INSTALLED_TARGET)
        Object.assign(environment, {
          BMS_UI_POWER_BACKEND_ROOT: path.join(root, "backend"),
        });
      else delete environment.BMS_UI_POWER_BACKEND_ROOT;
      // The isolated child owns all application/dependency paths in its bootstrap.
      // Inherited PYTHONPATH may intentionally refer to ordinary source helpers.
      delete environment.PYTHONPATH;
      delete environment.BMS_SERVER_IDENTITY_PATH;
      const child = spawn(
        python,
        [
          "-I",
          "-S",
          path.join(root, "web/tests/operation_power_server_bootstrap.py"),
        ],
        { cwd: state, env: environment, stdio: ["ignore", "pipe", "pipe"] },
      );
      let output = "";
      let spawnError: Error | null = null;
      child.once("error", (error) => {
        spawnError = error;
      });
      child.stdout?.on(
        "data",
        (bytes) => (output = (output + String(bytes)).slice(-65536)),
      );
      child.stderr?.on(
        "data",
        (bytes) => (output = (output + String(bytes)).slice(-65536)),
      );
      let client: Awaited<
        ReturnType<typeof playwright.request.newContext>
      > | null = null;
      await withOwnedPowerProcess(
        {
          child,
          state,
          identity,
          output: () => output,
          metadata: {
            origin,
            bootstrap: path.join(
              root,
              "web/tests/operation_power_server_bootstrap.py",
            ),
            installed_target: process.env.BMS_TEST_INSTALLED_TARGET ?? null,
          },
          dispose: async () => {
            if (client) await client.dispose();
          },
        },
        async () => {
          client = await playwright.request.newContext();
          const deadline = Date.now() + 8000;
          let ready = false;
          while (Date.now() < deadline) {
            if (spawnError) throw spawnError;
            if (child.exitCode !== null || child.signalCode !== null)
              throw new Error("Power fixture exited during startup: " + output);
            try {
              const response = await client.get(origin + "/api/session", {
                timeout: 300,
              });
              if (response.ok()) {
                ready = true;
                break;
              }
            } catch {}
            await new Promise((resolve) => setTimeout(resolve, 50));
          }
          if (!ready)
            throw new Error(
              "Power fixture startup exceeded its bound: " + output,
            );
          const proof = JSON.parse(readFileSync(identity, "utf8"));
          expect(proof.status).toBe("passed");
          expect(proof.mode).toBe(
            process.env.BMS_TEST_INSTALLED_TARGET ? "installed" : "source",
          );
          expect(proof.source_checkout).toBe(
            !process.env.BMS_TEST_INSTALLED_TARGET,
          );
          expect(
            proof.isolated && proof.no_site && proof.no_pth_processing,
          ).toBe(true);
          await use({ origin, identity });
        },
      );
    },
    { scope: "worker" },
  ],
  baseURL: async ({ powerServer }, use) => {
    await use(powerServer.origin);
  },
  powerIdentity: async ({ powerServer }, use) => {
    await use(powerServer.identity);
  },
});
