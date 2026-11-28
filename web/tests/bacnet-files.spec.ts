import { test, expect, type Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import {
  openMonitoringInterface,
  selectKnownMonitoringController,
} from "./event-workspace";
import {
  chooseWorkspaceSurface,
  chooseWorkspaceTask,
  chooseWorkspaceTool,
} from "./workspace-navigation";
import { disconnectTestInterface, freePort } from "./workflow-peer";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve("..");
async function filePeer(emptyConfiguration = false) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_bacnet_files import FilePeer,port
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject
async def main():
    remote=port()
    server=FilePeer.from_object_list([
        DeviceObject(objectIdentifier=('device',4190150),objectName='Independent file peer',
            vendorIdentifier=999,modelName='Authored File Peer',firmwareRevision='test-1.0',
            maxApduLengthAccepted=128,configurationFiles=[('file',31),('file',32)]),
        NetworkPortObject(f'127.0.0.1:{remote}',objectIdentifier=('network-port',1),objectName='Loopback UDP')])
    server.setup()
    if sys.argv[1]=='empty': server.device_object.configurationFiles=[]
    print(json.dumps({'address':f'127.0.0.1:{remote}'}),flush=True)
    try: await asyncio.to_thread(sys.stdin.readline)
    finally:
        server.close()
        print(json.dumps({'requests':server.all_requests,'file_reads':len(server.atomic_requests)}),flush=True)
        await asyncio.sleep(.05)
asyncio.run(main())`,
      emptyConfiguration ? "empty" : "configured",
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let output = "",
    error = "",
    ready = false;
  child.stderr.on("data", (data) => {
    error += data.toString();
  });
  const address = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("File peer startup timed out: " + error));
    }, 6000);
    child.stdout.on("data", (data) => {
      output += data.toString();
      if (!ready && output.includes("\n")) {
        ready = true;
        clearTimeout(timer);
        resolve(JSON.parse(output.split("\n")[0]).address);
      }
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`File peer exited ${code}: ${error}`));
    });
  });
  return {
    address,
    async close() {
      const finished = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      child.stdin.end("close\n");
      const timer = setTimeout(() => child.kill(), 2000);
      const code = await finished;
      clearTimeout(timer);
      expect(code, error).toBe(0);
      return JSON.parse(output.trim().split("\n").at(-1)!);
    },
  };
}
async function chooseFileController(page: Page, address: string) {
  await selectKnownMonitoringController(page, address, "device,4190150");
  await chooseWorkspaceTask(page, "Changes");
  await chooseWorkspaceTool(page, "Controller changes");
  const tools = page.getByRole("navigation", {
    name: "Controller task tools",
    exact: true,
  });
  const select = tools.getByRole("combobox");
  if (await select.isVisible())
    await select.selectOption({ label: "File captures" });
  else
    await tools
      .getByRole("button", { name: "File captures", exact: true })
      .click();
  const panel = page.getByRole("region", {
    name: "BACnet configuration files",
    exact: true,
  });
  await expect(
    panel.getByRole("button", {
      name: "Inspect advertised files",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    panel.getByLabel("File device address", { exact: true }),
  ).toHaveCount(0);
  return panel;
}

async function openInterface(page: Page, address: string) {
  await openMonitoringInterface(page);
  return chooseFileController(page, address);
}

async function openSavedFiles(page: Page) {
  await chooseWorkspaceSurface(page, "History");
  const nav = page.getByRole("navigation", {
    name: "history tools",
    exact: true,
  });
  await expect(nav).toBeVisible();
  const select = nav.getByRole("combobox");
  if (await select.isVisible())
    await select.selectOption({ label: "Native backups" });
  else
    await nav
      .getByRole("button", { name: "Native backups", exact: true })
      .click();
  await page.getByText("Saved BACnet file captures", { exact: true }).click();
  const saved = page.getByRole("region", {
    name: "Local BACnet file archive",
    exact: true,
  });
  await expect(saved).toBeVisible();
  await expect(
    saved.getByRole("button", {
      name: "Inspect advertised files",
      exact: true,
    }),
  ).toHaveCount(0);
  return saved;
}

test("configuration files use actual UDP reads and preserve exact stream bytes, empty records and offline receipts", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const peer = await filePeer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let reads = 0;
  page.on("request", (value) => {
    if (value.url().endsWith("/api/bacnet/files/read")) reads++;
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openInterface(page, peer.address);
    await expect(panel).toContainText(
      "not CAF files or proof of a coherent application backup",
    );
    await panel
      .getByRole("button", { name: "Inspect advertised files", exact: true })
      .click();
    const inspected = panel.getByRole("region", {
      name: "Inspected configuration files",
      exact: true,
    });
    await expect(inspected.locator("tbody tr")).toHaveCount(2);
    await expect(inspected).toContainText("Authored File Peer / test-1.0");
    expect(reads).toBe(0);
    await inspected
      .getByRole("button", { name: "Read and save file,31", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "BACnet file capture receipt",
      exact: true,
    });
    await expect(receipt).toContainText(
      "complete within the opaque file profile",
    );
    await expect(receipt).toContainText("not an atomic snapshot");
    let downloading = page.waitForEvent("download");
    await receipt
      .getByRole("button", { name: "Download file receipt JSON", exact: true })
      .click();
    const streamReceipt = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    expect(streamReceipt.native_caf).toBe(false);
    expect(streamReceipt.metadata.object_id).toBe("file,31");
    expect(streamReceipt.device_identity["firmware-revision"]).toBe("test-1.0");
    const one = Buffer.concat([
      Buffer.from("Independent UDP file bytes"),
      Buffer.from([0, 255]),
    ]);
    const expected = Buffer.concat(Array.from({ length: 12 }, () => one));
    expect(streamReceipt.sha256).toBe(
      createHash("sha256").update(expected).digest("hex"),
    );
    downloading = page.waitForEvent("download");
    await panel
      .getByRole("button", {
        name: "Export opaque capture " + streamReceipt.id,
        exact: true,
      })
      .click();
    const stream = await downloading;
    expect(stream.suggestedFilename()).toBe(streamReceipt.id + ".bin");
    expect(readFileSync((await stream.path())!)).toEqual(expected);
    await expect(panel).toContainText(
      "browser SHA-256 matches the saved receipt",
    );
    await inspected
      .getByRole("button", { name: "Read and save file,32", exact: true })
      .click();
    await expect(receipt).toContainText(
      "Record boundaries preserved: 3, including 1 empty records",
    );
    downloading = page.waitForEvent("download");
    await receipt
      .getByRole("button", { name: "Download file receipt JSON", exact: true })
      .click();
    const recordsReceipt = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    await disconnectTestInterface(request);
    await page.reload();
    const bacnetPosts: string[] = [];
    const catalogResponses: Promise<unknown>[] = [];
    const catalogPath =
      "/api/bacnet/controller/native-application/backup-library/list";
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (request.method() === "POST" && path.startsWith("/api/bacnet/"))
        bacnetPosts.push(path);
    });
    page.on("response", (response) => {
      if (new URL(response.url()).pathname === catalogPath)
        catalogResponses.push(response.json());
    });
    const saved = await openSavedFiles(page);
    downloading = page.waitForEvent("download");
    await saved
      .getByRole("button", {
        name: "Export opaque capture " + recordsReceipt.id,
        exact: true,
      })
      .click();
    const archive = await downloading;
    expect(archive.suggestedFilename()).toBe(
      recordsReceipt.id + "-records.zip",
    );
    const parsed = JSON.parse(
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps({'records':[z.read('records/%08d.bin'%i).hex() for i in range(3)],'receipt':json.loads(z.read('receipt.json'))}))",
          (await archive.path())!,
        ],
        { cwd: root, encoding: "utf8" },
      ),
    );
    expect(parsed.records).toEqual([
      Buffer.from("first\0record").toString("hex"),
      "",
      "ff" + Buffer.from("last-record").toString("hex"),
    ]);
    expect(parsed.receipt).toEqual(recordsReceipt);
    await page.reload();
    const reopened = await openSavedFiles(page);
    await reopened
      .getByRole("button", {
        name: "Open file receipt " + streamReceipt.id,
        exact: true,
      })
      .click();
    await expect(
      reopened.getByRole("region", { name: "BACnet file capture receipt" }),
    ).toContainText(streamReceipt.sha256);
    const sourceLabel = reopened
      .getByText("Source", { exact: true })
      .filter({ visible: true })
      .last();
    await sourceLabel.scrollIntoViewIfNeeded();
    const labelPosition = await sourceLabel.boundingBox();
    expect(labelPosition!.x).toBeGreaterThanOrEqual(0);
    await expect(
      reopened.getByRole("region", { name: "BACnet file capture receipt" }),
    ).toContainText("Independent file peer");
    expect(bacnetPosts).toEqual([catalogPath, catalogPath]);
    expect(await Promise.all(catalogResponses)).toEqual(
      [1, 2].map(() =>
        expect.objectContaining({
          controller_queries: false,
          field_actions: false,
        }),
      ),
    );
    expect(
      (await (await request.get("/api/bacnet/status")).json()).connected,
    ).toBe(false);
    expect(reads).toBe(2);
    await page.screenshot({
      path: "test-results/studio-bacnet-files.png",
      fullPage: true,
    });
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await peer.close();
    expect(new Set(evidence.requests)).toEqual(
      new Set(["ReadPropertyRequest", "AtomicReadFileRequest"]),
    );
    expect(evidence.file_reads).toBeGreaterThan(1);
  }
});

test("empty configuration-files uses advertised Object List files without relabeling them as configuration backups", async ({
  page,
  request,
}) => {
  const peer = await filePeer(true);
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openInterface(page, peer.address);
    await panel
      .getByRole("button", { name: "Inspect advertised files", exact: true })
      .click();
    const inspected = panel.getByRole("region", {
      name: "Inspected configuration files",
      exact: true,
    });
    await expect(inspected).toContainText(
      "object-list · 4 Object List entries checked",
    );
    await expect(inspected).toContainText(
      "Empty configuration-files list; listed files come from the Object List.",
    );
    await expect(inspected.locator("tbody tr")).toHaveCount(2);
    await inspected
      .getByRole("button", { name: "Read and save file,31", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "BACnet file capture receipt",
      exact: true,
    });
    await expect(receipt).toContainText(
      "object-list · configuration-files was empty",
    );
    const downloading = page.waitForEvent("download");
    await receipt
      .getByRole("button", { name: "Download file receipt JSON", exact: true })
      .click();
    const evidence = JSON.parse(
      readFileSync((await (await downloading).path())!, "utf8"),
    );
    expect(evidence.discovery_source).toBe("object-list");
    expect(evidence.configuration_files).toEqual([]);
    expect(evidence.advertised_files).toEqual(["file,31", "file,32"]);
    expect(evidence.native_caf).toBe(false);
    const exported = await request.get(
      "/api/bacnet/files/captures/" + evidence.id + "/export",
    );
    expect(
      createHash("sha256")
        .update(await exported.body())
        .digest("hex"),
    ).toBe(evidence.sha256);
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await peer.close();
    expect(new Set(evidence.requests)).toEqual(
      new Set(["ReadPropertyRequest", "AtomicReadFileRequest"]),
    );
  }
});

test("a parent target edit invalidates a delayed real file inspection", async ({
  page,
  request,
}) => {
  const peer = await filePeer();
  const next = await filePeer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const waiting = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  try {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const panel = await openInterface(page, peer.address);
    await page.route("**/api/bacnet/files/inspect", async (route) => {
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      arrived();
      await held;
      await route.fulfill({ response });
    });
    await panel
      .getByRole("button", { name: "Inspect advertised files", exact: true })
      .click();
    await waiting;
    await page
      .getByLabel("Working context")
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
    await chooseFileController(page, next.address);
    const completed = page.waitForResponse((r) =>
      r.url().endsWith("/api/bacnet/files/inspect"),
    );
    release();
    await completed;
    await expect(page.getByLabel("Working context")).toContainText(
      next.address,
    );
    await expect(
      panel.getByRole("region", {
        name: "Inspected configuration files",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", { name: "Read and save file,31", exact: true }),
    ).toHaveCount(0);
  } finally {
    release?.();
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    const evidence = await peer.close();
    expect((await next.close()).file_reads).toBe(0);
    expect(evidence.file_reads).toBe(0);
  }
});

test("a delayed saved export never downloads after leaving the local file archive", async ({
  page,
  request,
}) => {
  const peer = await filePeer();
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  let capture: any;
  try {
    const opened = await request.post("/api/bacnet/connect", {
      headers,
      data: { local_address: `127.0.0.1:${await freePort()}` },
    });
    expect(opened.ok()).toBeTruthy();
    const inspected = await request.post("/api/bacnet/files/inspect", {
      headers,
      data: { address: peer.address, device: "device,4190150" },
    });
    expect(inspected.ok()).toBeTruthy();
    const inspection = await inspected.json();
    const saved = await request.post("/api/bacnet/files/read", {
      headers,
      data: {
        inspection_id: inspection.id,
        object_id: inspection.files[0].object_id,
        metadata_sha256: inspection.files[0].metadata_sha256,
      },
    });
    expect(saved.ok()).toBeTruthy();
    capture = await saved.json();
  } finally {
    await request.post("/api/bacnet/disconnect", { headers, data: {} });
    await peer.close();
  }
  let release!: () => void, arrived!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const waiting = new Promise<void>((resolve) => {
    arrived = resolve;
  });
  const downloads: string[] = [];
  page.on("download", (download) =>
    downloads.push(download.suggestedFilename()),
  );
  await page.goto("/");
  await openSavedFiles(page);
  await page.route("**/api/bacnet/files/captures/*/export", async (route) => {
    const response = await route.fetch();
    arrived();
    await held;
    await route.fulfill({ response });
  });
  try {
    await page
      .getByRole("button", {
        name: "Export opaque capture " + capture.id,
        exact: true,
      })
      .click();
    await waiting;
    await chooseWorkspaceSurface(page, "Library");
    const completed = page.waitForResponse((response) =>
      response.url().endsWith("/" + capture.id + "/export"),
    );
    release();
    await completed;
    await expect(
      page.getByRole("region", {
        name: "Local BACnet file archive",
        exact: true,
      }),
    ).toHaveCount(0);
    await page.waitForTimeout(100);
    expect(downloads).toEqual([]);
  } finally {
    release?.();
  }
});
