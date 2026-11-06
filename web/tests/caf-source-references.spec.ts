import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import {
  seedReferences,
  references,
  enterCafComparison,
  compatibility,
  chooseFile,
  selectReferenceSource,
  saveReference,
  alterStoredReference,
} from "./caf-source-references-fixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";
const report = (page: Page) =>
  page.getByRole("region", {
    name: "Original saved CAF/source report",
    exact: true,
  });
const table = (page: Page) =>
  references(page).getByRole("table", {
    name: "Saved CAF/source reference list",
    exact: true,
  });
const calls = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page, request }) => {
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (await request.post("/api/bacnet/disconnect", { headers, data: {} })).ok(),
  ).toBe(true);
  calls.set(page, []);
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/bacnet\//.test(r.url()))
      calls.get(page)!.push(r.url());
  });
});
async function open(page: Page, ids: any, kind: "backup" | "file" = "backup") {
  const p = await enterCafComparison(page, ids.caf);
  await selectReferenceSource(p, kind, ids[kind]);
  return p;
}
async function saved(page: Page, source: string) {
  const row = table(page).getByRole("row").filter({ hasText: source });
  await expect(row).toBeVisible();
  return row;
}
async function openSaved(page: Page, source: string) {
  await (await saved(page, source))
    .getByRole("button", { name: "Open saved report", exact: true })
    .click();
  await expect(report(page)).toBeVisible();
  return report(page);
}
for (const kind of ["backup", "file"] as const)
  for (const width of [1440, 390]) {
    test(`${kind} reference saves an unfiltered original, deduplicates and removes locally at ${width}px`, async ({
      page,
      request,
    }, info) => {
      const ids = seedReferences();
      await page.setViewportSize({ width, height: 1000 });
      const p = await open(page, ids, kind);
      await p
        .getByLabel("Find comparison records", { exact: true })
        .fill("nothing-will-match-this-search");
      let body: any,
        original = Buffer.alloc(0);
      await page.route(
        `**/api/caf/${ids.hash}/source-references`,
        async (route) => {
          if (route.request().method() === "POST")
            body = route.request().postDataJSON();
          await route.continue();
        },
      );
      await page.route("**/source-references/*/report", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        original = await response.body();
        await route.fulfill({ response });
      });
      await saveReference(page);
      await saved(page, ids[kind]);
      expect(body).toEqual(ids.bodies[kind]);
      await saveReference(page);
      await expect(references(page)).toContainText(
        "This exact CAF/source reference was already saved",
      );
      await expect(table(page).getByRole("row")).toHaveCount(2);
      const r = await openSaved(page, ids[kind]);
      await expect(r).toContainText("Full comparison coverage: 8 CAF objects");
      await expect(r).toContainText(
        "8 of 8 references, unfiltered, offset 0, limit 128",
      );
      const downloading = page.waitForEvent("download");
      await r
        .getByRole("button", {
          name: "Download original saved report",
          exact: true,
        })
        .click();
      expect(readFileSync((await (await downloading).path())!)).toEqual(
        original,
      );
      const result = JSON.parse(original.toString());
      expect(result.application_association_granted).toBe(false);
      expect(result.query).toBe("");
      expect(result.limit).toBe(128);
      await references(page).scrollIntoViewIfNeeded();
      await page.screenshot({
        path: info.outputPath(`${kind}-reference-${width}.png`),
      });
      await (await saved(page, ids[kind]))
        .getByRole("button", { name: "Remove reference", exact: true })
        .click();
      await expect(references(page)).toContainText(
        "No saved references for this original CAF",
      );
      await expect(
        p.getByLabel(
          kind === "backup"
            ? "Native backup for CAF comparison"
            : "Captured File for CAF comparison",
          { exact: true },
        ),
      ).toHaveValue(ids[kind]);
      expect(calls.get(page)).toEqual([]);
      expect(
        (await (await request.get("/api/session")).json()).field_network_open,
      ).toBe(false);
    });
  }
test("same CAF hash restores both reference types without choosing a source; changed CAF does not inherit", async ({
  page,
}) => {
  const ids = seedReferences(),
    p = await open(page, ids);
  await saveReference(page);
  await saved(page, ids.backup);
  await selectReferenceSource(p, "file", ids.file);
  await saveReference(page);
  await saved(page, ids.file);
  await enterCafComparison(page, ids.caf);
  await expect(table(page).getByRole("row")).toHaveCount(3);
  await expect(
    p.getByLabel("Native backup for CAF comparison", { exact: true }),
  ).toHaveValue("");
  await chooseFile(page, ids.other, "other.caf");
  await compatibility(page);
  await expect(references(page)).toContainText(
    "No saved references for this original CAF",
  );
  await chooseFile(page, ids.caf);
  await compatibility(page);
  await expect(table(page).getByRole("row")).toHaveCount(3);
  expect(calls.get(page)).toEqual([]);
});
test("bounded detail page retains full classification and coverage counts", async ({
  page,
}) => {
  const ids = seedReferences();
  ids.caf = ids.large;
  await open(page, ids);
  await saveReference(page);
  const r = await openSaved(page, ids.backup);
  await expect(r).toContainText("158 CAF objects");
  await expect(r).toContainText("128 of 158 references");
  await expect(r).toContainText("Additional record details are not retained");
  await expect(r).toContainText("Recorded identity differences found");
  await expect(
    r.getByRole("table", { name: "Saved record identity counts" }),
  ).toContainText("150");
});
test("missing retained source leaves original saved evidence available without replacing the selection", async ({
  page,
}) => {
  const ids = seedReferences(),
    p = await open(page, ids, "file");
  await saveReference(page);
  await saved(page, ids.file);
  let original = Buffer.alloc(0);
  await page.route("**/source-references/*/report", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    original = await response.body();
    await route.fulfill({ response });
  });
  await openSaved(page, ids.file);
  const before = Buffer.from(original);
  alterStoredReference(ids.file, "missing-source");
  await p
    .getByRole("button", { name: "Refresh captured files", exact: true })
    .click();
  await expect(
    p.getByLabel("Captured File for CAF comparison", { exact: true }),
  ).toHaveValue("");
  await references(page)
    .getByRole("button", { name: "Refresh saved references", exact: true })
    .click();
  await openSaved(page, ids.file);
  expect(original).toEqual(before);
  await expect(references(page)).toContainText(
    "Retained source availability is not revalidated",
  );
  expect(calls.get(page)).toEqual([]);
});
test("corrupt saved evidence is removable but supplies no report or source shortcut", async ({
  page,
  request,
}) => {
  const ids = seedReferences();
  await open(page, ids);
  await saveReference(page);
  await saved(page, ids.backup);
  const listing = await (
    await request.get(`/api/caf/${ids.hash}/source-references`)
  ).json();
  alterStoredReference(listing.references[0].id, "corrupt-report");
  await references(page)
    .getByRole("button", { name: "Refresh saved references", exact: true })
    .click();
  await expect(table(page)).toContainText("Saved reference unavailable");
  await expect(
    references(page).getByRole("button", {
      name: "Open saved report",
      exact: true,
    }),
  ).toHaveCount(0);
  await references(page)
    .getByRole("button", { name: "Remove reference", exact: true })
    .click();
  await expect(references(page)).toContainText(
    "No saved references for this original CAF",
  );
});
test("graph entry and unsaved CAF proposals survive reference actions and navigation", async ({
  page,
}) => {
  const ids = seedReferences();
  await page.goto("/");
  await page
    .getByRole("button", { name: "New application", exact: true })
    .click();
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Keep local graph draft");
  await chooseFile(page, ids.caf);
  const p = await compatibility(page);
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await page
    .locator(".caf-layout tbody tr")
    .filter({ hasText: "Authored controller" })
    .click();
  await page
    .getByLabel("CAF property 2390", { exact: true })
    .fill("Keep unsaved CAF draft");
  await expect(
    page.getByLabel("Working context", { exact: true }),
  ).toContainText("Local changes: 1");
  const working = await page
    .getByLabel("Working context", { exact: true })
    .textContent();
  await compatibility(page);
  await selectReferenceSource(p, "backup", ids.backup);
  await saveReference(page);
  await openSaved(page, ids.backup);
  await expect(references(page)).toContainText(
    "Unsaved CAF proposals remain separate",
  );
  const r = report(page);
  await r
    .getByText("Recorded comparison details and source evidence", {
      exact: true,
    })
    .click();
  await expect(r.locator("pre")).toContainText("Authored controller");
  await expect(r.locator("pre")).not.toContainText("Keep unsaved CAF draft");
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Changes", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Program", exact: true })
    .click();
  await compatibility(page);
  await saved(page, ids.backup);
  await expect(report(page)).toHaveCount(0);
  await expect(page.getByLabel("Working context", { exact: true })).toHaveText(
    working!,
  );
  await page
    .getByRole("navigation", { name: "CAF application tasks" })
    .getByRole("button", { name: "Objects & parameters", exact: true })
    .click();
  await expect(
    page.getByLabel("CAF property 2390", { exact: true }),
  ).toHaveValue("Keep unsaved CAF draft");
  await page
    .getByRole("navigation", { name: "Current task tools", exact: true })
    .getByRole("button", { name: "Graph editor", exact: true })
    .click();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Keep local graph draft",
  );
  expect(calls.get(page)).toEqual([]);
});
for (const change of ["source", "task", "CAF"] as const)
  test(`late saved report is retired after ${change} changes`, async ({
    page,
  }) => {
    const ids = seedReferences(),
      p = await open(page, ids);
    await saveReference(page);
    await saved(page, ids.backup);
    let release!: () => void, started!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve)),
      ready = new Promise<void>((resolve) => (started = resolve));
    await page.route(
      "**/source-references/*/report",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        started();
        await gate;
        await route.fulfill({ response });
      },
      { times: 1 },
    );
    try {
      await (await saved(page, ids.backup))
        .getByRole("button", { name: "Open saved report", exact: true })
        .click();
      await ready;
      if (change === "source") {
        await selectReferenceSource(p, "file", ids.file);
        await selectReferenceSource(p, "backup", ids.backup);
      }
      if (change === "task") {
        await page
          .getByRole("navigation", { name: "Workspace tasks" })
          .getByRole("button", { name: "Changes", exact: true })
          .click();
        await page
          .getByRole("navigation", { name: "Workspace tasks" })
          .getByRole("button", { name: "Program", exact: true })
          .click();
        await compatibility(page);
      }
      if (change === "CAF") {
        await chooseFile(page, ids.other);
        await compatibility(page);
      }
      release();
      await page.unrouteAll({ behavior: "wait" });
      await expect(report(page)).toHaveCount(0);
      await expect(
        references(page).getByRole("button", {
          name: "Download original saved report",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      release();
    }
  });
test("a delayed CAF-owned list survives changing the current source selection", async ({
  page,
  request,
}) => {
  const ids = seedReferences(),
    p = await open(page, ids);
  await saveReference(page);
  await saved(page, ids.backup);
  const headers = {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
  expect(
    (
      await request.post(`/api/caf/${ids.hash}/source-references`, {
        headers,
        data: ids.bodies.file,
      })
    ).ok(),
  ).toBe(true);
  await expect(table(page).getByRole("row")).toHaveCount(2);
  await p
    .getByLabel("Native backup for CAF comparison", { exact: true })
    .selectOption("");
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    ready = new Promise<void>((resolve) => (started = resolve));
  await page.route(
    `**/api/caf/${ids.hash}/source-references`,
    async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 },
  );
  try {
    await references(page)
      .getByRole("button", { name: "Refresh saved references", exact: true })
      .click();
    await ready;
    await p
      .getByLabel("Native backup for CAF comparison", { exact: true })
      .selectOption(ids.backup);
    release();
    await page.unrouteAll({ behavior: "wait" });
    await saved(page, ids.backup);
    await saved(page, ids.file);
    await expect(table(page).getByRole("row")).toHaveCount(3);
    await expect(references(page)).not.toContainText(
      "Reading saved references…",
    );
  } finally {
    release();
  }
});
for (const fault of [
  "wrong-CAF-unavailable",
  "authority",
  "digest",
  "route",
] as const)
  test(`altered ${fault} evidence cannot grant saved-report display`, async ({
    page,
  }) => {
    const ids = seedReferences();
    await open(page, ids);
    await saveReference(page);
    await saved(page, ids.backup);
    if (fault === "wrong-CAF-unavailable" || fault === "authority") {
      await page.route(
        `**/api/caf/${ids.hash}/source-references`,
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            data = await response.json();
          if (fault === "authority")
            data.application_association_granted = true;
          else
            data.references = [
              {
                id: "1".repeat(32),
                caf_sha256: "0".repeat(64),
                state: "unavailable",
                error: "Wrong CAF",
              },
            ];
          await route.fulfill({ response, json: data });
        },
      );
      await references(page)
        .getByRole("button", { name: "Refresh saved references", exact: true })
        .click();
      await expect(references(page).getByRole("alert")).toContainText(
        "Saved reference list does not match",
      );
      await expect(references(page)).not.toContainText("Wrong CAF");
    } else {
      await page.route("**/source-references/*/report", async (route) => {
        const response = await route.fetch({ maxRetries: 0 }),
          data = await response.json();
        if (fault === "route") data.native_backup.target.address = "3001:8";
        const body = JSON.stringify(data),
          headers = {
            ...response.headers(),
            "x-studio-artifact-sha256":
              fault === "digest"
                ? "0".repeat(64)
                : createHash("sha256").update(body).digest("hex"),
          };
        await route.fulfill({ response, body, headers });
      });
      await (await saved(page, ids.backup))
        .getByRole("button", { name: "Open saved report", exact: true })
        .click();
      await expect(references(page).getByRole("alert")).toContainText(
        "Original saved report does not match",
      );
    }
    await expect(report(page)).toHaveCount(0);
    expect(calls.get(page)).toEqual([]);
  });
test("routed controller context stays exact while local reference actions generate zero BACnet work", async ({
  page,
}) => {
  const peer = await nativeDefaultPeer();
  try {
    const ids = seedReferences(undefined, peer.router);
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
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
      .fill("3001:7");
    await page
      .getByLabel("Known Device object", { exact: true })
      .fill("device,5136");
    await page.getByLabel("Known router", { exact: true }).fill(peer.router);
    await page.getByLabel("Known network", { exact: true }).fill("3001");
    await page
      .getByRole("region", { name: "Known controller connection", exact: true })
      .getByRole("button", { name: "Open controller", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Controller overview", exact: true }),
    ).toContainText("Authored controller");
    await chooseFile(page, ids.caf);
    const p = await compatibility(page);
    await selectReferenceSource(p, "file", ids.file);
    const before = await peer.command("stats"),
      working = await page
        .getByLabel("Working context", { exact: true })
        .textContent();
    await saveReference(page);
    await openSaved(page, ids.file);
    await expect(report(page)).toContainText(
      `${peer.router} / network 3001 / station 3001:7`,
    );
    await expect(
      page.getByLabel("Working context", { exact: true }),
    ).toHaveText(working!);
    const after = await peer.command("stats");
    expect(after.events).toEqual(before.events);
    expect(after.request_types).toEqual(before.request_types);
  } finally {
    peer.close();
  }
});
