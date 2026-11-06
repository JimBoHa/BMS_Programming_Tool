import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import {
  removalFixture,
  enterRemoval,
  showRemoval,
  removalPanel,
  removalReview,
  reviewRemoval,
  saveRemoval,
  inspectRemoval,
} from "./caf-connection-removal-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { editScalar } from "./caf-scalar-draft-recovery-fixture";
import { connectionSeal } from "../src/nativeConnectionContract";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

for (const width of [1440, 390])
  for (const kind of ["normal", "last", "duplicate"])
    test(`${width}px ${kind} removes one exact pair, saves original proof and explicitly opens the verified local copy`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      const index = kind === "normal" ? 1 : 0,
        f = removalFixture(kind, index);
      await enterRemoval(page, f, index);
      const field: string[] = [];
      page.on("request", (r) => {
        if (new URL(r.url()).pathname.startsWith("/api/bacnet/"))
          field.push(r.url());
      });
      let exactReport: Buffer | undefined;
      await page.route("**/connection-removal/preview", async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        exactReport = await response.body();
        await route.fulfill({ response });
      });
      const reviewed = await reviewRemoval(page);
      await expect(reviewed).toContainText(
        kind === "duplicate"
          ? "1 other recorded writer(s) remain"
          : "No recorded writer remains",
      );
      await expect(page.locator(".caf-graph-summary")).toContainText(
        `${f.diagram.connections.length} connections`,
      );
      const reportDownload = page.waitForEvent("download");
      await reviewed
        .getByRole("button", { name: "Save exact removal review", exact: true })
        .click();
      expect(readFileSync((await (await reportDownload).path())!)).toEqual(
        exactReport,
      );
      const download = await saveRemoval(page),
        file = (await download.path())!;
      expect(readFileSync(file)).toEqual(Buffer.from(f.output, "base64"));
      const after = inspectRemoval(file),
        remaining = f.diagram.connections.filter((w: any) => w.index !== index);
      expect(after.hash).toBe(f.review.removal.output_sha256);
      expect(after.graph.connections.map((w: any) => w.raw)).toEqual(
        remaining.map((w: any) => w.raw),
      );
      expect(after.graph.connections.map((w: any) => w.continuation)).toEqual(
        remaining.map((w: any) => w.continuation),
      );
      expect(after.graph.blocks).toEqual(f.diagram.blocks);
      expect(after.graph.execution_order).toEqual(f.diagram.execution_order);
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("authored-removal.caf");
      await expect(
        removalPanel(page).locator("button.primary:visible"),
      ).toHaveCount(1);
      await page.screenshot({
        path: info.outputPath(`caf-removal-${kind}-${width}.png`),
        fullPage: true,
      });
      await reviewed
        .getByRole("button", { name: "Open CAF copy", exact: true })
        .click();
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("authored-removal-connection-removed.caf");
      await expect(page.locator(".caf-graph-summary")).toContainText(
        `${remaining.length} connections`,
      );
      await expect(
        page.getByLabel("Native CAF diagram", { exact: true }),
      ).toHaveValue(f.diagram.ref);
      expect(field).toEqual([]);
    });

test("empty source explains unavailable removal and unsupported source preserves original selection", async ({
  page,
}) => {
  await enterRemoval(page, removalFixture("empty"));
  await expect(removalPanel(page)).toContainText("no selected connection");
  await expect(
    removalPanel(page).getByRole("button", {
      name: "Review connection removal",
      exact: true,
    }),
  ).toBeDisabled();
  await enterRemoval(page, removalFixture("unsupported"));
  await removalPanel(page)
    .getByRole("button", { name: "Review connection removal", exact: true })
    .click();
  await expect(removalPanel(page).getByRole("alert")).toBeVisible();
  await expect(removalPanel(page)).toContainText(
    "Retained removal proposal: connection #0",
  );
  await expect(removalReview(page)).toHaveCount(0);
});

test("390px long original identities and proof hashes wrap within the removal view", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const f = removalFixture("long");
  expect(f.source.source_ref.length).toBeGreaterThanOrEqual(51);
  await enterRemoval(page, f);
  await reviewRemoval(page);
  await removalReview(page)
    .getByText("Removal evidence", { exact: true })
    .click();
  const panel = removalPanel(page);
  await expect(
    panel.locator("code").filter({ hasText: f.source.source_ref }),
  ).toHaveText(f.source.source_ref);
  await expect(
    panel.locator("code").filter({ hasText: f.source.target_ref }),
  ).toHaveText(f.source.target_ref);
  const bounds = await panel.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const lines = Array.from(element.querySelectorAll("code")).flatMap(
      (code) => {
        const range = document.createRange();
        range.selectNodeContents(code);
        return Array.from(range.getClientRects()).map((rect) => ({
          left: rect.left,
          right: rect.right,
        }));
      },
    );
    return {
      left: box.left,
      right: box.right,
      lines,
      width: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
    };
  });
  expect(bounds.lines.length).toBeGreaterThan(6);
  for (const line of bounds.lines) {
    expect(line.left).toBeGreaterThanOrEqual(bounds.left - 1);
    expect(line.right).toBeLessThanOrEqual(bounds.right + 1);
  }
  expect(bounds.scroll).toBeLessThanOrEqual(bounds.width);
  await panel
    .locator("code")
    .filter({ hasText: f.source.source_ref })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("caf-removal-long-reference-viewport-390.png"),
  });
  await removalReview(page)
    .getByText("Removal evidence", { exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: info.outputPath("caf-removal-long-evidence-viewport-390.png"),
  });
});

test("navigation retains exact removal proposal without restoring review, and explicit discard releases conflicting graph edits", async ({
  page,
}) => {
  await enterRemoval(page);
  await reviewRemoval(page);
  await chooseWorkspaceTask(page, "Overview");
  await showRemoval(page);
  await expect(removalPanel(page)).toContainText(
    "Retained removal proposal: connection #0",
  );
  await expect(removalReview(page)).toHaveCount(0);
  await showRemoval(page, 1);
  await expect(removalPanel(page)).toContainText(
    "Another original wire is retained",
  );
  await expect(
    removalPanel(page).getByRole("button", {
      name: "Review connection removal",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toBeDisabled();
  await removalPanel(page)
    .getByRole("button", { name: "Select retained connection #0", exact: true })
    .click();
  await expect(removalPanel(page)).toContainText("Selected original record#0");
  await reviewRemoval(page);
  await removalPanel(page)
    .getByRole("button", { name: "Discard removal proposal", exact: true })
    .click();
  await expect(removalPanel(page)).not.toContainText(
    "Retained removal proposal",
  );
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toBeEnabled();
});

test("existing rewire proposal blocks removal without silently clearing or combining it", async ({
  page,
}) => {
  await enterRemoval(page);
  await page
    .getByLabel("Native replacement source", { exact: true })
    .selectOption("8-1/575_1.2_11");
  await expect(removalPanel(page)).toContainText(
    "Another unexported graph proposal",
  );
  await expect(
    removalPanel(page).getByRole("button", {
      name: "Review connection removal",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toHaveValue("8-1/575_1.2_11");
  await page
    .getByLabel("Native replacement source", { exact: true })
    .selectOption("");
  await reviewRemoval(page);
  await expect(
    page.getByLabel("Native replacement source", { exact: true }),
  ).toBeDisabled();
});

for (const stage of ["source", "preview", "export"])
  test(`altered ${stage} evidence produces no download, open authority or original change`, async ({
    page,
  }) => {
    await enterRemoval(page);
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route(`**/connection-removal/${stage}`, async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      if (stage === "export")
        return route.fulfill({
          response,
          headers: {
            ...response.headers(),
            "X-Studio-Artifact-Sha256": "0".repeat(64),
          },
        });
      const value = await response.json();
      if (stage === "source") {
        value.target_remaining_writer_count = 99;
        const { selection_sha256, ...body } = value;
        value.selection_sha256 = await connectionSeal(body);
      } else {
        value.removal.preserved.destination_configuration = false;
        const { removal_sha256, ...body } = value.removal;
        value.removal.removal_sha256 = await connectionSeal(body);
        const { review_sha256, ...outer } = value;
        value.review_sha256 = await connectionSeal(outer);
      }
      await route.fulfill({ response, json: value });
    });
    if (stage === "export") {
      await reviewRemoval(page);
      await removalReview(page)
        .getByRole("button", {
          name: "Save connection removal CAF copy",
          exact: true,
        })
        .click();
    } else
      await removalPanel(page)
        .getByRole("button", { name: "Review connection removal", exact: true })
        .click();
    await expect(removalPanel(page).getByRole("alert")).toContainText(/proof/);
    await expect(
      removalPanel(page).getByRole("button", {
        name: "Open CAF copy",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-removal.caf");
    expect(downloads).toBe(0);
  });

for (const stage of ["source", "preview", "export", "open"])
  test(`late ${stage} after task ABA cannot restore review, download or replace the original`, async ({
    page,
  }) => {
    await enterRemoval(page);
    if (stage === "export" || stage === "open") await reviewRemoval(page);
    if (stage === "open") await saveRemoval(page);
    let release!: () => void, started!: () => void;
    const gate = new Promise<void>((r) => (release = r)),
      entered = new Promise<void>((r) => (started = r));
    const pattern =
      stage === "open" ? "**/api/caf" : `**/connection-removal/${stage}`;
    await page.route(pattern, async (route) => {
      if (stage === "open") {
        started();
        await gate;
        await route.continue();
        return;
      }
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    });
    const returned = page.waitForResponse((r) =>
      stage === "open"
        ? new URL(r.url()).pathname === "/api/caf"
        : r.url().endsWith(`/connection-removal/${stage}`),
    );
    let downloads = 0;
    page.on("download", () => downloads++);
    await removalPanel(page)
      .getByRole("button", {
        name:
          stage === "open"
            ? "Open CAF copy"
            : stage === "export"
              ? "Save connection removal CAF copy"
              : "Review connection removal",
        exact: true,
      })
      .click();
    await entered;
    await chooseWorkspaceTask(page, "Overview");
    await showRemoval(page);
    release();
    expect(await (await returned).finished()).toBeNull();
    await page.unroute(pattern);
    await expect(removalReview(page)).toHaveCount(0);
    await expect(removalPanel(page)).toContainText(
      "Retained removal proposal: connection #0",
    );
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-removal.caf");
    expect(downloads).toBe(0);
    await reviewRemoval(page);
  });

test("accepted failed CAF replacement retires held review while preserving its source-bound draft", async ({
  page,
}) => {
  await enterRemoval(page);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r));
  await page.route("**/connection-removal/preview", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    started();
    await gate;
    await route.fulfill({ response });
  });
  const returned = page.waitForResponse((r) =>
    r.url().endsWith("/connection-removal/preview"),
  );
  await removalPanel(page)
    .getByRole("button", { name: "Review connection removal", exact: true })
    .click();
  await entered;
  page.once("dialog", (d) => d.accept());
  const replacement = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/caf" &&
      r.request().method() === "POST",
  );
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "bad.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("not a CAF"),
    });
  expect((await replacement).status()).toBeGreaterThanOrEqual(400);
  release();
  expect(await (await returned).finished()).toBeNull();
  await showRemoval(page);
  await expect(removalReview(page)).toHaveCount(0);
  await expect(removalPanel(page)).toContainText(
    "Retained removal proposal: connection #0",
  );
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-removal.caf");
});

for (const outcome of ["rejected", "wrong identity"])
  test(`${outcome} explicit open keeps original and verified retry`, async ({
    page,
  }) => {
    await enterRemoval(page);
    await reviewRemoval(page);
    await saveRemoval(page);
    await page.route("**/api/caf", (route) =>
      route.fulfill({
        status: outcome === "rejected" ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify(
          outcome === "rejected"
            ? { detail: "Authored upload unavailable" }
            : { sha256: "0".repeat(64) },
        ),
      }),
    );
    await removalPanel(page)
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(removalPanel(page).getByRole("alert")).toContainText(
      outcome === "rejected"
        ? "Authored upload unavailable"
        : "identity does not match",
    );
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-removal.caf");
    await page.unroute("**/api/caf");
    await removalPanel(page)
      .getByRole("button", { name: "Open CAF copy", exact: true })
      .click();
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-removal-connection-removed.caf");
  });

test("explicit open cancellation preserves unrelated scalar work, and same-original reopen retains only its saved proposal", async ({
  page,
}) => {
  const f = removalFixture();
  await enterRemoval(page, f);
  await editScalar(page, "Block 10", "3113", "-");
  await showRemoval(page);
  await reviewRemoval(page);
  await saveRemoval(page);
  const dismissed = new Promise<string>((resolve) => {
    page.once("dialog", async (d) => {
      const message = d.message();
      await d.dismiss();
      resolve(message);
    });
  });
  await removalPanel(page)
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  expect(await dismissed).toContain(
    "Other unexported CAF edits will be cleared",
  );
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-removal.caf");
  await expect(
    removalPanel(page).getByRole("button", {
      name: "Open CAF copy",
      exact: true,
    }),
  ).toBeEnabled();
  page.once("dialog", (d) => d.accept());
  await removalPanel(page)
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-removal-connection-removed.caf");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "original-again.caf",
      mimeType: "application/octet-stream",
      buffer: Buffer.from(f.caf, "base64"),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("original-again.caf");
  await showRemoval(page);
  await expect(removalPanel(page)).toContainText("A copy was exported");
  await expect(removalReview(page)).toHaveCount(0);
});

test("pagehide retires a reviewed copy without discarding original removal selection", async ({
  page,
}) => {
  await enterRemoval(page);
  await reviewRemoval(page);
  await saveRemoval(page);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await showRemoval(page);
  await expect(removalReview(page)).toHaveCount(0);
  await expect(removalPanel(page)).toContainText("Retained removal proposal");
});

test("keyboard wire selection and repeated Open gesture retain one owned upload", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enterRemoval(page);
  const second = page.getByRole("button", {
    name: "Select native connection 1",
    exact: true,
  });
  await second.focus();
  await second.press("Enter");
  await expect(second).toHaveAttribute("aria-pressed", "true");
  await reviewRemoval(page);
  await saveRemoval(page);
  let release!: () => void,
    started!: () => void,
    count = 0;
  const gate = new Promise<void>((r) => (release = r)),
    entered = new Promise<void>((r) => (started = r));
  await page.route("**/api/caf", async (route) => {
    count++;
    started();
    await gate;
    await route.continue();
  });
  const returned = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/caf" &&
      r.request().method() === "POST",
  );
  await removalPanel(page)
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  await entered;
  expect(count).toBe(1);
  release();
  expect(await (await returned).finished()).toBeNull();
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored-removal-connection-removed.caf");
  expect(count).toBe(1);
});

for (const retirement of [false, true])
  test(`controller entry retains its exact route and local CAF removal ${retirement ? "retires pending open on interface close" : "adds no peer traffic"}`, async ({
    page,
  }, info) => {
    const peer = await nativeDefaultPeer(),
      f = removalFixture();
    const profiles: Promise<void>[] = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/api/bacnet/controller/profile"))
        profiles.push(
          request.response().then(async (response) => {
            expect(response?.status()).toBe(200);
            expect(await response?.finished()).toBeNull();
          }),
        );
    });
    let closed = false;
    try {
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
        .getByRole("region", {
          name: "Known controller connection",
          exact: true,
        })
        .getByRole("button", { name: "Open controller", exact: true })
        .click();
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      const choosing = page.waitForEvent("filechooser");
      await page.getByRole("button", { name: "Open CAF", exact: true }).click();
      await (
        await choosing
      ).setFiles({
        name: "routed.caf",
        mimeType: "application/octet-stream",
        buffer: Buffer.from(f.caf, "base64"),
      });
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText("routed.caf");
      await page.getByRole("button", { name: "Edit", exact: true }).click();
      await showRemoval(page);
      await Promise.all(profiles);
      expect(profiles.length).toBeGreaterThan(0);
      const before = await peer.command("stats");
      await reviewRemoval(page);
      await saveRemoval(page);
      let release!: () => void, started!: () => void;
      const gate = new Promise<void>((r) => (release = r)),
        entered = new Promise<void>((r) => (started = r));
      if (retirement)
        await page.route("**/api/caf", async (route) => {
          started();
          await gate;
          await route.continue();
        });
      const returned = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === "/api/caf" &&
          r.request().method() === "POST",
      );
      await removalPanel(page)
        .getByRole("button", { name: "Open CAF copy", exact: true })
        .click();
      if (retirement) {
        await entered;
        await page
          .getByLabel("Working context", { exact: true })
          .getByRole("button", { name: "Change controller", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Close BACnet interface", exact: true })
          .click();
        closed = true;
        await showRemoval(page);
        release();
      }
      expect(await (await returned).finished()).toBeNull();
      await expect(
        page.getByLabel("Current CAF archive", { exact: true }),
      ).toHaveText(retirement ? "routed.caf" : "routed-connection-removed.caf");
      if (retirement) await expect(removalReview(page)).toHaveCount(0);
      const after = await peer.command("stats");
      expect(after.request_types).toEqual(before.request_types);
      expect(after.events).toEqual(before.events);
      await info.attach("local removal peer evidence", {
        body: Buffer.from(JSON.stringify({ before, after })),
        contentType: "application/json",
      });
      await expect(
        page.getByLabel("Selected controller path", { exact: true }),
      ).toContainText("3001:7");
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText("unverified");
    } finally {
      if (!closed) {
        await page
          .getByLabel("Working context", { exact: true })
          .getByRole("button", { name: "Change controller", exact: true })
          .click();
        await page
          .getByRole("button", { name: "Close BACnet interface", exact: true })
          .click();
      }
      peer.close();
    }
  });
