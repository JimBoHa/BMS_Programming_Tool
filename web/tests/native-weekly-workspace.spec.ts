import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { scheduleControllerPeer } from "./schedule-controller-peer";
import {
  chooseWorkspaceTask,
  chooseWorkspaceSurface,
} from "./workspace-navigation";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const base = "/api/bacnet/schedules/library";
const lib = (page: Page) =>
  page.getByRole("region", {
    name: "Native Schedule capture library",
    exact: true,
  });
const value = (page: Page) =>
  lib(page).getByLabel("Transition 1 exact value text", { exact: true });
const button = (page: Page, name: string) =>
  lib(page).getByRole("button", { name, exact: true });
const reviewed = (page: Page) =>
  lib(page).getByLabel("Native weekly draft review", { exact: true });
async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function open(page: Page, id: string) {
  await button(page, "Open capture " + id.slice(0, 12)).click();
  await expect(
    lib(page).getByLabel("Opened native schedule capture", { exact: true }),
  ).toContainText(id);
  await expect(button(page, "Refresh local schedule library")).toBeEnabled();
}
async function setup(page: Page, request: APIRequestContext, caf = false) {
  const peers: Awaited<ReturnType<typeof scheduleControllerPeer>>[] = [],
    captures: any[] = [],
    headers = await auth(request);
  try {
    for (const string of [false, true]) {
      const peer = await scheduleControllerPeer(string, string);
      peers.push(peer);
      expect(
        (
          await request.post("/api/bacnet/disconnect", { headers, data: {} })
        ).ok(),
      ).toBe(true);
      expect(
        (
          await request.post("/api/bacnet/connect", {
            headers,
            data: { local_address: peer.local },
          })
        ).ok(),
      ).toBe(true);
      const read = await request.post("/api/bacnet/schedules/read", {
        headers,
        data: {
          ...peer.target,
          object_ids: string ? ["schedule,1"] : ["schedule,1", "schedule,2"],
          operation_id: "weekly_workspace_" + crypto.randomUUID(),
        },
      });
      expect(read.ok(), await read.text()).toBe(true);
      const report = await read.json();
      expect(report.complete).toBe(true);
      const saved = await request.post(base + "/save", {
        headers,
        data: { id: report.id },
      });
      expect(saved.ok()).toBe(true);
      captures.push(await saved.json());
    }
    expect(
      (
        await request.post("/api/bacnet/disconnect", { headers, data: {} })
      ).ok(),
    ).toBe(true);
    const calls: string[] = [];
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        r.url().includes("/api/bacnet/") &&
        !r.url().includes(base + "/")
      )
        calls.push(r.url());
    });
    await page.goto("/");
    if (caf) {
      const root = path.resolve("..");
      const buffer = execFileSync(
        path.join(root, ".venv/bin/python"),
        [
          "-c",
          "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
        ],
        {
          cwd: root,
          env: { ...process.env, PYTHONPATH: root + "/backend:" + root },
        },
      );
      await page
        .getByLabel("Open local CAF application", { exact: true })
        .setInputFiles({
          name: "weekly-work.caf",
          mimeType: "application/octet-stream",
          buffer,
        });
      await expect(page.getByLabel("Working context")).toContainText(
        "weekly-work.caf",
      );
    } else
      await page
        .getByRole("button", { name: "New application", exact: true })
        .click();
    await chooseWorkspaceTask(page, "Schedules");
    await open(page, captures[0].id);
    const before = await Promise.all(peers.map((p) => p.stats()));
    return { peers, captures, headers, calls, before };
  } catch (e) {
    await Promise.all(peers.map((p) => p.close()));
    throw e;
  }
}
async function review(page: Page) {
  await button(page, "Review native weekly draft").click();
  await expect(reviewed(page)).toBeVisible();
}
async function exported(page: Page) {
  const pending = page.waitForEvent("download");
  await button(page, "Export exact reviewed weekly draft").click();
  return readFileSync((await (await pending).path())!);
}
async function finish(work: Awaited<ReturnType<typeof setup>>) {
  try {
    expect(work.calls).toEqual([]);
    expect(await Promise.all(work.peers.map((p) => p.stats()))).toEqual(
      work.before,
    );
  } finally {
    await Promise.all(work.peers.map((p) => p.close()));
  }
}
for (const caf of [false, true])
  test(`${caf ? "CAF" : "local graph"} weekly raw text stays with its source, Schedule and day through navigation`, async ({
    page,
    request,
  }, info) => {
    const work = await setup(page, request, caf);
    try {
      await value(page).fill("2e-");
      await lib(page)
        .getByLabel("Transition 1 hour", { exact: true })
        .fill("1e");
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Schedules");
      await expect(value(page)).toHaveValue("2e-");
      await expect(
        lib(page).getByLabel("Transition 1 hour", { exact: true }),
      ).toHaveValue("1e");
      await lib(page)
        .getByLabel("Native weekly day", { exact: true })
        .selectOption("2");
      await value(page).fill("3.5");
      await lib(page)
        .getByLabel("Captured Schedule for weekly draft", { exact: true })
        .selectOption("schedule,2");
      await value(page).fill("4.25");
      await open(page, work.captures[1].id);
      const raw = lib(page).getByLabel(
        "Transition 1 CharacterString JSON literal",
        { exact: true },
      );
      await raw.fill('  "unfinished\\u00');
      await chooseWorkspaceSurface(page, "Library");
      await chooseWorkspaceSurface(page, "Workspace");
      await chooseWorkspaceTask(page, "Schedules");
      await expect(raw).toHaveValue('  "unfinished\\u00');
      await open(page, work.captures[0].id);
      await expect(
        lib(page).getByLabel("Captured Schedule for weekly draft", {
          exact: true,
        }),
      ).toHaveValue("schedule,2");
      await expect(
        lib(page).getByLabel("Native weekly day", { exact: true }),
      ).toHaveValue("2");
      await expect(value(page)).toHaveValue("4.25");
      await lib(page)
        .getByLabel("Captured Schedule for weekly draft", { exact: true })
        .selectOption("schedule,1");
      await expect(value(page)).toHaveValue("3.5");
      await lib(page)
        .getByLabel("Native weekly day", { exact: true })
        .selectOption("1");
      await expect(value(page)).toHaveValue("2e-");
      await expect(
        lib(page).getByLabel("Transition 1 hour", { exact: true }),
      ).toHaveValue("1e");
      await expect(reviewed(page)).toHaveCount(0);
      await button(page, "Discard weekly draft").click();
      await expect(value(page)).toHaveValue("-0.0");
      await lib(page)
        .getByLabel("Native weekly day", { exact: true })
        .selectOption("2");
      await expect(value(page)).toHaveValue("3.5");
      await open(page, work.captures[1].id);
      await expect(raw).toHaveValue('  "unfinished\\u00');
      await page.setViewportSize({ width: 390, height: 1100 });
      await raw.scrollIntoViewIfNeeded();
      expect(await lib(page).evaluate((e) => e.scrollLeft)).toBe(0);
      expect(
        await lib(page).evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
      ).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("weekly-draft-phone.png"),
        fullPage: true,
      });
    } finally {
      await finish(work);
    }
  });
test("imported weekly provenance survives tasks while same-day replacement preserves unfinished text", async ({
  page,
  request,
}) => {
  const work = await setup(page, request);
  try {
    const response = await request.post(base + "/drafts/review", {
      headers: work.headers,
      data: {
        capture_id: work.captures[0].id,
        object_id: "schedule,1",
        day: 1,
        transitions: [
          { time: [8, 0, 0, 0], native_type: "Real", value_text: "0.1" },
        ],
      },
    });
    expect(response.ok()).toBe(true);
    const original = await response.json();
    const raw = await (
      await request.post(base + "/drafts/export", {
        headers: work.headers,
        data: { id: original.id },
      })
    ).body();
    const file = {
      name: "reviewed-day.json",
      mimeType: "application/json",
      buffer: raw,
    };
    await lib(page)
      .getByLabel("Import native weekly draft file", { exact: true })
      .setInputFiles(file);
    await expect(reviewed(page)).toBeVisible();
    await lib(page)
      .getByText("Imported weekly draft source", { exact: true })
      .click();
    await expect(
      lib(page).getByLabel("Imported weekly draft provenance", { exact: true }),
    ).toContainText(original.id);
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    await expect(value(page)).toHaveValue("0.1");
    await expect(reviewed(page)).toHaveCount(0);
    await lib(page)
      .getByText("Imported weekly draft source", { exact: true })
      .click();
    await page.setViewportSize({ width: 390, height: 1100 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(
      lib(page).getByLabel("Imported weekly draft provenance", { exact: true }),
    ).toContainText("reviewed-day.json");
    await value(page).fill("-8e");
    await lib(page)
      .getByLabel("Import native weekly draft file", { exact: true })
      .setInputFiles(file);
    await expect(lib(page).getByRole("alert")).toContainText(
      "already has unfinished work",
    );
    await expect(value(page)).toHaveValue("-8e");
    await value(page).fill("0.1");
    await review(page);
    expect((await exported(page)).equals(raw)).toBe(true);
    await chooseWorkspaceTask(page, "Program");
    await chooseWorkspaceTask(page, "Schedules");
    await expect(reviewed(page)).toHaveCount(0);
    await expect(value(page)).toHaveValue("0.1");
    await review(page);
    expect((await exported(page)).equals(raw)).toBe(true);
  } finally {
    await finish(work);
  }
});
for (const kind of ["review", "export", "import"] as const)
  test(`held weekly ${kind} cannot revive after task navigation or overwrite retained work`, async ({
    page,
    request,
  }) => {
    const work = await setup(page, request);
    let release = () => {};
    try {
      await value(page).fill("2.5");
      let importFile: any;
      if (kind === "import") {
        const r = await request.post(base + "/drafts/review", {
          headers: work.headers,
          data: {
            capture_id: work.captures[0].id,
            object_id: "schedule,1",
            day: 2,
            transitions: [
              { time: [8, 0, 0, 0], native_type: "Real", value_text: "9.5" },
            ],
          },
        });
        const d = await r.json();
        importFile = {
          name: "held.json",
          mimeType: "application/json",
          buffer: await (
            await request.post(base + "/drafts/export", {
              headers: work.headers,
              data: { id: d.id },
            })
          ).body(),
        };
      }
      if (kind === "export") await review(page);
      let entered = () => {};
      const reached = new Promise<void>((r) => (entered = r)),
        gate = new Promise<void>((r) => (release = r));
      const endpoint =
        base +
        "/drafts/" +
        (kind === "review"
          ? "review"
          : kind === "export"
            ? "export"
            : "import");
      await page.route("**" + endpoint, async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        entered();
        await gate;
        await route.fulfill({ response });
      });
      const downloads: string[] = [];
      page.on("download", (d) => downloads.push(d.suggestedFilename()));
      if (kind === "import")
        await lib(page)
          .getByLabel("Import native weekly draft file", { exact: true })
          .setInputFiles(importFile);
      else
        await button(
          page,
          kind === "review"
            ? "Review native weekly draft"
            : "Export exact reviewed weekly draft",
        ).click();
      await reached;
      await chooseWorkspaceTask(page, "Program");
      await chooseWorkspaceTask(page, "Schedules");
      await expect(value(page)).toHaveValue("2.5");
      await value(page).fill("6e-");
      const delivered = page.waitForResponse("**" + endpoint);
      release();
      await (await delivered).finished();
      await expect(value(page)).toHaveValue("6e-");
      await expect(reviewed(page)).toHaveCount(0);
      expect(downloads).toEqual([]);
      await expect(
        lib(page).getByLabel("Native weekly day", { exact: true }),
      ).toHaveValue("1");
    } finally {
      release();
      await finish(work);
    }
  });
test("weekly review retires on visibility and source ABA without losing raw text", async ({
  page,
  request,
}) => {
  const work = await setup(page, request);
  try {
    await value(page).fill("0.1");
    await review(page);
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await expect(reviewed(page)).toHaveCount(0);
    await expect(value(page)).toHaveValue("0.1");
    await review(page);
    await open(page, work.captures[1].id);
    await open(page, work.captures[0].id);
    await expect(value(page)).toHaveValue("0.1");
    await expect(reviewed(page)).toHaveCount(0);
  } finally {
    await finish(work);
  }
});
