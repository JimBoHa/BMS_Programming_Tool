import { expect, test, type Page } from "@playwright/test";

type Target = {
  address: string;
  device: string;
  router: string;
  dnet: number;
};
const first: Target = {
  address: "3001:7",
  device: "device,5101",
  router: "198.51.100.21:47816",
  dnet: 3001,
};
const second: Target = { ...first, router: "198.51.100.22:47817" };
const third: Target = { ...second, address: "3002:7", dnet: 3002 };
const renamedIdentity: Target = { ...first, device: "device,6101" };
const targetKey = (value: Target) =>
  JSON.stringify([value.address, value.device, value.router, value.dnet]);
const label = (target: Target) =>
  targetKey(target) === targetKey(first)
    ? "Authored trend controller A"
    : targetKey(target) === targetKey(second)
      ? "Authored trend controller B"
      : targetKey(target) === targetKey(third)
        ? "Authored trend controller C"
        : "Authored replacement Device identity";
const object = (target: Target) =>
  targetKey(target) === targetKey(first)
    ? "analog-input,47"
    : "binary-value,73";

function deferred() {
  let release!: () => void;
  return {
    promise: new Promise<void>((resolve) => (release = resolve)),
    release: () => release(),
  };
}

// Authored HTTP responses exercise workspace/context behavior without field
// interfaces. Protocol identity and collector behavior have separate tests.
async function fixture(page: Page) {
  const starts: any[] = [],
    stops: string[] = [],
    inventories: any[] = [];
  const jobs: any[] = [];
  const sample = {
    sequence: 1,
    source_kind: "field",
    source: "field/saved-earlier",
    signal: "original_saved_signal",
    value: 18.75,
    quality: "good",
    unit: "degC",
    clock: "2026-02-03T04:05:06Z",
    recorded_at: "2026-02-03T04:05:07Z",
    provenance: { controller_target: third },
  };
  let connected = false;
  let config: any = {
    transport: "ip",
    local_address: "127.0.0.1:47931",
    instance: 4190001,
    router: null,
    dnet: null,
  };
  let held: ReturnType<typeof deferred> | null = null;
  let heldSamples: {
    source: string;
    gate: ReturnType<typeof deferred>;
    arrived: ReturnType<typeof deferred>;
  } | null = null;
  let wrongStartSource = false;
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname;
    const body = request.method() === "POST" ? request.postDataJSON() : null;
    const reply = (json: unknown) => route.fulfill({ json });
    if (path === "/api/bacnet/status")
      return reply({ connected, config, commands: [] });
    if (path === "/api/bacnet/connect") {
      config = {
        ...config,
        ...body,
        router: body.router || null,
        dnet: body.dnet ?? null,
      };
      connected = true;
      return reply({ connected, config, commands: [] });
    }
    if (path === "/api/bacnet/disconnect") {
      connected = false;
      return reply({ connected, config, commands: [] });
    }
    if (path === "/api/bacnet/device-details")
      return reply({
        address: body.address,
        router: body.router,
        dnet: body.dnet,
        identity_verified: true,
        properties: {
          "object-identifier": body.device,
          "object-name": label(body),
          "model-name": "Authored undisclosed model",
          "firmware-revision": "1.0",
        },
        finished_at: "2026-02-03T04:05:06Z",
      });
    if (path === "/api/bacnet/controller/inventory") {
      inventories.push(body);
      return reply({
        identity_verified: true,
        target: body,
        connector_config: structuredClone(config),
        offset: 0,
        next_offset: null,
        total: 2,
        objects: [
          { object: body.device, object_type: 8, has_present_value: false },
          {
            object: object(body),
            object_type: object(body).startsWith("binary") ? 5 : 0,
            has_present_value: true,
          },
        ],
        errors: [],
      });
    }
    if (path === "/api/bacnet/controller/properties")
      return reply({
        identity_verified: true,
        target: body,
        connector_config: structuredClone(config),
        errors: [],
        objects: body.object_ids.map((id: string) => ({
          object: id,
          identity_verified: true,
          properties: {
            "object-name": { status: "ok", value: `${label(body)} input` },
          },
        })),
      });
    if (path === "/api/field-trends/status")
      return reply({
        jobs,
        running_jobs: jobs.filter((job) => job.running).length,
      });
    if (path === "/api/field-trends/sources")
      return reply([
        {
          source: sample.source,
          samples: 1,
          ended: true,
          provenance: sample.provenance,
        },
        ...jobs.map((job) => ({
          source: job.source,
          samples: 0,
          ended: !job.running,
          provenance: {
            controller_target: job.controller_target,
            connector_config: job.connector_config,
          },
        })),
      ]);
    if (path === "/api/field-trends/samples") {
      const selectedSource = url.searchParams.get("source") || "";
      const gate = heldSamples?.source === selectedSource ? heldSamples : null;
      if (gate) {
        heldSamples = null;
        gate.arrived.release();
        await gate.gate.promise;
      }
      return reply(
        !selectedSource || selectedSource === sample.source ? [sample] : [],
      );
    }
    if (path === "/api/field-trends/events") return reply([]);
    if (path === "/api/field-trends/start") {
      starts.push(body);
      const id = `authored-job-${starts.length}`;
      const job = {
        ...body,
        connector_config: structuredClone(config),
        id,
        source: `field/${id}`,
        state: "running",
        running: true,
        polls: 0,
        samples: 0,
        failures: 0,
      };
      jobs.push(job);
      const gate = held;
      held = null;
      if (gate) await gate.promise;
      return reply(
        wrongStartSource ? { ...job, controller_target: second } : job,
      );
    }
    if (path === "/api/field-trends/stop") {
      stops.push(body.id);
      const job = jobs.find((value) => value.id === body.id);
      if (job) Object.assign(job, { state: "stopped", running: false });
      return reply(job);
    }
    if (path.startsWith("/api/bacnet/") && request.method() !== "GET")
      return route.fulfill({
        status: 500,
        json: { detail: `Unexpected field action ${path}` },
      });
    return route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Connect to a controller/ }).click();
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Known controller address", exact: true }),
  ).toBeEnabled();
  return {
    starts,
    stops,
    inventories,
    jobs,
    currentConfig: () => structuredClone(config),
    wrongStartSource: () => {
      wrongStartSource = true;
    },
    holdStart: () => {
      held = deferred();
      return held;
    },
    holdSamples: (source: string) => {
      const gate = deferred(),
        arrived = deferred();
      heldSamples = { source, gate, arrived };
      return { arrived: arrived.promise, release: gate.release };
    },
    changeInterface: (next: Record<string, unknown>, open = true) => {
      config = { ...config, ...next };
      connected = open;
    },
  };
}

async function openController(page: Page, target: Target, change = false) {
  if (change)
    await page
      .getByLabel("Working context")
      .getByRole("button", {
        name: "Change controller",
        exact: true,
      })
      .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  await page
    .getByLabel("Known controller address", { exact: true })
    .fill(target.address);
  await page
    .getByLabel("Known Device object", { exact: true })
    .fill(target.device);
  await page.getByLabel("Known router", { exact: true }).fill(target.router);
  await page
    .getByLabel("Known network", { exact: true })
    .fill(String(target.dnet));
  await page
    .getByRole("region", { name: "Known controller connection" })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview" }),
  ).toContainText(label(target));
}
async function openTrends(page: Page) {
  await page
    .getByRole("navigation", { name: "Workspace tasks" })
    .getByRole("button", { name: "Trends & Alarms", exact: true })
    .click();
  await page
    .getByRole("navigation", { name: "Current task tools" })
    .getByRole("button", { name: "Field recording", exact: true })
    .click();
  await expect(page.getByLabel("Field sampling target")).toBeVisible();
}
const start = (page: Page) =>
  page.getByRole("button", { name: "Start field sampling", exact: true });
const picker = (page: Page) =>
  page.getByLabel("Field discovered object object", { exact: true });

test("field recording uses one discovered-object picker and submits the full selected route and captured connector", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  await expect(page.getByLabel("Field address 1", { exact: true })).toHaveValue(
    first.address,
  );
  await expect(
    page.getByLabel("Field address 1", { exact: true }),
  ).toHaveAttribute("readonly", "");
  await expect(
    page.getByLabel("Field object identifier 1", { exact: true }),
  ).toHaveValue("");
  await expect(start(page)).toBeDisabled();
  await expect(picker(page)).toContainText(`${label(first)} input`);
  await picker(page).selectOption(object(first));
  await page
    .getByRole("button", { name: "Add field point", exact: true })
    .click();
  await expect(
    page.getByRole("group", { name: "Field discovered object", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByLabel("Field object identifier 2", { exact: true }),
  ).toHaveValue("");
  await picker(page).selectOption(object(first));
  await page
    .getByLabel("Trend job name", { exact: true })
    .fill("Selected route capture");
  const capturedConfig = state.currentConfig();
  await start(page).click();
  await expect.poll(() => state.starts.length).toBe(1);
  expect(state.starts[0].controller_target).toEqual(first);
  expect(state.starts[0].expected_connector_config).toEqual(capturedConfig);
  expect(state.starts[0].points.map((point: any) => point.address)).toEqual([
    first.address,
    first.address,
  ]);
  expect(state.starts[0].points.map((point: any) => point.object_id)).toEqual([
    object(first),
    object(first),
  ]);
  expect(
    state.inventories.every(
      (item) =>
        item.limit === 16 &&
        item.device === first.device &&
        item.router === first.router,
    ),
  ).toBe(true);
  const jobs = page.getByRole("region", { name: "Field sampling jobs" });
  await expect(jobs).toContainText(first.router);
  await expect(jobs).toContainText(first.device);
  await expect(
    page.getByLabel("Field trend source", { exact: true }),
  ).toHaveValue("field/authored-job-1");
});

test("same station number on another route or Device identity gets a separate draft and background jobs remain on their original target", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  await picker(page).selectOption(object(first));
  await page
    .getByLabel("Trend job name", { exact: true })
    .fill("Original A draft");
  await start(page).click();
  await expect.poll(() => state.starts.length).toBe(1);
  for (const target of [second, third, renamedIdentity]) {
    await openController(page, target, true);
    await openTrends(page);
    await expect(page.getByLabel("Field sampling target")).toContainText(
      target.device,
    );
    await expect(
      page.getByLabel("Field address 1", { exact: true }),
    ).toHaveValue(target.address);
    await expect(
      page.getByLabel("Trend job name", { exact: true }),
    ).toHaveValue("");
    await expect(
      page.getByLabel("Field object identifier 1", { exact: true }),
    ).toHaveValue("");
    await expect(start(page)).toBeDisabled();
    await expect(picker(page)).toContainText(`${label(target)} input`);
    await expect(picker(page)).not.toContainText(`${label(first)} input`);
    await expect(
      page.getByRole("region", { name: "Field sampling jobs" }),
    ).toContainText(first.router);
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue("");
  }
  expect(state.stops).toEqual([]);
  expect(state.jobs[0].controller_target).toEqual(first);
  await openController(page, first, true);
  await openTrends(page);
  await expect(page.getByLabel("Trend job name", { exact: true })).toHaveValue(
    "Original A draft",
  );
  await expect(
    page.getByLabel("Field object identifier 1", { exact: true }),
  ).toHaveValue(object(first));
  await page
    .getByRole("button", { name: "Stop sampling", exact: true })
    .click();
  await expect.poll(() => state.stops).toEqual(["authored-job-1"]);
  await expect(
    page.getByRole("region", { name: "Field sampling jobs" }),
  ).toContainText("stopped");
});

test("a held start response from the old controller never selects its source for the new controller", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  await picker(page).selectOption(object(first));
  const gate = state.holdStart();
  const response = page.waitForResponse((value) =>
    value.url().endsWith("/api/field-trends/start"),
  );
  try {
    await start(page).click();
    await expect.poll(() => state.starts.length).toBe(1);
    await openController(page, second, true);
    await openTrends(page);
    await expect(picker(page)).toContainText(`${label(second)} input`);
    gate.release();
    await response;
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue("");
    await expect(
      page.getByLabel("Field object identifier 1", { exact: true }),
    ).toHaveValue("");
    await expect(
      page.getByRole("region", { name: "Field sampling jobs" }),
    ).toContainText(first.router);
    expect(state.stops).toEqual([]);
    await picker(page).selectOption(object(second));
    await start(page).click();
    await expect.poll(() => state.starts.length).toBe(2);
    expect(state.starts[1].controller_target).toEqual(second);
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue("field/authored-job-2");
  } finally {
    gate.release();
  }
});

test("interface drift disables a selected-controller start while saved samples and explicit job stop remain available offline", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  await picker(page).selectOption(object(first));
  await start(page).click();
  await expect.poll(() => state.starts.length).toBe(1);
  state.changeInterface({ local_address: "127.0.0.1:47932" }, false);
  await page
    .getByRole("button", { name: "Refresh field trends", exact: true })
    .click();
  await expect(start(page)).toBeDisabled();
  await expect(
    page.getByText("Selected controller sampling unavailable", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Field trend source", { exact: true })
    .selectOption("field/saved-earlier");
  await expect(
    page.getByRole("region", { name: "Saved field trend samples" }),
  ).toContainText("original_saved_signal");
  await expect(
    page.getByRole("region", { name: "Saved field trend samples" }),
  ).toContainText(third.router);
  await expect(
    page.getByRole("button", { name: "Export field page CSV", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Stop sampling", exact: true })
    .click();
  await expect.poll(() => state.stops).toEqual(["authored-job-1"]);
  expect(state.starts).toHaveLength(1);
});

test("a start response naming another target is never adopted as the current recording source", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  await picker(page).selectOption(object(first));
  state.wrongStartSource();
  await start(page).click();
  await expect(page.getByRole("alert")).toContainText(
    "does not match the selected controller and interface",
  );
  await expect(
    page.getByLabel("Field trend source", { exact: true }),
  ).toHaveValue("");
  expect(state.starts[0].controller_target).toEqual(first);
  expect(state.stops).toEqual([]);
  await page
    .getByRole("button", { name: "Refresh field trends", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Field sampling jobs" }),
  ).toContainText(first.router);
});

test("a held refresh for an earlier source cannot overwrite the operator's later saved-source selection", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  await picker(page).selectOption(object(first));
  await start(page).click();
  await expect(
    page.getByLabel("Field trend source", { exact: true }),
  ).toHaveValue("field/authored-job-1");
  const refresh = page.getByRole("button", {
    name: "Refresh field trends",
    exact: true,
  });
  await expect(refresh).toBeEnabled();
  const gate = state.holdSamples("field/authored-job-1");
  try {
    await refresh.click();
    await gate.arrived;
    await expect(refresh).toBeDisabled();
    await page
      .getByLabel("Field trend source", { exact: true })
      .selectOption("field/saved-earlier");
    const samples = page.getByRole("region", {
      name: "Saved field trend samples",
    });
    await expect(samples).toContainText("original_saved_signal");
    gate.release();
    await expect(refresh).toBeEnabled();
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue("field/saved-earlier");
    await expect(samples).toContainText("original_saved_signal");
    await expect(samples).toContainText(third.router);
    expect(state.starts).toHaveLength(1);
    expect(state.stops).toEqual([]);
  } finally {
    gate.release();
  }
});

test("changing to a newly admitted source hides already displayed samples before its first page arrives", async ({
  page,
}) => {
  const state = await fixture(page);
  await openController(page, first);
  await openTrends(page);
  const samples = page.getByRole("region", {
    name: "Saved field trend samples",
  });
  const oldSignal = samples.getByRole("cell", {
    name: /original_saved_signal/,
  });
  await expect(oldSignal).toBeVisible();
  await picker(page).selectOption(object(first));
  const gate = state.holdSamples("field/authored-job-1");
  try {
    await start(page).click();
    await gate.arrived;
    await expect(
      page.getByLabel("Field trend source", { exact: true }),
    ).toHaveValue("field/authored-job-1");
    await expect(oldSignal).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Export field page CSV", exact: true }),
    ).toBeDisabled();
    gate.release();
    await expect(oldSignal).toHaveCount(0);
    expect(state.starts).toHaveLength(1);
  } finally {
    gate.release();
  }
});
