import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
async function holdDebounce(page: Page) {
  await page.addInitScript(() => {
    const original = window.setTimeout.bind(window),
      clear = window.clearTimeout.bind(window),
      held = new Map<number, () => void>();
    (window as any).__runDraftTimers = () => {
      const pending = [...held.values()];
      held.clear();
      pending.forEach((f) => f());
    };
    window.setTimeout = ((
      handler: TimerHandler,
      delay?: number,
      ...args: any[]
    ) => {
      if (delay === 200 && typeof handler === "function") {
        const id = original(() => {}, 2147483647);
        held.set(id, () => handler(...args));
        return id;
      }
      return original(handler, delay, ...args);
    }) as typeof window.setTimeout;
    window.clearTimeout = (id?: number) => {
      held.delete(id!);
      clear(id);
    };
  });
}
async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByLabel("Program name", { exact: true })).toBeVisible();
}
async function macroSource(page: Page) {
  const buffer = execFileSync(
    python,
    [
      "-c",
      "from tests.test_macro_integration import nested_rate_program;p=nested_rate_program();[(setattr(n,'x',i*250),setattr(n,'y',100)) for i,n in enumerate(p.nodes)];[(n.update(x=i*250,y=100)) for d in p.metadata['macros']['definitions'] for i,n in enumerate(d['program']['nodes'])];print(p.model_dump_json())",
    ],
    { cwd: root },
  );
  await page
    .locator(
      'input[type=file][accept=".json,.st,.xml,.graphml,.sedona.zip,.sax,.sab,.bog,.bas"]',
    )
    .setInputFiles({
      name: "recover-macro.bms.json",
      mimeType: "application/json",
      buffer,
    });
  await expect(page.locator(".toast")).toContainText(
    "Imported as a new local project",
  );
}
async function editMacro(page: Page) {
  await page.getByRole("button", { name: "Macros", exact: true }).click();
  await page
    .getByRole("button", { name: "Edit definition on wiresheet", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toContainText("limiter");
  await page.locator('.react-flow__node[data-id="limit"]').click();
  return page
    .locator(".inspector label")
    .filter({ hasText: /^rate$/ })
    .locator("input");
}

test("fast reload flushes latest ordinary source while200ms debounce is held", async ({
  page,
}) => {
  await holdDebounce(page);
  await open(page);
  await page.getByLabel("Program name", { exact: true }).fill("earlier draft");
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Latest unsaved draft");
  expect(
    await page.evaluate(() => localStorage.getItem("bms-studio-draft-v1")),
  ).toBeNull();
  await page.reload();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Latest unsaved draft",
  );
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("bms-studio-draft-v1")!).name,
    ),
  ).toBe("Latest unsaved draft");
});

test("fast macro reload retains definition draft; apply and discard persist latest parent before clearing macro", async ({
  page,
}) => {
  await holdDebounce(page);
  await open(page);
  await macroSource(page);
  let rate = await editMacro(page);
  await rate.fill("3.75");
  await page.reload();
  await expect(page.locator(".macro-edit-banner")).toContainText("limiter");
  await page.locator('.react-flow__node[data-id="limit"]').click();
  rate = page
    .locator(".inspector label")
    .filter({ hasText: /^rate$/ })
    .locator("input");
  await expect(rate).toHaveValue("3.75");
  await rate.fill("4");
  await page
    .getByRole("button", { name: "Apply definition changes", exact: true })
    .click();
  await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
  expect(
    await page.evaluate(() => localStorage.getItem("bms-studio-macro-edit-v1")),
  ).toBeNull();
  rate = await editMacro(page);
  await expect(rate).toHaveValue("4");
  await rate.fill("9");
  await page
    .getByRole("button", { name: "Discard definition changes", exact: true })
    .click();
  await page.reload();
  await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
  rate = await editMacro(page);
  await expect(rate).toHaveValue("4");
});

for (const event of ["pagehide", "beforeunload", "visibilitychange"])
  test(`${event} flush uses latest ready snapshot`, async ({ page }) => {
    await holdDebounce(page);
    await open(page);
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Lifecycle " + event);
    await page.evaluate((event) => {
      if (event === "visibilitychange") {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "hidden",
        });
        document.dispatchEvent(new Event(event));
      } else window.dispatchEvent(new Event(event));
    }, event);
    expect(
      await page.evaluate(
        () => JSON.parse(localStorage.getItem("bms-studio-draft-v1")!).name,
      ),
    ).toBe("Lifecycle " + event);
  });

test("boot lifecycle events cannot overwrite saved recovery before initialization completes", async ({
  page,
}) => {
  await holdDebounce(page);
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((r) => (release = r)),
    requested = new Promise<void>((r) => (seen = r));
  await page.addInitScript(() => {
    if (!localStorage.getItem("seeded-recovery")) {
      localStorage.setItem(
        "bms-studio-draft-v1",
        JSON.stringify({
          schema_version: 1,
          id: "seed",
          name: "Previous good draft",
          description: "",
          revision: 0,
          scan_seconds: 1,
          target: {
            family: "universal-runtime",
            model: "",
            firmware: "",
            release_mode: "",
            max_nodes: 2000,
            physical_inputs: null,
            physical_outputs: null,
          },
          nodes: [],
          edges: [],
          metadata: {},
        }),
      );
      localStorage.setItem("seeded-recovery", "yes");
    }
  });
  await page.route("**/api/templates", async (route) => {
    const response = await route.fetch();
    seen();
    await gate;
    await route.fulfill({ response });
  });
  await page.goto("/");
  await requested;
  await page.evaluate(() => {
    window.dispatchEvent(new Event("pagehide"));
    window.dispatchEvent(new Event("beforeunload"));
  });
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("bms-studio-draft-v1")!).name,
    ),
  ).toBe("Previous good draft");
  release();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Previous good draft",
  );
});

test("storage failure preserves prior copy and is visible while validation still runs", async ({
  page,
}) => {
  await holdDebounce(page);
  await open(page);
  await page.evaluate(() => {
    (window as any).__originalDraftWrite = Storage.prototype.setItem;
    localStorage.setItem("bms-studio-draft-v1", "previous-good-copy");
    localStorage.setItem("bms-studio-macro-edit-v1", "previous-macro-copy");
    Storage.prototype.setItem = function (k, v) {
      if (k.startsWith("bms-studio-"))
        throw new DOMException("Test quota failure", "QuotaExceededError");
      return (window as any).__originalDraftWrite.call(this, k, v);
    };
  });
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Current work after storage failure");
  const validated = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/validate") &&
      r.request().postDataJSON().name === "Current work after storage failure",
  );
  await page.evaluate(() => (window as any).__runDraftTimers());
  expect((await validated).ok()).toBe(true);
  await expect(page.getByRole("alert")).toContainText(
    "Browser draft recovery failed",
  );
  expect(
    await page.evaluate(() => localStorage.getItem("bms-studio-draft-v1")),
  ).toBe("previous-good-copy");
  expect(
    await page.evaluate(() => localStorage.getItem("bms-studio-macro-edit-v1")),
  ).toBe("previous-macro-copy");
  await page.evaluate(() => {
    Storage.prototype.setItem = (window as any).__originalDraftWrite;
    window.dispatchEvent(new Event("pagehide"));
  });
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("bms-studio-draft-v1")!).name,
    ),
  ).toBe("Current work after storage failure");
});

test("actual React unmount flushes latest ready source before debounce", async ({
  page,
}) => {
  await holdDebounce(page);
  await page.route("**/assets/index-*.js", async (route) => {
    const response = await route.fetch(),
      source = await response.text();
    const pattern =
      /(\w+\.createRoot\(document\.getElementById\("root"\)\))\.render\(/;
    expect(source).toMatch(pattern);
    await route.fulfill({
      response,
      body: source.replace(pattern, "(window.__draftTestRoot=$1).render("),
    });
  });
  await open(page);
  await page
    .getByLabel("Program name", { exact: true })
    .fill("Unmounted latest draft");
  await page.evaluate(() => (window as any).__draftTestRoot.unmount());
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("bms-studio-draft-v1")!).name,
    ),
  ).toBe("Unmounted latest draft");
});

for (const failure of ["get", "parse"])
  test(`${failure} startup recovery failure blocks every automatic write for the page while editing and saving remain usable`, async ({
    page,
  }) => {
    await holdDebounce(page);
    await page.addInitScript((failure) => {
      const originalGet = Storage.prototype.getItem;
      (window as any).__originalRecoveryGet = originalGet;
      const raw =
        failure === "parse"
          ? "{corrupt-copy"
          : JSON.stringify({
              schema_version: 1,
              id: "precious",
              name: "Precious original",
              description: "",
              revision: 0,
              scan_seconds: 1,
              target: {
                family: "universal-runtime",
                model: "",
                firmware: "",
                release_mode: "",
                max_nodes: 2000,
                physical_inputs: null,
                physical_outputs: null,
              },
              nodes: [],
              edges: [],
              metadata: {},
            });
      if (!originalGet.call(localStorage, "seeded-read-fault")) {
        localStorage.setItem("bms-studio-draft-v1", raw);
        localStorage.setItem("seeded-read-fault", "yes");
      }
      (window as any).__previousRecoveryRaw = raw;
      if (failure === "get")
        Storage.prototype.getItem = function (key) {
          if (key.startsWith("bms-studio-")) throw new Error("read denied");
          return originalGet.call(this, key);
        };
    }, failure);
    await open(page);
    await expect(page.getByRole("alert")).toContainText("recovery unavailable");
    await page.evaluate(() => {
      Storage.prototype.getItem = (window as any).__originalRecoveryGet;
    });
    await page
      .getByRole("button", { name: "New program", exact: true })
      .click();
    await page
      .getByLabel("Program name", { exact: true })
      .fill("Unsaved work while recovery unavailable");
    const validated = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/validate") &&
        r.request().postDataJSON().name ===
          "Unsaved work while recovery unavailable",
    );
    await page.evaluate(() => (window as any).__runDraftTimers());
    expect((await validated).ok()).toBe(true);
    await page
      .getByRole("button", { name: "Save revision", exact: true })
      .click();
    await expect(
      page.getByLabel("Last saved revision", { exact: true }),
    ).toContainText("r1");
    if (failure === "get") {
      await macroSource(page);
      const rate = await editMacro(page);
      await rate.fill("7");
      await page
        .getByRole("button", { name: "Apply definition changes", exact: true })
        .click();
      await expect(page.locator(".macro-edit-banner")).toHaveCount(0);
    }
    await page.evaluate(() => {
      window.dispatchEvent(new Event("pagehide"));
      window.dispatchEvent(new Event("beforeunload"));
      (window as any).__runDraftTimers();
    });
    expect(
      await page.evaluate(
        () =>
          localStorage.getItem("bms-studio-draft-v1") ===
          (window as any).__previousRecoveryRaw,
      ),
    ).toBe(true);
    await expect(page.getByRole("alert")).toContainText("reload to retry");
  });
