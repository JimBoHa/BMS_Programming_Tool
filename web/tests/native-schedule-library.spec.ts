import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(".."),
  base = "/api/bacnet/schedules/library";
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function disconnect(request: APIRequestContext) {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
}
test.afterEach(async ({ request }) => disconnect(request));
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      socket.close(() =>
        resolve(typeof address === "string" ? 0 : address.port),
      );
    });
  });
}
async function peer(routed: boolean) {
  const child = spawn(
    path.join(root, ".venv/bin/python"),
    [
      "-u",
      "-c",
      `
import asyncio,json,sys
from tests.test_schedule_inventory import make_peer
async def main():
 p=await make_peer(routed=sys.argv[1]=='1');original=p.datagram_received
 def observed(data,source):
  print('READ',flush=True);original(data,source)
 p.datagram_received=observed
 print(json.dumps({'port':int(p.endpoint.split(':')[-1])}),flush=True)
 try: await asyncio.to_thread(sys.stdin.readline)
 finally:
  p.close();print(json.dumps({'requests':len(p.requests),'errors':p.errors}),flush=True)
asyncio.run(main())
`,
      routed ? "1" : "0",
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  let output = "",
    error = "",
    reads = 0,
    summary: any,
    closed = false;
  const port = await new Promise<number>((resolve, reject) => {
    let ready = false;
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Schedule peer startup: " + error));
    }, 5000);
    child.stderr.on("data", (value) => {
      error += String(value);
    });
    child.stdout.on("data", (value) => {
      output += String(value);
      while (output.includes("\n")) {
        const end = output.indexOf("\n"),
          line = output.slice(0, end);
        output = output.slice(end + 1);
        if (line === "READ") reads++;
        else {
          const parsed = JSON.parse(line);
          if (!ready) {
            ready = true;
            clearTimeout(timer);
            resolve(parsed.port);
          } else summary = parsed;
        }
      }
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`Peer exited ${code}: ${error}`));
    });
  });
  return {
    port,
    reads: () => reads,
    async close() {
      if (closed) return summary;
      closed = true;
      const exited = new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      child.stdin.end("close\n");
      const timer = setTimeout(() => child.kill(), 3000),
        code = await exited;
      clearTimeout(timer);
      expect(code, error).toBe(0);
      expect(summary.errors).toEqual([]);
      return summary;
    },
  };
}
function library(page: Page) {
  return page.getByRole("region", {
    name: "Native Schedule capture library",
    exact: true,
  });
}
async function capture(
  page: Page,
  request: APIRequestContext,
  routed: boolean,
  save = true,
) {
  const server = await peer(routed);
  expect(
    (
      await request.post("/api/bacnet/connect", {
        headers: await headers(request),
        data: { local_address: `127.0.0.1:${await freePort()}` },
      })
    ).ok(),
  ).toBe(true);
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Native Calendar and Schedule inventory",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Read native schedules", exact: true }),
  ).toBeEnabled();
  await panel
    .getByLabel("Schedule source address", { exact: true })
    .fill(routed ? "3001:7" : `127.0.0.1:${server.port}`);
  await panel
    .getByLabel("Schedule Device identifier", { exact: true })
    .fill("device,42");
  await panel
    .getByLabel("Calendar/Schedule object selection", { exact: true })
    .fill("calendar,1; schedule,1");
  if (routed) {
    await panel
      .getByLabel("Schedule router endpoint", { exact: true })
      .fill(`127.0.0.1:${server.port}`);
    await panel.getByLabel("Schedule DNET", { exact: true }).fill("3001");
  }
  await panel
    .getByRole("button", { name: "Read native schedules", exact: true })
    .click();
  await expect(
    panel.getByLabel("Schedule evidence report", { exact: true }),
  ).toBeVisible();
  const local = library(page);
  if (!save) return { server, panel, local, id: "" };
  await local
    .getByRole("button", {
      name: "Save current schedule report locally",
      exact: true,
    })
    .click();
  await expect(
    local.getByLabel("Opened native schedule capture", { exact: true }),
  ).toBeVisible();
  const id = (await local.locator(".mono").innerText()).match(
    /[a-f0-9]{64}/,
  )![0];
  return { server, panel, local, id };
}
async function download(page: Page, button: ReturnType<Page["getByRole"]>) {
  const pending = page.waitForEvent("download");
  await button.click();
  return readFileSync((await (await pending).path())!);
}
function verifyReview(raw: Buffer, text: string) {
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `import hashlib,json,sys
r=json.load(sys.stdin)
assert r['id']==hashlib.sha256(json.dumps({k:v for k,v in r.items() if k!='id'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
assert r['request']['transitions'][0]['value_text']==sys.argv[1]
assert r['field_writes'] is False
assert r['new']['roundtrip_tags_exhausted'] is True
assert r['diff']['other_days_changed'] is False
`,
      text,
    ],
    { input: raw },
  );
}
function verifyArchive(raw: Buffer) {
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [
      "-c",
      `import hashlib,json,sys
r=json.load(sys.stdin)
assert r['archive_sha256']==hashlib.sha256(json.dumps({k:v for k,v in r.items() if k!='archive_sha256'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
assert hashlib.sha256(r['source_json'].encode()).hexdigest()==r['id']==r['source_sha256']
`,
    ],
    { input: raw },
  );
}

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} native capture saves offline and exact negative-zero draft downloads/imports without field queries`, async ({
    page,
    request,
  }) => {
    const { server, local, id } = await capture(page, request, routed);
    try {
      await page
        .getByRole("button", { name: "Close BACnet interface", exact: true })
        .click();
      await expect(
        page.getByText("No BACnet interface open", { exact: true }),
      ).toBeVisible();
      const before = server.reads();
      expect(before).toBeGreaterThan(20);
      await expect(
        local.getByLabel("Transition 1 exact value text", { exact: true }),
      ).toHaveValue("-0.0");
      await local
        .getByRole("button", {
          name: "Review native weekly draft",
          exact: true,
        })
        .click();
      await expect(
        local.getByRole("heading", {
          name: "No native day changes",
          exact: true,
        }),
      ).toBeVisible();
      const review = await download(
        page,
        local.getByRole("button", {
          name: "Export exact reviewed weekly draft",
          exact: true,
        }),
      );
      verifyReview(review, "-0.0");
      const doc = JSON.parse(review.toString());
      expect(doc.new.encoded_hex).toBe(doc.old.encoded_hex);
      expect(doc.new.transitions[0].wire_value_text).toBe("-0.0");
      const archive = await download(
        page,
        local.getByRole("button", {
          name: "Export exact capture archive",
          exact: true,
        }),
      );
      verifyArchive(archive);
      const authoritative = await request.post(base + "/export", {
        headers: await headers(request),
        data: { id },
      });
      expect(archive.equals(await authoritative.body())).toBe(true);
      const source = await download(
        page,
        local.getByRole("button", {
          name: "Export original schedule source",
          exact: true,
        }),
      );
      execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "import hashlib,sys;assert hashlib.sha256(sys.stdin.buffer.read()).hexdigest()==sys.argv[1]",
          id,
        ],
        { input: source },
      );
      await page.reload();
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      const reopened = library(page);
      await reopened
        .getByLabel("Import native schedule capture file", { exact: true })
        .setInputFiles({
          name: "capture.json",
          mimeType: "application/json",
          buffer: archive,
        });
      await expect(
        reopened.getByText(`Imported capture ${id.slice(0, 12)}.`, {
          exact: true,
        }),
      ).toBeVisible();
      const duplicate = await download(
        page,
        reopened.getByRole("button", {
          name: "Export exact capture archive",
          exact: true,
        }),
      );
      expect(duplicate.equals(archive)).toBe(true);
      await expect(
        reopened.getByLabel("Transition 1 exact value text", { exact: true }),
      ).toHaveValue("-0.0");
      await reopened
        .getByLabel("Import native weekly draft file", { exact: true })
        .setInputFiles({
          name: "review.json",
          mimeType: "application/json",
          buffer: review,
        });
      await expect(
        reopened.getByText(
          "Imported review regenerated against its exact local source capture.",
          { exact: true },
        ),
      ).toBeVisible();
      const again = await download(
        page,
        reopened.getByRole("button", {
          name: "Export exact reviewed weekly draft",
          exact: true,
        }),
      );
      expect(again.equals(review)).toBe(true);
      expect(server.reads()).toBe(before);
      expect((await server.close()).requests).toBe(before);
    } catch (failure) {
      await server.close();
      throw failure;
    }
  });

test("native day edits retain typed intent, expose wire rounding, reject unsupported values and guard dirty replacement", async ({
  page,
  request,
}) => {
  const { server, local } = await capture(page, request, false);
  try {
    await disconnect(request);
    const before = server.reads();
    const value = local.getByLabel("Transition 1 exact value text", {
      exact: true,
    });
    await value.fill("0.1");
    await local
      .getByLabel("Native weekly day", { exact: true })
      .selectOption("2");
    await expect(local.getByRole("alert")).toContainText("Export or discard");
    await expect(
      local.getByLabel("Native weekly day", { exact: true }),
    ).toHaveValue("1");
    await local
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await expect(
      local.getByLabel("Native weekly draft review", { exact: true }),
    ).toBeVisible();
    await expect(
      local.getByRole("table", { name: "Requested and encoded native values" }),
    ).toContainText("Inspect rounding");
    const reviewed = await download(
      page,
      local.getByRole("button", {
        name: "Export exact reviewed weekly draft",
        exact: true,
      }),
    );
    verifyReview(reviewed, "0.1");
    await value.fill("1e400");
    await local
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await expect(local.getByRole("alert")).toContainText("finite");
    await expect(value).toHaveValue("1e400");
    await expect(
      local.getByRole("button", {
        name: "Export exact reviewed weekly draft",
        exact: true,
      }),
    ).toHaveCount(0);
    await local
      .getByRole("button", { name: "Discard weekly draft", exact: true })
      .click();
    await local
      .getByLabel("Native weekly day", { exact: true })
      .selectOption("2");
    await local
      .getByRole("button", { name: "Remove transition 1", exact: true })
      .click();
    await local
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await expect(
      local.getByLabel("Native weekly draft review", { exact: true }),
    ).toContainText("1 → 0 transitions");
    expect(server.reads()).toBe(before);
    await server.close();
  } catch (failure) {
    await server.close();
    throw failure;
  }
});

test("a completed local save cannot adopt an inventory source that changed during delivery", async ({
  page,
  request,
}) => {
  const { server, panel, local } = await capture(page, request, false, false);
  let release!: () => void;
  try {
    const before = server.reads();
    let received!: () => void;
    const entered = new Promise<void>((resolve) => {
      received = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/bacnet/schedules/library/save", async (route) => {
      const response = await route.fetch();
      received();
      await gate;
      await route.fulfill({ response });
    });
    await local
      .getByRole("button", {
        name: "Save current schedule report locally",
        exact: true,
      })
      .click();
    await entered;
    await panel
      .getByLabel("Schedule source address", { exact: true })
      .fill("192.0.2.77");
    await expect(
      panel.getByLabel("Schedule evidence report", { exact: true }),
    ).toHaveCount(0);
    const delivered = page.waitForResponse(
      "**/api/bacnet/schedules/library/save",
    );
    release();
    await (await delivered).finished();
    await expect(
      local.getByRole("button", {
        name: "Refresh local schedule library",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      local.getByLabel("Opened native schedule capture", { exact: true }),
    ).toHaveCount(0);
    await expect(local.getByText(/^Saved capture /)).toHaveCount(0);
    await expect(
      panel.getByLabel("Schedule source address", { exact: true }),
    ).toHaveValue("192.0.2.77");
    await local
      .getByRole("button", {
        name: "Refresh local schedule library",
        exact: true,
      })
      .click();
    const captures = (await (await request.get(base + "/profile")).json())
      .captures;
    const saved = captures.find(
      (item: any) => item.target.address === `127.0.0.1:${server.port}`,
    );
    expect(saved).toBeTruthy();
    await expect(
      local.getByRole("button", {
        name: `Open capture ${saved.id.slice(0, 12)}`,
        exact: true,
      }),
    ).toBeVisible();
    expect(server.reads()).toBe(before);
    await server.close();
  } catch (failure) {
    release?.();
    await server.close();
    throw failure;
  }
});

test("a delayed local reopen or export cannot clear edited rows or follow a changed day", async ({
  page,
  request,
}) => {
  const { server, local, id } = await capture(page, request, false);
  let release!: () => void;
  try {
    await disconnect(request);
    const before = server.reads();
    let received!: () => void;
    const entered = new Promise<void>((resolve) => {
      received = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      "**/api/bacnet/schedules/library/captures/" + id,
      async (route) => {
        const response = await route.fetch();
        received();
        await gate;
        await route.fulfill({ response });
      },
    );
    await local
      .getByRole("button", {
        name: `Open capture ${id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    await entered;
    await local
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill("4.5");
    const delivered = page.waitForResponse(
      "**/api/bacnet/schedules/library/captures/" + id,
    );
    release();
    await (await delivered).finished();
    await expect(
      local.getByRole("button", {
        name: "Refresh local schedule library",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      local.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("4.5");
    await page.unroute("**/api/bacnet/schedules/library/captures/" + id);
    await local
      .getByRole("button", { name: "Discard weekly draft", exact: true })
      .click();
    let exporting!: () => void;
    const exportEntered = new Promise<void>((resolve) => {
      exporting = resolve;
    });
    const exportGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      "**/api/bacnet/schedules/library/source-export",
      async (route) => {
        const response = await route.fetch();
        exporting();
        await exportGate;
        await route.fulfill({ response });
      },
    );
    const downloads: string[] = [];
    page.on("download", (item) => downloads.push(item.suggestedFilename()));
    await local
      .getByRole("button", {
        name: "Export original schedule source",
        exact: true,
      })
      .click();
    await exportEntered;
    await local
      .getByLabel("Native weekly day", { exact: true })
      .selectOption("2");
    const exported = page.waitForResponse(
      "**/api/bacnet/schedules/library/source-export",
    );
    release();
    await (await exported).finished();
    await expect(
      local.getByRole("button", {
        name: "Export original schedule source",
        exact: true,
      }),
    ).toBeEnabled();
    expect(downloads).toEqual([]);
    expect(server.reads()).toBe(before);
    await server.close();
  } catch (failure) {
    release?.();
    await server.close();
    throw failure;
  }
});

test("tampered imports, mismatched reviews, altered source bytes and storage errors preserve the current draft", async ({
  page,
  request,
}) => {
  const { server, local } = await capture(page, request, false);
  try {
    await disconnect(request);
    const before = server.reads();
    const raw = await download(
      page,
      local.getByRole("button", {
        name: "Export exact capture archive",
        exact: true,
      }),
    );
    const archive = JSON.parse(raw.toString());
    archive.id = "0".repeat(64);
    await local
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill("2.5");
    await local
      .getByLabel("Import native schedule capture file", { exact: true })
      .setInputFiles({
        name: "changed.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(archive)),
      });
    await expect(local.getByRole("alert")).toContainText("seal");
    await expect(
      local.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("2.5");
    await page.route(
      "**/api/bacnet/schedules/library/drafts/review",
      async (route) => {
        const response = await route.fetch();
        const body = await response.json();
        body.source.capture_id = "0".repeat(64);
        await route.fulfill({ response, json: body });
      },
    );
    await local
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await expect(local.getByRole("alert")).toContainText(
      "not a native weekly-day",
    );
    await expect(
      local.getByLabel("Native weekly draft review", { exact: true }),
    ).toHaveCount(0);
    await page.unroute("**/api/bacnet/schedules/library/drafts/review");
    await page.route(
      "**/api/bacnet/schedules/library/source-export",
      async (route) => {
        const response = await route.fetch();
        await route.fulfill({ response, body: (await response.text()) + "\n" });
      },
    );
    const downloads: string[] = [];
    page.on("download", (item) => downloads.push(item.suggestedFilename()));
    await local
      .getByRole("button", {
        name: "Export original schedule source",
        exact: true,
      })
      .click();
    await expect(local.getByRole("alert")).toContainText(
      "source bytes do not match",
    );
    expect(downloads).toEqual([]);
    await page.route("**/api/bacnet/schedules/library/profile", (route) =>
      route.fulfill({
        status: 500,
        json: { detail: "Review test storage is unavailable" },
      }),
    );
    await local
      .getByRole("button", {
        name: "Refresh local schedule library",
        exact: true,
      })
      .click();
    await expect(local.getByRole("alert")).toContainText(
      "storage is unavailable",
    );
    await expect(
      local.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("2.5");
    await page.unroute("**/api/bacnet/schedules/library/profile");
    for (const malformed of [
      { profile: "unknown-version", captures: [] },
      { captures: {} },
      { captures: [{ id: "invalid-summary" }] },
      { storage: { durability: { message: "not displayable text" } } },
    ]) {
      await page.route(
        "**/api/bacnet/schedules/library/profile",
        async (route) => {
          const response = await route.fetch();
          await route.fulfill({
            response,
            json: { ...(await response.json()), ...malformed },
          });
        },
      );
      await local
        .getByRole("button", {
          name: "Refresh local schedule library",
          exact: true,
        })
        .click();
      await expect(local.getByRole("alert")).toContainText(
        "profile is malformed or unsupported",
      );
      await expect(
        local.getByLabel("Transition 1 exact value text", { exact: true }),
      ).toHaveValue("2.5");
      await expect(
        local.getByRole("table", { name: "Saved native schedule captures" }),
      ).toContainText("Open capture");
      await page.unroute("**/api/bacnet/schedules/library/profile");
    }
    expect(server.reads()).toBe(before);
    await server.close();
  } catch (failure) {
    await server.close();
    throw failure;
  }
});

test("late real reviews and downloads cannot replace edited rows or survive leaving the library", async ({
  page,
  request,
}) => {
  const { server, local } = await capture(page, request, false);
  let release!: () => void;
  try {
    await disconnect(request);
    const before = server.reads();
    let received!: () => void;
    const captured = new Promise<void>((resolve) => {
      received = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      "**/api/bacnet/schedules/library/drafts/review",
      async (route) => {
        const response = await route.fetch();
        received();
        await gate;
        await route.fulfill({ response });
      },
    );
    await local
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill("2.5");
    await local
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await captured;
    await local
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill("3.5");
    const delivered = page.waitForResponse(
      "**/api/bacnet/schedules/library/drafts/review",
    );
    release();
    await (await delivered).finished();
    await expect(
      local.getByRole("button", {
        name: "Review native weekly draft",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      local.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("3.5");
    await expect(
      local.getByLabel("Native weekly draft review", { exact: true }),
    ).toHaveCount(0);
    await page.unroute("**/api/bacnet/schedules/library/drafts/review");
    await local
      .getByRole("button", { name: "Discard weekly draft", exact: true })
      .click();
    let exportReceived!: () => void;
    const exporting = new Promise<void>((resolve) => {
      exportReceived = resolve;
    });
    const exportGate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(
      "**/api/bacnet/schedules/library/source-export",
      async (route) => {
        const response = await route.fetch();
        exportReceived();
        await exportGate;
        await route.fulfill({ response });
      },
    );
    const downloads: string[] = [];
    page.on("download", (item) => downloads.push(item.suggestedFilename()));
    await local
      .getByRole("button", {
        name: "Export original schedule source",
        exact: true,
      })
      .click();
    await exporting;
    await page.getByRole("button", { name: "Reference", exact: true }).click();
    const exported = page.waitForResponse(
      "**/api/bacnet/schedules/library/source-export",
    );
    release();
    await (await exported).finished();
    await page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
    expect(downloads).toEqual([]);
    expect(server.reads()).toBe(before);
    await server.close();
  } catch (failure) {
    release?.();
    await server.close();
    throw failure;
  }
});
