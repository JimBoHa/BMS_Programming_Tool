import { test, expect } from "@playwright/test";
import { buildSync } from "esbuild";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createServer, request as forward } from "node:http";
import { networkInterfaces } from "node:os";
import path from "node:path";
import { peer, freePort } from "./workflow-peer";
import { openDiscoveryDetails } from "./discovery-controls";

const backend = "http://127.0.0.1:8766";
const root = path.resolve("..");
const helpers = buildSync({
  stdin: {
    contents:
      'import {sha256Digest,randomUUID} from "./src/browserCrypto"; globalThis.browserCryptoUnderTest={sha256Digest,randomUUID};',
    resolveDir: path.join(root, "web"),
  },
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "es2022",
  write: false,
}).outputFiles[0].text;

async function ordinaryHttpProxy() {
  const address = Object.values(networkInterfaces())
    .flat()
    .find((entry) => entry?.family === "IPv4" && !entry.internal)?.address;
  if (!address)
    throw new Error("LAN acceptance requires a non-loopback IPv4 interface.");
  const server = createServer((incoming, response) => {
    const headers = { ...incoming.headers, host: "127.0.0.1:8766" };
    if (headers.origin) headers.origin = backend;
    const upstream = forward(
      backend + incoming.url,
      {
        method: incoming.method,
        headers,
      },
      (reply) => {
        response.writeHead(reply.statusCode!, reply.headers);
        reply.pipe(response);
      },
    );
    upstream.on("error", () => {
      response.writeHead(502);
      response.end();
    });
    incoming.pipe(upstream);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, address, resolve);
  });
  const listener = server.address();
  if (!listener || typeof listener === "string")
    throw new Error("Missing test listener.");
  return {
    origin: `http://${address}:${listener.port}`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
        server.closeAllConnections();
      }),
  };
}

for (const browserName of ["chromium", "webkit"] as const) {
  test(`ordinary HTTP in ${browserName}: source hashing, offline CAFs and routed reports`, async ({
    playwright,
    request,
  }) => {
    test.setTimeout(90000);
    const proxy = await ordinaryHttpProxy();
    const browser = await playwright[browserName].launch();
    const page = await browser.newPage();
    try {
      const token = (await (await request.get("/api/session")).json()).token;
      const headers = { "X-Studio-Token": token };
      expect(
        (
          await request.post("/api/bacnet/disconnect", { headers, data: {} })
        ).ok(),
      ).toBe(true);
      // A real HTTP proxy preserves multipart file bodies in both engines.
      // Browser crypto properties and secure-context flags are never changed.
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(proxy.origin);
      expect(
        await page.evaluate(() => ({
          secure: isSecureContext,
          digest: typeof crypto.subtle,
          uuid: typeof crypto.randomUUID,
          rng: typeof crypto.getRandomValues,
        })),
      ).toEqual({
        secure: false,
        digest: "undefined",
        uuid: "undefined",
        rng: "function",
      });
      await page.addScriptTag({ content: helpers });
      const primitive = await page.evaluate(async () => {
        const api = (globalThis as any).browserCryptoUnderTest;
        return {
          digest: Array.from(
            new Uint8Array(
              await api.sha256Digest(new TextEncoder().encode("abc")),
            ),
            (v: number) => v.toString(16).padStart(2, "0"),
          ).join(""),
          id: api.randomUUID(),
        };
      });
      expect(primitive.digest).toBe(
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      );
      expect(primitive.id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
      await expect(
        page.getByRole("button", { name: /^Connect to a controller/ }),
      ).toBeVisible();
      const caf = execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
        ],
        {
          cwd: root,
          env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        },
      );
      const choosing = page.waitForEvent("filechooser");
      await page.getByRole("button", { name: /^Open a CAF file/ }).click();
      await (
        await choosing
      ).setFiles({
        name: "Authored-LAN-example.caf",
        mimeType: "application/octet-stream",
        buffer: caf,
      });
      await page
        .getByRole("navigation", { name: "Workspace tasks" })
        .getByRole("button", { name: "Program", exact: true })
        .click();
      await page
        .getByRole("navigation", { name: "CAF application tasks" })
        .getByRole("button", { name: "Logic", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Native CAF graph", exact: true }),
      ).toContainText("4 blocks · 2 connections");
      const save = page.waitForEvent("download");
      await page
        .getByRole("button", { name: "Save CAF copy", exact: true })
        .click();
      expect(await readFile((await (await save).path())!)).toEqual(caf);

      const router = await peer(3001, false, 2, true);
      try {
        await page.route("**/api/bacnet/interfaces", (route) =>
          route.fulfill({
            json: {
              interfaces: [
                {
                  address: "127.0.0.1",
                  name: "Authored loopback",
                  network: "127.0.0.0/8",
                  recommended: true,
                  broadcast_available: true,
                },
              ],
            },
          }),
        );
        await page
          .getByRole("button", { name: "Connect", exact: true })
          .click();
        await page
          .getByLabel("Local bind address / UDP port", { exact: true })
          .fill(`127.0.0.1:${await freePort()}`);
        await page
          .getByRole("button", { name: "Open interface", exact: true })
          .click();
        const panel = page.getByRole("region", {
          name: "Routed BACnet discovery",
          exact: true,
        });
        await openDiscoveryDetails(panel, "Enter an engine IP address instead");
        await panel
          .getByLabel("Discovery router address", { exact: true })
          .fill(router.endpoint);
        await panel
          .getByRole("button", { name: "Read router networks", exact: true })
          .click();
        await panel
          .getByLabel("Commissioning trunk", { exact: true })
          .selectOption("3001");
        await openDiscoveryDetails(panel, "Advanced scan settings");
        await panel
          .getByLabel("Routed response window seconds", { exact: true })
          .fill("1");
        await panel
          .getByRole("button", { name: "Scan controllers", exact: true })
          .click();
        await expect(panel.getByLabel("Controller name lookup")).toContainText(
          "2 of 2 controller names read.",
        );
        const pending = page.waitForEvent("download");
        await panel
          .getByRole("button", {
            name: "Download routed discovery JSON",
            exact: true,
          })
          .click();
        const report = JSON.parse(
          await readFile((await (await pending).path())!, "utf8"),
        );
        expect(report.report_sha256).toBe(
          createHash("sha256")
            .update(JSON.stringify(report.report))
            .digest("hex"),
        );
        expect(report.device_names).toHaveLength(2);
        expect(router.writes).toEqual([]);
      } finally {
        await request.post("/api/bacnet/disconnect", { headers, data: {} });
        router.close();
      }
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
      await proxy.close();
    }
  });
}
