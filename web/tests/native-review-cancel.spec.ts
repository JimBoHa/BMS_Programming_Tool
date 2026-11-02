import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { calendarControllerPeer } from "./calendar-controller-peer";
import { scheduleControllerPeer } from "./schedule-controller-peer";
import { exceptionControllerPeer } from "./exception-controller-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";

async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
test.afterEach(async ({ request }) => {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await auth(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
});
async function select(page: Page, target: any, initial = true) {
  if (initial) {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  } else
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [name, value] of [
    ["Known controller address", target.address],
    ["Known Device object", target.device],
    ["Known router", target.router || ""],
    ["Known network", target.dnet == null ? "" : String(target.dnet)],
  ])
    await page.getByLabel(name, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Native " + target.device);
  await chooseWorkspaceTask(page, "Schedules");
}

async function captureResponse(
  page: Page,
  endpoint: string,
  expectedOperation?: () => string | undefined,
) {
  let resolve!: (value: any) => void, reject!: (error: unknown) => void;
  const result = new Promise<any>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  const pattern = "**" + endpoint;
  await page.route(pattern, async (route) => {
    if (
      expectedOperation &&
      route.request().postDataJSON()?.operation_id !== expectedOperation()
    ) {
      await route.continue();
      return;
    }
    try {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      const raw = await response.body();
      expect(response.ok(), raw.toString()).toBe(true);
      const data = JSON.parse(raw.toString());
      await route.fulfill({ response, body: raw });
      await page.unroute(pattern);
      resolve(data);
    } catch (error) {
      reject(error);
    }
  });
  return { result };
}
type Domain = "calendar" | "numeric" | "string" | "exception";
async function setup(page: Page, request: APIRequestContext, domain: Domain) {
  const peer =
    domain === "calendar"
      ? await calendarControllerPeer(true)
      : domain === "exception"
        ? await exceptionControllerPeer(true)
        : await scheduleControllerPeer(
            domain === "string",
            domain === "string",
          );
  const base =
    domain === "calendar"
      ? "/api/bacnet/calendars/writes"
      : domain === "exception"
        ? "/api/bacnet/schedule-exceptions/writes"
        : "/api/bacnet/schedules/writes";
  const headers = await auth(request);
  try {
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers,
          data: { local_address: peer.local },
        })
      ).ok(),
    ).toBe(true);
    const acquired = await request.post("/api/bacnet/schedules/read", {
      headers,
      data: {
        ...peer.target,
        object_ids: [domain === "calendar" ? "calendar,1" : "schedule,1"],
        operation_id: "cancel_capture_" + crypto.randomUUID(),
      },
    });
    expect(acquired.ok(), await acquired.text()).toBe(true);
    const report = await acquired.json();
    expect(report.complete).toBe(true);
    const saved = await request.post("/api/bacnet/schedules/library/save", {
      headers,
      data: { id: report.id },
    });
    expect(saved.ok()).toBe(true);
    const capture = await saved.json();
    await select(page, peer.target);
    const library = page.getByRole("region", {
      name: "Native Schedule capture library",
      exact: true,
    });
    await library
      .getByRole("button", {
        name: "Open capture " + capture.id.slice(0, 12),
        exact: true,
      })
      .click();
    let panel, previewName, applyName;
    if (domain === "calendar") {
      const details = library.getByLabel("Captured Calendar dates", {
        exact: true,
      });
      await details.locator("summary").click();
      const editor = page.getByRole("region", {
        name: "Captured Calendar date editor",
        exact: true,
      });
      await expect(
        editor.getByLabel("Captured Calendar for date draft", { exact: true }),
      ).toHaveValue("calendar,1");
      while (
        await editor
          .getByRole("button", { name: /^Remove Calendar entry/ })
          .count()
      )
        await editor
          .getByRole("button", { name: /^Remove Calendar entry/ })
          .first()
          .click();
      await editor
        .getByRole("button", { name: "Add Calendar entry", exact: true })
        .click();
      await editor
        .getByLabel("Calendar entry 1 year", { exact: true })
        .fill("2026");
      await editor
        .getByLabel("Calendar entry 1 month", { exact: true })
        .selectOption("11");
      await editor
        .getByLabel("Calendar entry 1 day", { exact: true })
        .selectOption("2");
      await editor
        .getByRole("button", { name: "Review Calendar dates", exact: true })
        .click();
      panel = editor.getByRole("region", {
        name: "Calendar controller deployment",
        exact: true,
      });
      await panel
        .getByRole("button", {
          name: "Open Calendar deployment and receipts",
          exact: true,
        })
        .click();
      await panel
        .getByLabel("Declared Calendar operator", { exact: true })
        .fill("Authored operator");
      await panel
        .getByLabel("Calendar change rationale", { exact: true })
        .fill("Cancel ready review");
      previewName = "Review Calendar controller change";
      applyName = "Apply Calendar dates";
    } else if (domain === "exception") {
      const details = library.getByLabel("Captured Schedule exceptions", {
        exact: true,
      });
      await details.locator("summary").click();
      const editor = page.getByRole("region", {
        name: "Captured Schedule exception editor",
        exact: true,
      });
      await expect(
        editor.getByLabel("Captured Schedule for exceptions", { exact: true }),
      ).toHaveValue("schedule,1");
      await editor
        .getByLabel("Exception event priority", { exact: true })
        .fill("9");
      await editor
        .getByRole("button", { name: "Review exception draft", exact: true })
        .click();
      await expect(
        editor.getByLabel("Native exception draft review", { exact: true }),
      ).toBeVisible();
      panel = editor.getByRole("region", {
        name: "Exception controller deployment",
        exact: true,
      });
      await panel
        .getByRole("button", {
          name: "Open exception deployment and receipts",
          exact: true,
        })
        .click();
      await panel
        .getByLabel("Declared Exception operator", { exact: true })
        .fill("Authored operator");
      await panel
        .getByLabel("Exception change rationale", { exact: true })
        .fill("Cancel invalid preview");
      previewName = "Review Exception controller change";
      applyName = "Apply Schedule exceptions";
    } else {
      await library
        .getByLabel(
          domain === "string"
            ? "Transition 1 CharacterString JSON literal"
            : "Transition 1 exact value text",
          { exact: true },
        )
        .fill(domain === "string" ? '"changed"' : "2.5");
      await library
        .getByRole("button", {
          name: "Review native weekly draft",
          exact: true,
        })
        .click();
      await expect(
        library.getByLabel("Native weekly draft review", { exact: true }),
      ).toBeVisible();
      panel = page.getByRole("region", {
        name: "Native weekly-day deployment",
        exact: true,
      });
      await panel
        .getByRole("button", {
          name: "Open native deployment and local history",
          exact: true,
        })
        .click();
      await panel
        .getByLabel("Declared native write operator", { exact: true })
        .fill("Authored operator");
      await panel
        .getByLabel("Native write rationale", { exact: true })
        .fill("Cancel ready review");
      previewName = "Preview fresh native weekly-day write";
      applyName = "Apply one native weekly-day request";
    }
    async function preview() {
      const { result: captured } = await captureResponse(
        page,
        base + "/preview",
      );
      await panel
        .getByRole("button", { name: previewName, exact: true })
        .click();
      const plan = await captured;
      expect(plan.can_apply, JSON.stringify(plan.reasons)).toBe(true);
      await expect(
        panel.getByRole("button", { name: applyName, exact: true }),
      ).toBeEnabled();
      return plan;
    }
    return {
      peer,
      base,
      headers,
      library,
      panel,
      capture,
      preview,
      applyName,
      previewName,
    };
  } catch (error) {
    await peer.close();
    throw error;
  }
}
for (const domain of ["calendar", "numeric", "string"] as const)
  for (const action of ["close", "visibility", "task", "edit"] as const)
    test(`${domain} ${action} cancels the completed owned server token before a stale API Apply`, async ({
      page,
      request,
    }) => {
      const { peer, base, headers, panel, preview } = await setup(
        page,
        request,
        domain,
      );
      try {
        const plan = await preview();
        const { result: cancelled } = await captureResponse(
          page,
          base + "/cancel",
          () => plan.operation_id,
        );
        if (action === "close")
          await panel
            .getByRole("button", {
              name:
                domain === "calendar"
                  ? "Close Calendar deployment"
                  : "Close native deployment workspace",
              exact: true,
            })
            .click();
        else if (action === "visibility")
          await page.evaluate(() =>
            document.dispatchEvent(new Event("visibilitychange")),
          );
        else if (action === "task") await chooseWorkspaceTask(page, "Overview");
        else
          await page
            .getByLabel(
              domain === "calendar"
                ? "Calendar entry 1 year"
                : domain === "string"
                  ? "Transition 1 CharacterString JSON literal"
                  : "Transition 1 exact value text",
              { exact: true },
            )
            .fill(
              domain === "calendar"
                ? "20"
                : domain === "string"
                  ? '"unfinished'
                  : "2e-",
            );
        const result = await cancelled;
        expect(result.reviews_retired).toBe(1);
        expect(result.cancel_requested).toBe(false);
        const before = await peer.stats();
        const old = await request.post(base + "/apply", {
          headers,
          data: {
            operation_id: "stale_review_manual_" + crypto.randomUUID(),
            token: plan.token,
            review_sha256: plan.review_sha256,
          },
        });
        expect(old.status()).toBe(422);
        const after = await peer.stats();
        expect(after.writes).toBe(0);
        expect(after.reads).toBe(before.reads);
      } finally {
        await peer.close();
      }
    });
for (const domain of ["calendar", "numeric", "string"] as const)
  test(`${domain} consumes its ready review without cancellation and retains one verified receipt`, async ({
    page,
    request,
  }) => {
    const { peer, base, headers, panel, preview, applyName } = await setup(
      page,
      request,
      domain,
    );
    try {
      const plan = await preview(),
        cancelled: string[] = [];
      page.on("request", (r) => {
        if (r.url().endsWith(base + "/cancel"))
          cancelled.push(r.postDataJSON()?.operation_id);
      });
      const { result: applied } = await captureResponse(page, base + "/apply");
      await panel.getByRole("button", { name: applyName, exact: true }).click();
      const receipt = await applied;
      expect(receipt.protocol_accepted).toBe(true);
      expect(receipt.readback.status).toBe("match");
      await expect(
        panel.getByLabel(
          domain === "calendar"
            ? "Calendar transfer receipt"
            : "Native write receipt",
          { exact: true },
        ),
      ).toBeVisible();
      expect(cancelled).not.toContain(plan.operation_id);
      expect((await peer.stats()).writes).toBe(1);
      const original = await (
        await request.get(base + "/receipts/" + receipt.id)
      ).body();
      await request.post(base + "/cancel", {
        headers,
        data: { operation_id: plan.operation_id },
      });
      expect(
        await (await request.get(base + "/receipts/" + receipt.id)).body(),
      ).toEqual(original);
    } finally {
      await peer.close();
    }
  });

for (const domain of ["calendar", "numeric", "string", "exception"] as const)
  test(`${domain} malformed preview retires its real server review without issuing Apply`, async ({
    page,
    request,
  }) => {
    const { peer, base, headers, panel, previewName } = await setup(
      page,
      request,
      domain,
    );
    try {
      let original: any;
      await page.route(
        "**" + base + "/preview",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 });
          original = await response.json();
          expect(original.can_apply, JSON.stringify(original.reasons)).toBe(
            true,
          );
          await route.fulfill({
            response,
            json: { ...original, operation_id: "substituted_operation" },
          });
        },
        { times: 1 },
      );
      const { result: cancel } = await captureResponse(
        page,
        base + "/cancel",
        () => original?.operation_id,
      );
      await panel
        .getByRole("button", { name: previewName, exact: true })
        .click();
      const result = await cancel;
      expect(result.reviews_retired).toBe(1);
      await expect(panel.getByRole("alert")).toBeVisible();
      const before = await peer.stats();
      expect(
        (
          await request.post(base + "/apply", {
            headers,
            data: {
              operation_id: "malformed_stale_apply",
              token: original.token,
              review_sha256: original.review_sha256,
            },
          })
        ).status(),
      ).toBe(422);
      const after = await peer.stats();
      expect(after.reads).toBe(before.reads);
      expect(after.writes).toBe(0);
    } finally {
      await peer.close();
    }
  });
