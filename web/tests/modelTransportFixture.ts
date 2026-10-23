import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { test as base, expect } from "@playwright/test";
import { cleanupPeers } from "./modelTransportCleanup";
const root = fileURLToPath(new URL("../..", import.meta.url));
const python = path.join(root, ".venv/bin/python");
const dependency = execFileSync(
  python,
  ["-I", "-c", "import sysconfig;print(sysconfig.get_paths()['purelib'])"],
  { encoding: "utf8" },
).trim();
export { expect };
export const test = base.extend<{
  modelPeer: (model?: string, routed?: boolean) => Promise<any>;
}>({
  modelPeer: async ({ request }, use, info) => {
    const children: any[] = [];
    let primaryError: unknown;
    try {
      await use(async (model = "MS-FAC4911-0", routed = false) => {
        const installed = process.env.BMS_TEST_INSTALLED_TARGET?.trim(),
          expected = installed
            ? path.resolve(installed)
            : path.join(root, "backend");
        const evidence = info.outputPath(`peer-${children.length}.json`);
        const identity = info.outputPath(
          `peer-${children.length}.identity.json`,
        );
        mkdirSync(path.dirname(evidence), { recursive: true });
        const directory = mkdtempSync(path.join(tmpdir(), "bms-model-peer-"));
        const child = spawn(
          python,
          [
            "-I",
            "-S",
            "-u",
            path.join(root, "web/tests/model_transport_peer.py"),
            model,
            routed ? "routed" : "direct",
          ],
          {
            cwd: directory,
            env: {
              ...process.env,
              PYTHONPATH: [expected, root].join(path.delimiter),
              BMS_MODEL_HELPER_ROOT: root,
              BMS_MODEL_EXPECTED_ROOT: expected,
              BMS_MODEL_EVIDENCE: evidence,
              BMS_MODEL_IDENTITY: identity,
              BMS_MODEL_DEPENDENCY_ROOT: dependency,
            },
            stdio: ["pipe", "pipe", "pipe"],
          },
        );
        const owned = {
          child,
          evidence,
          identity,
          directory,
          expectReads: false,
        };
        children.push(owned);
        let stderr = "",
          stdout = "";
        child.stderr.on("data", (d) => (stderr += String(d)));
        const peer = await new Promise<any>((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error("Peer startup exceeded10s: " + stderr)),
            10000,
          );
          child.on("error", (e) => {
            clearTimeout(timer);
            reject(e);
          });
          child.on("exit", (code) => {
            clearTimeout(timer);
            reject(new Error(`Peer exited ${code}: ${stderr}`));
          });
          child.stdout.on("data", (data) => {
            stdout += String(data);
            const line = stdout
              .split("\n")
              .find((s) => s.startsWith("MODEL_TRANSPORT_PEER="));
            if (line) {
              clearTimeout(timer);
              resolve(JSON.parse(line.slice("MODEL_TRANSPORT_PEER=".length)));
            }
          });
        });
        const token = (await (await request.get("/api/session")).json()).token;
        const response = await request.post("/api/bacnet/connect", {
          headers: { "X-Studio-Token": token },
          data: { local_address: peer.client_address },
        });
        expect(response.ok(), await response.text()).toBe(true);
        return {
          ...peer,
          token,
          expectReads: () => (owned.expectReads = true),
        };
      });
    } catch (error) {
      primaryError = error;
    } finally {
      try {
        await cleanupPeers(
          children,
          async (owned, retirement) => {
            const { evidence, identity, directory, expectReads } = owned;
            const errors: unknown[] = [];
            const attempt = async <T>(
              work: () => T | Promise<T>,
            ): Promise<T | undefined> => {
              try {
                return await work();
              } catch (error) {
                errors.push(error);
                return undefined;
              }
            };
            const lifecycle = identity + ".lifecycle.json";
            await attempt(() =>
              writeFileSync(
                lifecycle,
                JSON.stringify(retirement, null, 2) + "\n",
                { flag: "wx" },
              ),
            );
            await attempt(() => expect(retirement.reaped).toBe(true));
            await attempt(() =>
              expect(retirement.normal_stdin_shutdown).toBe(true),
            );
            const proof = await attempt(() =>
              JSON.parse(readFileSync(evidence, "utf8")),
            );
            const startup = await attempt(() =>
              JSON.parse(readFileSync(identity, "utf8")),
            );
            const post = await attempt(() =>
              JSON.parse(readFileSync(identity + ".post.json", "utf8")),
            );
            if (proof)
              await attempt(() => {
                if (expectReads)
                  expect(proof.native_reads.length).toBeGreaterThan(0);
                else expect(proof.native_reads).toEqual([]);
                expect(proof.proxy_errors).toEqual([]);
                expect(proof.pending_proxy_clients).toBe(0);
              });
            if (startup && post)
              await attempt(() => {
                expect(startup.phase).toBe("startup");
                expect(post.phase).toBe("post_shutdown");
                expect(post.isolated && post.no_site).toBe(true);
                for (const [name, origin] of Object.entries(
                  startup.loaded_modules,
                ))
                  expect(post.loaded_modules[name]).toBe(origin);
              });
            for (const file of [
              evidence,
              identity,
              identity + ".post.json",
              lifecycle,
            ])
              await attempt(() =>
                info.attach(path.basename(file), {
                  path: file,
                  contentType: "application/json",
                }),
              );
            if (retirement.reaped)
              await attempt(() => rmSync(directory, { recursive: true }));
            if (errors.length)
              throw new AggregateError(
                errors,
                "Owned peer evidence/temporary-directory cleanup failed",
              );
          },
          async () => {
            const token = (await (await request.get("/api/session")).json())
              .token;
            const response = await request.post("/api/bacnet/disconnect", {
              headers: { "X-Studio-Token": token },
              data: {},
            });
            expect(response.ok(), await response.text()).toBe(true);
          },
        );
      } catch (cleanupError) {
        if (primaryError !== undefined)
          throw new AggregateError(
            [primaryError, cleanupError],
            "Primary fixture and cleanup/evidence failures",
          );
        throw cleanupError;
      }
    }
    if (primaryError !== undefined) throw primaryError;
  },
});
