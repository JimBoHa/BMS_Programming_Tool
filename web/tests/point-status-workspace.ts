import { expect, type Page } from "@playwright/test";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freePort } from "./workflow-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";

const root = fileURLToPath(new URL("../..", import.meta.url));

export { disconnectTestInterface as disconnectPointInterface } from "./workflow-peer";

export async function startPointPeer(routed = false, behavior = "normal") {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-m",
      "tests.browser_point_status_peer",
      routed ? "1" : "0",
      behavior,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let count = 0;
  let acknowledgeHold!: () => void;
  const holding = new Promise<void>((resolve) => {
    acknowledgeHold = resolve;
  });
  const port = await new Promise<number>((resolve, reject) => {
    let pending = "",
      error = "",
      ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Point peer startup " + error));
    }, 5000);
    child.stderr!.on("data", (value) => {
      error += String(value);
    });
    child.stdout!.on("data", (value) => {
      pending += String(value);
      while (pending.includes("\n")) {
        const end = pending.indexOf("\n"),
          line = pending.slice(0, end);
        pending = pending.slice(end + 1);
        if (!ready) {
          ready = true;
          clearTimeout(timer);
          resolve(Number(line));
        } else if (line === "READ") count++;
        else if (line === "HOLDING") acknowledgeHold();
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Point peer exited ${code}: ${error}`));
    });
  });
  return {
    async stop() {
      if (child.exitCode !== null || child.signalCode !== null) return;
      const stopped = new Promise<void>((resolve) =>
        child.once("exit", () => resolve()),
      );
      child.kill();
      await stopped;
    },
    port,
    reads: () => count,
    hold() {
      child.stdin.write("hold\n");
      return holding;
    },
  };
}
async function selectController(
  page: Page,
  server: { port: number },
  routed = false,
) {
  const endpoint = `127.0.0.1:${server.port}`;
  const address = routed ? "3001:7" : endpoint;
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  const form = page.getByRole("region", {
    name: "Known controller connection",
  });
  await form
    .getByLabel("Known controller address", { exact: true })
    .fill(address);
  await form
    .getByLabel("Known Device object", { exact: true })
    .fill("device,42");
  await form
    .getByLabel("Known router", { exact: true })
    .fill(routed ? endpoint : "");
  await form
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  await form
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText("Native device,42");
  const inventory = page.waitForResponse((r) =>
    r.url().endsWith("/api/bacnet/controller/inventory"),
  );
  await chooseWorkspaceTask(page, "Points & I/O");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  const compact = tools.getByRole("combobox", {
    name: "Controller task tools",
    exact: true,
  });
  if (await compact.isVisible())
    await compact.selectOption({ label: "Detailed point evidence" });
  else
    await tools
      .getByRole("button", { name: "Detailed point evidence", exact: true })
      .click();
  expect(await (await inventory).json()).toMatchObject({
    complete: true,
    identity_verified: true,
    target: {
      address,
      device: "device,42",
      router: routed ? endpoint : null,
      dnet: routed ? 3001 : null,
    },
  });
  const panel = page.getByRole("region", {
    name: "Native point status inspection",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Inspect native point status",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(page.getByLabel("Working context")).toContainText(address);
  await expect(
    panel.getByLabel("Point-status source address", { exact: true }),
  ).toHaveCount(0);
  await panel
    .getByLabel("Selected native points", { exact: true })
    .fill("analog-input,1; analog-output,2");
  return panel;
}
export async function openPointInspection(
  page: Page,
  server: { port: number },
  routed = false,
) {
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  return selectController(page, server, routed);
}
export async function changePointController(
  page: Page,
  server: { port: number },
) {
  await page
    .getByLabel("Working context")
    .getByRole("button", { name: "Change controller", exact: true })
    .click();
  return selectController(page, server);
}
export async function readPointStatus(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", { name: "Inspect native point status", exact: true })
    .click();
  await expect(
    panel.getByLabel("Native point evidence report", { exact: true }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Cancel point inspection", exact: true }),
  ).toBeDisabled();
}
