import { spawn } from "node:child_process";
import { createSocket } from "node:dgram";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { expect, type Page, type APIRequestContext } from "@playwright/test";
const root = fileURLToPath(new URL("../..", import.meta.url));
export async function scheduleTracePeer(routed = false, mode = "normal") {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-m",
      "tests.browser_schedule_trace_peer",
      routed ? "routed" : "direct",
      mode,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let pending = "",
    stderr = "",
    count = 0,
    final: any,
    ready = false;
  let resolveReady!: (endpoint: string) => void,
    rejectReady!: (error: Error) => void;
  const started = new Promise<string>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  const timer = setTimeout(() => {
    child.kill("SIGTERM");
    rejectReady(new Error("Schedule peer startup: " + stderr));
  }, 5000);
  child.stderr.on("data", (data) => {
    stderr += String(data);
  });
  child.stdout.on("data", (data) => {
    pending += String(data);
    while (pending.includes("\n")) {
      const end = pending.indexOf("\n"),
        line = pending.slice(0, end);
      pending = pending.slice(end + 1);
      if (!ready) {
        ready = true;
        clearTimeout(timer);
        resolveReady(JSON.parse(line).endpoint);
      } else if (line === "READ") count++;
      else if (line.startsWith("FINAL ")) final = JSON.parse(line.slice(6));
    }
  });
  const exited = new Promise<number | null>((resolve, reject) => {
    child.once("error", (error) => {
      clearTimeout(timer);
      rejectReady(error);
      reject(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready)
        rejectReady(new Error(`Schedule peer exited ${code}: ${stderr}`));
      resolve(code);
    });
  });
  const endpoint = await started;
  return {
    endpoint,
    reads: () => count,
    async stop() {
      if (child.exitCode === null) child.kill("SIGTERM");
      const timeout = setTimeout(() => child.kill("SIGKILL"), 5000);
      try {
        expect(await exited, stderr).toBe(0);
      } finally {
        clearTimeout(timeout);
      }
      expect(
        final,
        "The owned read-only peer must retain its final audit",
      ).toBeTruthy();
      expect(final.errors, stderr).toEqual([]);
      return final;
    },
  };
}
async function freePort() {
  const socket = createSocket("udp4");
  return new Promise<number>((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const port = (socket.address() as any).port;
      socket.close(() => resolve(port));
    });
  });
}
export async function openScheduleController(
  page: Page,
  request: APIRequestContext,
  peer: { endpoint: string },
  routed = false,
) {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBeTruthy();
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(routed ? "3001:7" : peer.endpoint);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill("device,42");
  await page
    .getByLabel("Known router", { exact: true })
    .fill(routed ? peer.endpoint : "");
  await page
    .getByLabel("Known network", { exact: true })
    .fill(routed ? "3001" : "");
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(page.getByLabel("Working context")).toContainText("device,42");
  await chooseWorkspaceTask(page, "Schedules");
  const panel = page.getByRole("region", {
    name: "Native Calendar and Schedule inventory",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Read native schedules", exact: true }),
  ).toBeEnabled();
  await panel
    .getByLabel("Calendar/Schedule object selection", { exact: true })
    .fill("calendar,1; schedule,1");
  return panel;
}
