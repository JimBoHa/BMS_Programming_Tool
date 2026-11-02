import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { scheduleControllerPeer } from "./schedule-controller-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";

type Target = {
  address: string;
  device: string;
  router: string | null;
  dnet: number | null;
};
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
async function capture(request: APIRequestContext, target: Target) {
  const headers = await auth(request);
  const read = await request.post("/api/bacnet/schedules/read", {
    headers,
    data: {
      ...target,
      object_ids: ["schedule,1"],
      operation_id: "capture_" + crypto.randomUUID().replaceAll("-", ""),
    },
  });
  expect(read.ok(), await read.text()).toBe(true);
  const report = await read.json();
  expect(report.complete).toBe(true);
  const saved = await request.post("/api/bacnet/schedules/library/save", {
    headers,
    data: { id: report.id },
  });
  expect(saved.ok()).toBe(true);
  return saved.json();
}
async function select(page: Page, target: Target, initial = true) {
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
async function draft(page: Page, id: string, string = false) {
  const library = page.getByRole("region", {
    name: "Native Schedule capture library",
    exact: true,
  });
  await library
    .getByRole("button", {
      name: "Open capture " + id.slice(0, 12),
      exact: true,
    })
    .click();
  await library
    .getByLabel(
      string
        ? "Transition 1 CharacterString JSON literal"
        : "Transition 1 exact value text",
      { exact: true },
    )
    .fill(string ? JSON.stringify("Reviewed schedule") : "2.5");
  await library
    .getByRole("button", { name: "Review native weekly draft", exact: true })
    .click();
  await expect(
    library.getByLabel("Native weekly draft review", { exact: true }),
  ).toBeVisible();
  const panel = await deployment(page);
  await panel
    .getByLabel("Declared native write operator", { exact: true })
    .fill("Authored operator");
  await panel
    .getByLabel("Native write rationale", { exact: true })
    .fill("Selected-controller qualification");
  return { library, panel };
}
async function deployment(page: Page) {
  const panel = page.getByRole("region", {
    name: "Native weekly-day deployment",
    exact: true,
  });
  await panel
    .getByRole("button", {
      name: "Open native deployment and local history",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("table", { name: "Native write journal", exact: true }),
  ).toBeVisible();
  return panel;
}

for (const changed of ["address", "router", "device"])
  test(`capture from another ${changed} cannot prepare a field write under the selected controller`, async ({
    page,
    request,
  }) => {
    const a = await scheduleControllerPeer(changed === "router"),
      b = await scheduleControllerPeer(changed === "router");
    try {
      expect(
        (
          await request.post("/api/bacnet/connect", {
            headers: await auth(request),
            data: { local_address: a.local },
          })
        ).ok(),
      ).toBe(true);
      const source = await capture(request, a.target);
      const selected =
        changed === "device" ? { ...a.target, device: "device,43" } : b.target;
      await select(page, selected);
      const calls: string[] = [];
      page.on("request", (r) => {
        if (/\/schedules\/writes\/(preview|apply|reconcile)$/.test(r.url()))
          calls.push(r.url());
      });
      const { library, panel } = await draft(page, source.id);
      await expect(
        panel.getByRole("button", {
          name: "Preview fresh native weekly-day write",
          exact: true,
        }),
      ).toBeDisabled();
      await expect(
        library.getByRole("button", {
          name: "Export exact reviewed weekly draft",
          exact: true,
        }),
      ).toBeEnabled();
      expect(calls).toEqual([]);
      expect((await a.stats()).writes).toBe(0);
      expect((await b.stats()).writes).toBe(0);
    } finally {
      await a.close();
      await b.close();
    }
  });

for (const routed of [false, true])
  test(`matching ${routed ? "routed" : "direct"} controller permits one write; receipt readback requires its original selection`, async ({
    page,
    request,
  }, info) => {
    test.setTimeout(60000);
    if (routed) await page.setViewportSize({ width: 600, height: 1000 });
    const a = await scheduleControllerPeer(routed),
      b = await scheduleControllerPeer(routed);
    try {
      expect(
        (
          await request.post("/api/bacnet/connect", {
            headers: await auth(request),
            data: { local_address: a.local },
          })
        ).ok(),
      ).toBe(true);
      const source = await capture(request, a.target);
      await select(page, a.target);
      let { panel } = await draft(page, source.id);
      await panel
        .getByRole("button", {
          name: "Preview fresh native weekly-day write",
          exact: true,
        })
        .click();
      await expect(
        panel.getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        }),
      ).toBeEnabled();
      await panel
        .getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        })
        .click();
      const shown = panel.getByLabel("Native write receipt", { exact: true });
      await expect(shown).toContainText("One dispatch admitted");
      const id = (await shown.textContent())!.match(
        /Receipt ([a-f0-9]{32})/,
      )![1];
      const original = await (
        await request.get("/api/bacnet/schedules/writes/receipts/" + id)
      ).body();
      const receipt = JSON.parse(original.toString());
      expect(receipt.protocol_accepted).toBe(true);
      expect(receipt.readback.status).toBe("match");
      expect((await a.stats()).writes).toBe(1);
      await page.screenshot({
        path: info.outputPath("selected-schedule-controller.png"),
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await select(page, b.target, false);
      panel = await deployment(page);
      await panel
        .getByRole("button", {
          name: "Open native receipt " + receipt.id.slice(0, 12),
          exact: true,
        })
        .click();
      await expect(
        panel.getByLabel("Native write receipt", { exact: true }),
      ).toBeVisible();
      await expect(
        panel.getByRole("button", {
          name: "Read-only reconcile selected receipt",
          exact: true,
        }),
      ).toBeDisabled();
      const saved = page.waitForEvent("download");
      await panel
        .getByRole("button", {
          name: "Export exact native write receipt",
          exact: true,
        })
        .click();
      const chunks: Buffer[] = [];
      for await (const chunk of (await (await saved).createReadStream())!)
        chunks.push(Buffer.from(chunk));
      expect(Buffer.concat(chunks)).toEqual(original);
      const before = await a.stats();
      await select(page, a.target, false);
      panel = await deployment(page);
      await panel
        .getByRole("button", {
          name: "Open native receipt " + receipt.id.slice(0, 12),
          exact: true,
        })
        .click();
      await panel
        .getByRole("button", {
          name: "Read-only reconcile selected receipt",
          exact: true,
        })
        .click();
      await expect(
        panel.getByLabel("Native write reconciliation", { exact: true }),
      ).toContainText("Readback: match. Writes sent: 0.");
      expect((await a.stats()).writes).toBe(1);
      expect((await b.stats()).writes).toBe(0);
      expect((await a.stats()).reads).toBeGreaterThan(before.reads);
      expect(
        await (
          await request.get(
            "/api/bacnet/schedules/writes/receipts/" + receipt.id,
          )
        ).body(),
      ).toEqual(original);
    } finally {
      await a.close();
      await b.close();
    }
  });

for (const entry of ["application", "CAF"])
  test(`${entry} entry retains local review/export without a selected controller or field traffic`, async ({
    page,
    request,
  }) => {
    const a = await scheduleControllerPeer();
    try {
      expect(
        (
          await request.post("/api/bacnet/connect", {
            headers: await auth(request),
            data: { local_address: a.local },
          })
        ).ok(),
      ).toBe(true);
      const source = await capture(request, a.target);
      await request.post("/api/bacnet/disconnect", {
        headers: await auth(request),
        data: {},
      });
      const calls: string[] = [];
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          r.url().includes("/api/bacnet/") &&
          !r.url().includes("/schedules/library/")
        )
          calls.push(r.url());
      });
      await page.goto("/");
      if (entry === "application")
        await page
          .getByRole("button", { name: "New application", exact: true })
          .click();
      else {
        const { execFileSync } = await import("node:child_process");
        const { default: path } = await import("node:path");
        const buffer = execFileSync(
          path.join(path.resolve(".."), ".venv/bin/python"),
          [
            "-c",
            "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
          ],
          {
            cwd: path.resolve(".."),
            env: {
              ...process.env,
              PYTHONPATH: path.join(path.resolve(".."), "backend"),
            },
          },
        );
        await page
          .getByLabel("Open local CAF application", { exact: true })
          .setInputFiles({
            name: "authored-schedule.caf",
            mimeType: "application/octet-stream",
            buffer,
          });
      }
      await expect(
        page.getByRole("navigation", { name: "Workspace tasks", exact: true }),
      ).toBeVisible();
      await chooseWorkspaceTask(page, "Schedules");
      const { library, panel } = await draft(page, source.id);
      await expect(
        panel.getByRole("button", {
          name: "Preview fresh native weekly-day write",
          exact: true,
        }),
      ).toBeDisabled();
      const download = page.waitForEvent("download");
      await library
        .getByRole("button", {
          name: "Export exact reviewed weekly draft",
          exact: true,
        })
        .click();
      expect((await download).suggestedFilename()).toMatch(/\.json$/);
      expect(calls).toEqual([]);
    } finally {
      await a.close();
    }
  });

test("a held preview cannot revive after controller A to B to A", async ({
  page,
  request,
}) => {
  test.setTimeout(60000);
  const a = await scheduleControllerPeer(),
    b = await scheduleControllerPeer();
  let release = () => {};
  try {
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers: await auth(request),
          data: { local_address: a.local },
        })
      ).ok(),
    ).toBe(true);
    const source = await capture(request, a.target);
    await select(page, a.target);
    let { panel } = await draft(page, source.id);
    let arrived!: () => void, finished!: () => void;
    const held = new Promise<void>((resolve) => {
      arrived = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const delivered = new Promise<void>((resolve) => {
      finished = resolve;
    });
    await page.route(
      "**/schedules/writes/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        expect((await response.json()).can_apply).toBe(true);
        arrived();
        await gate;
        await route.fulfill({ response });
        finished();
      },
      { times: 1 },
    );
    await panel
      .getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      })
      .click();
    await held;
    await select(page, b.target, false);
    await select(page, a.target, false);
    ({ panel } = await draft(page, source.id));
    release();
    await delivered;
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      }),
    ).toBeEnabled();
    expect((await a.stats()).writes).toBe(0);
    expect((await b.stats()).writes).toBe(0);
  } finally {
    release();
    await a.close();
    await b.close();
  }
});

test("the qualified String Schedule domain retains selected-controller preview, Apply and readback", async ({
  page,
  request,
}) => {
  const a = await scheduleControllerPeer(false, true);
  try {
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers: await auth(request),
          data: { local_address: a.local },
        })
      ).ok(),
    ).toBe(true);
    const source = await capture(request, a.target);
    await select(page, a.target);
    const { panel } = await draft(page, source.id, true);
    await panel
      .getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      })
      .click();
    await panel
      .getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      })
      .click();
    const shown = panel.getByLabel("Native write receipt", { exact: true });
    await expect(shown).toContainText("One dispatch admitted");
    const id = (await shown.textContent())!.match(/Receipt ([a-f0-9]{32})/)![1];
    const receipt = await (
      await request.get("/api/bacnet/schedules/writes/receipts/" + id)
    ).json();
    expect(receipt.profile).toBe(
      "native-schedule-reviewed-utf8-weekly-day-write/1",
    );
    expect(receipt.readback.status).toBe("match");
    await panel
      .getByRole("button", {
        name: "Read-only reconcile selected receipt",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Native write reconciliation", { exact: true }),
    ).toContainText("Readback: match. Writes sent: 0.");
    expect((await a.stats()).writes).toBe(1);
  } finally {
    await a.close();
  }
});
