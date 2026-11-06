import { test, expect, type Page } from "@playwright/test";
import {
  enterRemoval,
  removalFixture,
  removalPanel,
  removalReview,
  reviewRemoval,
  saveRemoval,
  showRemoval,
} from "./caf-connection-removal-fixture";

async function originalRemains(page: Page, name = "authored-removal.caf") {
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText(name);
  await expect(page.locator(".caf-graph-summary")).toContainText(
    "2 connections",
  );
}

async function notSaved(page: Page) {
  await expect(removalPanel(page)).toContainText(
    "Retained removal proposal: connection #0",
  );
  await expect(removalPanel(page)).toContainText("Not exported.");
  await expect(removalPanel(page)).not.toContainText("A copy was exported");
  await expect(
    removalPanel(page).getByRole("button", {
      name: "Open CAF copy",
      exact: true,
    }),
  ).toHaveCount(0);
}

async function upload(
  page: Page,
  name: string,
  buffer: Buffer,
  successful = true,
) {
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname === "/api/caf" &&
      r.request().method() === "POST",
  );
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer,
    });
  expect((await response).ok()).toBe(successful);
  if (successful)
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText(name);
}

for (const stage of ["source", "preview"])
  test(`a valid sealed ${stage} for another occurrence in the same source cannot authorize this selection`, async ({
    page,
  }) => {
    const selected = removalFixture("normal", 0),
      other = removalFixture("normal", 1);
    expect(selected.hash).toBe(other.hash);
    expect(selected.source.connection_count).toBe(
      other.source.connection_count,
    );
    await enterRemoval(page, selected);
    const requests: string[] = [];
    let downloads = 0;
    page.on("download", () => downloads++);
    page.on("request", (request) => {
      if (request.url().includes("/connection-removal/"))
        requests.push(new URL(request.url()).pathname.split("/").at(-1)!);
    });
    const pattern = `**/connection-removal/${stage}`;
    await page.route(pattern, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        // Both payloads are genuine independently produced, self-consistent proofs.
        // Only their selected occurrence differs from the visible user selection.
        json: stage === "source" ? other.source : other.review,
      }),
    );
    await removalPanel(page)
      .getByRole("button", { name: "Review connection removal", exact: true })
      .click();
    await expect(removalPanel(page).getByRole("alert")).toContainText(/proof/);
    await expect(removalReview(page)).toHaveCount(0);
    await notSaved(page);
    await originalRemains(page);
    expect(requests).toEqual(
      stage === "source" ? ["source"] : ["source", "preview"],
    );
    expect(downloads).toBe(0);
    await page.unroute(pattern);
    await reviewRemoval(page);
    await expect(removalReview(page)).toContainText(
      "Reviewed connection #0 removal",
    );
    expect(downloads).toBe(0);
  });

test("substituted export bytes fail even when every proof header is unchanged", async ({
  page,
}) => {
  await enterRemoval(page);
  await reviewRemoval(page);
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route("**/connection-removal/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    const original = await response.body(),
      changed = Buffer.from(original);
    changed[changed.length - 1] ^= 1;
    expect(changed).not.toEqual(original);
    await route.fulfill({ response, body: changed });
  });
  await removalReview(page)
    .getByRole("button", {
      name: "Save connection removal CAF copy",
      exact: true,
    })
    .click();
  await expect(removalPanel(page).getByRole("alert")).toContainText(
    "bytes or proof do not match",
  );
  await notSaved(page);
  await originalRemains(page);
  expect(downloads).toBe(0);
  await page.unroute("**/connection-removal/export");
  await saveRemoval(page);
  await expect(removalPanel(page)).toContainText("A copy was exported");
  expect(downloads).toBe(1);
});

for (const replacement of [
  "accepted failed upload",
  "different source then same original",
])
  test(`a held export after ${replacement} cannot download or mark the retained draft saved`, async ({
    page,
  }) => {
    const original = removalFixture();
    await enterRemoval(page, original);
    await reviewRemoval(page);
    let release!: () => void, started!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve)),
      entered = new Promise<void>((resolve) => (started = resolve));
    const pattern = "**/connection-removal/export";
    await page.route(pattern, async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      started();
      await gate;
      await route.fulfill({ response });
    });
    let downloads = 0;
    page.on("download", () => downloads++);
    const returned = page.waitForResponse((r) =>
      r.url().endsWith("/connection-removal/export"),
    );
    await removalReview(page)
      .getByRole("button", {
        name: "Save connection removal CAF copy",
        exact: true,
      })
      .click();
    await entered;
    const dialogs: string[] = [];
    page.on("dialog", (dialog) => {
      dialogs.push(dialog.message());
      void dialog.accept();
    });
    let currentName = "authored-removal.caf";
    if (replacement === "accepted failed upload") {
      await upload(
        page,
        "invalid-removal-source.caf",
        Buffer.from("not a CAF"),
        false,
      );
    } else {
      await upload(
        page,
        "different.caf",
        Buffer.from(removalFixture("last").caf, "base64"),
      );
      currentName = "same-original-again.caf";
      await upload(page, currentName, Buffer.from(original.caf, "base64"));
    }
    expect(dialogs).toHaveLength(1);
    expect(dialogs[0]).toContain("Discard unexported CAF edits");
    await showRemoval(page);
    release();
    expect(await (await returned).finished()).toBeNull();
    await page.unroute(pattern);
    await expect(removalReview(page)).toHaveCount(0);
    await notSaved(page);
    await originalRemains(page, currentName);
    // A fresh complete review also settles the released asynchronous work; its
    // success must not cause the former export to gain saved/open authority.
    await reviewRemoval(page);
    await notSaved(page);
    expect(downloads).toBe(0);
    await saveRemoval(page);
    expect(downloads).toBe(1);
  });

test("a held removal-copy upload cannot replace a reopened original with the same hash", async ({
  page,
}) => {
  const original = removalFixture();
  await enterRemoval(page, original);
  await reviewRemoval(page);
  await saveRemoval(page);
  let release!: () => void, started!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    entered = new Promise<void>((resolve) => (started = resolve));
  let first = true;
  await page.route("**/api/caf", async (route) => {
    if (first && route.request().method() === "POST") {
      first = false;
      started();
      await gate;
    }
    // Keep the native browser multipart body; route.fetch cannot replay a
    // browser-created File consistently in WebKit.
    await route.continue();
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  const requested = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === "/api/caf" &&
      request.method() === "POST",
  );
  await removalReview(page)
    .getByRole("button", { name: "Open CAF copy", exact: true })
    .click();
  const heldRequest = await requested;
  const returned = page.waitForResponse(
    (response) => response.request() === heldRequest,
  );
  await entered;
  await upload(
    page,
    "different.caf",
    Buffer.from(removalFixture("last").caf, "base64"),
  );
  await upload(
    page,
    "original-after-open.caf",
    Buffer.from(original.caf, "base64"),
  );
  await showRemoval(page);
  release();
  const response = await returned;
  expect(response.status()).toBe(200);
  expect(await response.finished()).toBeNull();
  await page.unroute("**/api/caf");
  await originalRemains(page, "original-after-open.caf");
  await expect(removalReview(page)).toHaveCount(0);
  await expect(removalPanel(page)).toContainText("A copy was exported");
  await reviewRemoval(page);
  await expect(
    removalReview(page).getByRole("button", {
      name: "Open CAF copy",
      exact: true,
    }),
  ).toHaveCount(0);
  await originalRemains(page, "original-after-open.caf");
  expect(downloads).toBe(0);
});
