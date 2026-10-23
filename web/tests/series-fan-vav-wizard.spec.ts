import {
  test,
  expect,
  simulationServerResponseJSON,
  simulationServerResponseText,
  type Page,
  type Locator,
} from "./simulationFixture";
import {
  sourceFixtureData,
  projectedSourceFixture,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/series-fan-vav-wizard",
  title = "Portable real series fan VAV",
  previewName = "Series-fan VAV preview";
const environment = () => ({
  ...process.env,
  PYTHONPATH: path.join(root, "backend"),
});
const sha = (body: Buffer) => createHash("sha256").update(body).digest("hex");
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Series-fan VAV wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Series-fan VAV wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Series VAV project name", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("Series VAV project name", { exact: true })
    .fill(title);
  return dialog;
}
async function configure(dialog: Locator, short = true) {
  for (const label of [
    "Initial occupied",
    "Initial unit enabled",
    "Initial fan proven",
  ])
    await dialog.getByLabel(label, { exact: true }).check();
  if (short) {
    await dialog
      .getByLabel("Damper close estimate (seconds)", { exact: true })
      .fill("2");
    await dialog
      .getByLabel("Stable proof interval (seconds)", { exact: true })
      .fill("2");
    await dialog
      .getByLabel("Startup deadline (seconds)", { exact: true })
      .fill("3");
  }
}
async function units(dialog: Locator, temperature: string, flow: string) {
  if (
    (await dialog
      .getByLabel("Series VAV temperature units", { exact: true })
      .inputValue()) !== temperature
  ) {
    await dialog
      .getByLabel("Series VAV temperature units", { exact: true })
      .selectOption(temperature);
    await expect(dialog.getByRole("status")).toHaveCount(0);
  }
  if (
    (await dialog
      .getByLabel("Series VAV primary flow units", { exact: true })
      .inputValue()) !== flow
  ) {
    await dialog
      .getByLabel("Series VAV primary flow units", { exact: true })
      .selectOption(flow);
    await expect(dialog.getByRole("status")).toHaveCount(0);
  }
}
async function review(page: Page, dialog: Locator) {
  let original: Buffer | undefined;
  await page.route(
    "**" + base + "/preview",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      expect(response.status()).toBe(200);
      original = await response.body();
      await route.fulfill({ response, body: original });
    },
    { times: 1 },
  );
  await dialog
    .getByRole("button", {
      name: "Preview series-fan VAV project",
      exact: true,
    })
    .click();
  await expect(
    dialog.getByRole("region", { name: previewName, exact: true }),
  ).toBeVisible();
  expect(original).toBeDefined();
  await test.info().attach("original-series-preview-source-response", {
    body: original!,
    contentType: "application/json",
  });
  return projectedSourceFixture(JSON.parse(original!.toString()));
}
async function create(page: Page, dialog: Locator) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", {
      name: "Create editable series-fan VAV project",
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
}
async function scan(page: Page) {
  const pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await pending;
  expect(response.status()).toBe(200);
  return { response, data: simulationServerResponseJSON(response) };
}
async function step(page: Page) {
  return (await scan(page)).data.history.at(-1).outputs;
}
async function ready(page: Page) {
  const rows = [];
  for (let i = 0; i < 4; i++) rows.push(await step(page));
  expect(rows.map((r) => r.series_state)).toEqual([1, 1, 2, 3]);
  return rows.at(-1)!;
}
async function scenario(page: Page, duration: number, events: unknown[] = []) {
  if (
    !(await page.getByLabel("Timed simulation events", { exact: true }).count())
  )
    await page.getByRole("button", { name: "Scenarios", exact: true }).click();
  await page
    .getByLabel("Timed simulation events", { exact: true })
    .fill(JSON.stringify(events));
  await page
    .getByLabel("Scenario duration seconds", { exact: true })
    .fill(String(duration));
  const pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/scenario",
  );
  await page.getByRole("button", { name: "Run scenario", exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  await test.info().attach("original-series-scenario-response", {
    body: simulationServerResponseText(response),
    contentType: "application/json",
  });
  return simulationServerResponseJSON(response).history;
}
async function downloading(page: Page, dialog: Locator) {
  let original: Buffer | undefined,
    header = "";
  await page.route(
    "**" + base + "/export",
    async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      original = await response.body();
      header = response.headers()["x-file-sha256"];
      await route.fulfill({ response, body: original });
    },
    { times: 1 },
  );
  const waiting = page.waitForEvent("download");
  await dialog
    .getByRole("button", {
      name: "Export original series-fan VAV review JSON",
      exact: true,
    })
    .click();
  const download = await waiting,
    bytes = readFileSync((await download.path())!);
  expect(bytes).toEqual(original);
  expect(sha(bytes)).toBe(header);
  await test.info().attach("original-upstream-series-review", {
    body: original!,
    contentType: "application/json",
  });
  await test.info().attach("original-downloaded-series-review", {
    body: bytes,
    contentType: "application/json",
  });
  return { bytes, header };
}
async function held(page: Page, endpoint: string) {
  let seen!: () => void, release!: () => void, done!: () => void;
  const incoming = new Promise<void>((r) => (seen = r)),
    gate = new Promise<void>((r) => (release = r)),
    finished = new Promise<void>((r) => (done = r));
  await page.route("**" + base + "/" + endpoint, async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      body = await response.body();
    seen();
    await gate;
    await route.fulfill({ response, body });
    done();
  });
  return { incoming, release, finished };
}
const temperature = (f: number, unit: string) =>
  unit === "degC" ? ((f - 32) * 5) / 9 : f;
const flowValue = (cfm: number, unit: string) =>
  unit === "L/s" ? cfm * 0.4719474432 : cfm;

for (const unit of ["degF", "degC"])
  for (const flow of ["cfm", "L/s"])
    test(`authors real series topology in ${unit}/${flow}, simulates feedback and preserves original revision interchange`, async ({
      page,
    }) => {
      const dialog = await open(page);
      await configure(dialog);
      await dialog
        .getByLabel("Series VAV declared controller family", { exact: true })
        .selectOption("johnson-metasys");
      await dialog
        .getByLabel("Series VAV declared model", { exact: true })
        .fill("MS-VMA1630-0");
      for (const label of [
        "Heating integral gain",
        "Cooling integral gain",
        "Flow integral gain",
      ])
        await dialog.getByLabel(label, { exact: true }).fill("0");
      await units(dialog, unit, flow);
      const report = await review(page, dialog),
        original = await downloading(page, dialog);
      expect(report.can_create).toBe(true);
      expect(report.inputs).toHaveLength(9);
      expect(report.outputs).toHaveLength(24);
      expect(report.program.nodes).toHaveLength(167);
      expect(report.choices.fan).toBe("single-speed-series");
      expect(report.choices.heating).toBe("proportional-hot-water");
      expect(report.choices.flow_feedback).toBe("calibrated-primary");
      expect(report.native_compile).toBe(false);
      expect(report.controller_writes).toBe(false);
      await create(page, dialog);
      let outputs = await ready(page);
      expect(outputs.zone_cooling_demand).toBeCloseTo(8, 8);
      expect(outputs.primary_flow_target).toBeCloseTo(flowValue(156, flow), 8);
      expect(outputs.primary_damper).toBeCloseTo(31.2, 8);
      expect(outputs.reheat_valve).toBe(0);
      await page
        .getByLabel("Simulate zone_temperature", { exact: true })
        .fill(String(temperature(60, unit)));
      outputs = await step(page);
      expect(outputs.heating_active).toBe(true);
      expect(outputs.cooling_active).toBe(false);
      expect(outputs.reheat_valve).toBeCloseTo(32, 8);
      expect(outputs.primary_flow_target).toBeCloseTo(flowValue(100, flow), 8);
      await page
        .getByRole("button", { name: "Save revision", exact: true })
        .click();
      await expect(
        page.getByLabel("Last saved revision", { exact: true }),
      ).toContainText("r1");
      const exports: { filename: string; body_base64: string }[] = [];
      for (const format of ["json", "st", "plcopen", "graphml"]) {
        await page
          .getByLabel("Export format", { exact: true })
          .selectOption(format);
        const pending = page.waitForEvent("download");
        await page.getByRole("button", { name: "Export", exact: true }).click();
        const file = await pending,
          body = readFileSync((await file.path())!);
        exports.push({
          filename: file.suggestedFilename(),
          body_base64: body.toString("base64"),
        });
        await test.info().attach("original-series-interchange-" + format, {
          body,
          contentType: "application/octet-stream",
        });
      }
      await page.reload();
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(title);
      const saved = await page.request.get(
          "/api/projects/" + report.program.id,
        ),
        savedBytes = await saved.body();
      expect(saved.status()).toBe(200);
      await test.info().attach("original-saved-series-project", {
        body: savedBytes,
        contentType: "application/json",
      });
      // One process/import for every original raw body. Keep all format checks
      // and the final session probe inside the unchanged30s test budget.
      const checked = execFileSync(
        python,
        [
          "-c",
          "import base64,hashlib,json,sys;from bms_tool.models import Program;from bms_tool.formats import import_program;v=json.load(sys.stdin);raw=base64.b64decode(v['review']);assert hashlib.sha256(raw).hexdigest()==v['review_sha'];r=json.loads(raw);p=Program.model_validate(r['program']);assert p.digest()==v['digest'];assert not r['native_compile'] and not r['controller_writes'];out=[p.digest()];items=[(base64.b64decode(x['body_base64']),x['filename']) for x in v['exports']]+[(base64.b64decode(v['saved']),'restored.json')];\nfor raw,name in items:\n p=import_program(raw,name);assert p.revision==1;assert not p.metadata['native_deployment_verified'];assert p.metadata['series_fan_vav_wizard']['choices']['fan']=='single-speed-series';assert p.metadata['series_fan_vav_wizard']['choices']['heating']=='proportional-hot-water';p.revision=0;out.append(p.digest())\nprint(json.dumps(out))",
        ],
        {
          cwd: root,
          env: environment(),
          input: JSON.stringify({
            review: original.bytes.toString("base64"),
            review_sha: original.header,
            digest: report.program_sha256,
            exports,
            saved: savedBytes.toString("base64"),
          }),
          encoding: "utf8",
        },
      );
      expect(JSON.parse(checked)).toEqual(Array(6).fill(report.program_sha256));
      expect(
        (await (await page.request.get("/api/session")).json())
          .field_network_open,
      ).toBe(false);
    });

test("source90second close and15second proof defaults count actual elapsed scans without early proof", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, false);
  const report = await review(page, dialog);
  expect(report.choices.close_seconds).toBe(90);
  expect(report.choices.proof_seconds).toBe(15);
  await create(page, dialog);
  const rows = await scenario(page, 105);
  expect(rows).toHaveLength(105);
  expect(
    rows.slice(0, 90).every((r: any) => r.outputs.fan_enable === false),
  ).toBe(true);
  expect(rows[89].outputs.close_complete).toBe(true);
  expect(rows[90].outputs.fan_enable).toBe(true);
  expect(
    rows.slice(0, 104).every((r: any) => r.outputs.fan_ready === false),
  ).toBe(true);
  expect(rows[104].outputs.fan_ready).toBe(true);
});
test("proof chatter cannot extend startup and stable proof at exact deadline wins", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  let rows = await scenario(page, 5, [
    { time: 2, inputs: { fan_proven: false } },
    { time: 3, inputs: { fan_proven: true } },
  ]);
  expect(rows.map((r: any) => r.outputs.series_state)).toEqual([1, 1, 2, 2, 3]);
  expect(rows[4].outputs.startup_deadline_reached).toBe(true);
  expect(rows[4].outputs.fan_fault).toBe(false);
  rows = await scenario(page, 5, [
    { time: 3, inputs: { fan_proven: false } },
    { time: 4, inputs: { fan_proven: true } },
  ]);
  expect(rows[4].outputs.fan_fault).toBe(true);
  expect(rows[4].outputs.fan_enable).toBe(false);
  expect(rows[4].outputs.primary_damper).toBe(0);
});
test("lost running proof latches immediately and invalid setpoints cannot impersonate raw off reset", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  await ready(page);
  await page.getByLabel("Simulate fan_proven", { exact: true }).uncheck();
  let out = await step(page);
  expect(out.fan_fault).toBe(true);
  expect(out.fan_enable).toBe(false);
  expect(out.primary_damper).toBe(0);
  expect(out.reheat_valve).toBe(0);
  await page.getByLabel("Simulate fan_proven", { exact: true }).check();
  await page
    .getByLabel("Simulate heating_setpoint", { exact: true })
    .fill("90");
  await page.getByLabel("Simulate fan_reset", { exact: true }).check();
  expect((await step(page)).fan_fault).toBe(true);
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  expect((await step(page)).fan_fault).toBe(true);
  await page.getByLabel("Simulate fan_reset", { exact: true }).uncheck();
  expect((await step(page)).fan_fault).toBe(true);
  await page.getByLabel("Simulate fan_reset", { exact: true }).check();
  out = await step(page);
  expect(out.fan_fault).toBe(false);
  expect(out.reset_accepted).toBe(true);
  await page
    .getByLabel("Simulate heating_setpoint", { exact: true })
    .fill("68");
  await page.getByLabel("Simulate unit_enable", { exact: true }).check();
  expect((await ready(page)).fan_ready).toBe(true);
});
test("good invalid primaryflow and zone targets inhibit commands without a fault and restart full startup", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  await ready(page);
  for (const [field, invalid, valid] of [
    ["primary_airflow", "-1", "0"],
    ["zone_temperature", "-100", "74"],
    ["heating_setpoint", "90", "68"],
  ]) {
    await page.getByLabel("Simulate " + field, { exact: true }).fill(invalid);
    const out = await step(page);
    expect(out.raw_run_request).toBe(true);
    expect(out.fan_ready).toBe(false);
    expect(out.fan_fault).toBe(false);
    expect(out.fan_enable).toBe(false);
    expect(out.primary_damper).toBe(0);
    expect(out.reheat_valve).toBe(0);
    await page.getByLabel("Simulate " + field, { exact: true }).fill(valid);
    await ready(page);
  }
});
test("first bad-quality scan has no seeded commands and later faults retain prior positive outputs", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await dialog
    .getByLabel("Zone temperature default", { exact: true })
    .fill("60");
  await review(page, dialog);
  await create(page, dialog);
  await page
    .getByLabel("Quality primary_airflow", { exact: true })
    .selectOption("open-circuit");
  const first = await scan(page);
  expect(first.data.history).toEqual([]);
  expect(first.data.session).toBeNull();
  expect(first.data.last).toBeNull();
  expect(first.data.completed_steps).toBe(0);
  expect(first.data.snapshot.outputs).toEqual({});
  expect(first.data.snapshot.state).toEqual({});
  await test.info().attach("original-series-first-fault", {
    body: simulationServerResponseText(first.response),
    contentType: "application/json",
  });
  await page
    .getByLabel("Quality primary_airflow", { exact: true })
    .selectOption("good");
  const positive = await ready(page);
  expect(positive.reheat_valve).toBeGreaterThan(0);
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  await page
    .getByLabel("Quality zone_temperature", { exact: true })
    .selectOption("stale");
  const fault = await scan(page);
  expect(fault.data.history.at(-1).outputs).toEqual(positive);
  expect(fault.data.scan_error).toContain("stale");
  await test.info().attach("original-series-positive-output-rollback", {
    body: simulationServerResponseText(fault.response),
    contentType: "application/json",
  });
});
test("active PI holds at setpoint and zero primaryflow does not become invented total coil proof", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await dialog
    .getByLabel("Cooling proportional gain", { exact: true })
    .fill("0");
  await dialog.getByLabel("Cooling integral gain", { exact: true }).fill("1");
  await review(page, dialog);
  await create(page, dialog);
  expect((await ready(page)).zone_cooling_demand).toBe(2);
  await page
    .getByLabel("Simulate zone_temperature", { exact: true })
    .fill("72");
  let out = await step(page);
  expect(out.cooling_active).toBe(true);
  expect(out.zone_cooling_demand).toBe(2);
  await page
    .getByLabel("Simulate zone_temperature", { exact: true })
    .fill("60");
  await page.getByLabel("Simulate primary_airflow", { exact: true }).fill("0");
  out = await step(page);
  expect(out.heating_active).toBe(true);
  expect(out.cooling_active).toBe(false);
  expect(out.reheat_valve).toBeGreaterThan(0);
  expect(out.primary_flow_measured).toBe(0);
});
test("unit changes couple every absolute difference and inverse gain without changing seconds or flags", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await units(dialog, "degC", "L/s");
  let report = await review(page, dialog);
  expect(report.choices.zone_default).toBe(temperature(74, "degC"));
  expect(report.choices.heating_setpoint).toBe(20);
  expect(report.choices.entry_delta).toBe(5 / 9);
  expect(report.choices.cooling_kp).toBe(4 / (5 / 9));
  expect(report.choices.primary_flow_min).toBe(flowValue(100, "L/s"));
  expect(report.choices.flow_kp).toBe(0.2 / 0.4719474432);
  expect(report.choices.proof_seconds).toBe(2);
  expect(report.choices.fan_proven_default).toBe(true);
  await units(dialog, "degF", "cfm");
  report = await review(page, dialog);
  expect(report.choices.primary_flow_max).toBeCloseTo(800, 10);
  expect(report.choices.heating_setpoint).toBeCloseTo(68, 10);
});
test("adjacent legal differences that collapse during conversion refuse without widening or replacing original draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await units(dialog, "degC", "cfm");
  await dialog
    .getByLabel("Entry difference", { exact: true })
    .fill("1.5000000000000007");
  await dialog
    .getByLabel("Release difference", { exact: true })
    .fill("1.5000000000000004");
  const report = await review(page, dialog);
  const pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === base + "/units",
  );
  await dialog
    .getByLabel("Series VAV temperature units", { exact: true })
    .selectOption("degF");
  const response = await pending;
  expect(response.status()).toBe(422);
  await test.info().attach("original-series-unit-collapse-refusal", {
    body: await response.body(),
    contentType: "application/json",
  });
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("Series VAV temperature units", { exact: true }),
  ).toHaveValue("degC");
  expect((await review(page, dialog)).choices).toEqual(report.choices);
});
test("invalid engineering order and fractional or nonaligned times cannot replace current editor", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  const original = await page
    .getByLabel("Program name", { exact: true })
    .inputValue();
  for (const [label, invalid, restored] of [
    ["Entry difference", "0", "1"],
    ["Primary minimum airflow", "800", "100"],
    ["Damper close estimate (seconds)", "1.5", "2"],
    ["Series VAV scan interval (seconds)", "3", "1"],
  ]) {
    await dialog.getByLabel(label, { exact: true }).fill(invalid);
    const button = dialog.getByRole("button", {
      name: "Preview series-fan VAV project",
      exact: true,
    });
    if (await button.isEnabled()) {
      await button.click();
      await expect(dialog.getByRole("alert")).toBeVisible();
    }
    await expect(
      dialog.getByRole("button", {
        name: "Create editable series-fan VAV project",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      original,
    );
    await dialog.getByLabel(label, { exact: true }).fill(restored);
  }
});
test("scientific original Program values survive review export creation and save", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await dialog
    .getByLabel("Heating setpoint default", { exact: true })
    .fill("0.000001");
  await dialog.getByLabel("Entry difference", { exact: true }).fill("0.000001");
  const report = await review(page, dialog),
    original = await downloading(page, dialog);
  expect(original.bytes.toString()).toContain("1e-06");
  expect(report.choices.heating_setpoint).toBe(1e-6);
  await create(page, dialog);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByLabel("Last saved revision", { exact: true }),
  ).toContainText("r1");
  const saved = await page.request.get("/api/projects/" + report.program.id),
    raw = await saved.body();
  expect(saved.status()).toBe(200);
  await test.info().attach("original-scientific-saved-series-project", {
    body: raw,
    contentType: "application/json",
  });
  execFileSync(
    python,
    [
      "-c",
      "import json,sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;assert p.metadata['series_fan_vav_wizard']['choices']['entry_delta']==1e-6;assert next(n for n in p.nodes if n.id=='heating_setpoint').params['default']==1e-6;p.revision=0;assert p.digest()==sys.argv[1]",
      report.program_sha256,
    ],
    { cwd: root, env: environment(), input: raw },
  );
});

for (const kind of [
  "preview-source",
  "preview-discard",
  "export-source",
  "export-back",
  "units-close",
])
  test(`held ${kind} cannot authorize a stale series project or original download`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog);
    const endpoint = kind.split("-")[0];
    if (endpoint === "export") await review(page, dialog);
    const gate = await held(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (endpoint === "units")
        await dialog
          .getByLabel("Series VAV temperature units", { exact: true })
          .selectOption("degC");
      else
        await dialog
          .getByRole("button", {
            name:
              endpoint === "preview"
                ? "Preview series-fan VAV project"
                : "Export original series-fan VAV review JSON",
            exact: true,
          })
          .click();
      await gate.incoming;
      if (kind.endsWith("source"))
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed source while series request pending");
      else
        await dialog
          .getByRole("button", {
            name: kind.endsWith("discard")
              ? "Discard pending series-fan VAV response"
              : kind.endsWith("back")
                ? "Back to equipment wizard"
                : "Cancel series-fan VAV wizard",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      expect(downloads).toBe(0);
      await expect(
        page.getByRole("button", {
          name: "Create editable series-fan VAV project",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      gate.release();
    }
  });
for (const malformed of [
  "profile",
  "choices",
  "manifest",
  "flow-unit",
  "native-claim",
])
  test(`refuse ${malformed} preview as series project authority`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog);
    await page.route("**" + base + "/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "choices") value.choices.close_seconds = 3;
      else if (malformed === "manifest")
        value.inputs.find((r: any) => r.id === "fan_proven").value_type =
          "number";
      else if (malformed === "flow-unit")
        value.outputs.find((r: any) => r.id === "primary_flow_target").unit =
          "L/s";
      else value.program.metadata.native_deployment_verified = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", {
        name: "Preview series-fan VAV project",
        exact: true,
      })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable series-fan VAV project",
        exact: true,
      }),
    ).toHaveCount(0);
  });
test("unit reply cannot silently change timing or its independent source draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await page.route("**" + base + "/units", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.choices.close_seconds = 3;
    await route.fulfill({ response, json: value });
  });
  await dialog
    .getByLabel("Series VAV temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("Series VAV temperature units", { exact: true }),
  ).toHaveValue("degF");
  await expect(
    dialog.getByLabel("Damper close estimate (seconds)", { exact: true }),
  ).toHaveValue("2");
});
test("wrong original export byte digest prevents a series review download", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  let downloads = 0;
  page.on("download", () => downloads++);
  await page.route("**" + base + "/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({
      response,
      headers: { ...response.headers(), "x-file-sha256": "0".repeat(64) },
      body: await response.body(),
    });
  });
  await dialog
    .getByRole("button", {
      name: "Export original series-fan VAV review JSON",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(downloads).toBe(0);
});
test("unsupported same-ID catalog rules cannot initialize a series draft", async ({
  page,
}) => {
  await page.route("**" + base + "/catalog", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.profile_sha256 = "0".repeat(64);
    await route.fulfill({ response, json: value });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Series-fan VAV wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Series-fan VAV wizard",
    exact: true,
  });
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("Series VAV project name", { exact: true }),
  ).toHaveCount(0);
});

test("dismissed replacement confirmation preserves editor and later draft edits invalidate create authority", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  const original = await page
    .getByLabel("Program name", { exact: true })
    .inputValue();
  await review(page, dialog);
  let confirmation = "";
  page.once("dialog", async (event) => {
    confirmation = event.message();
    await event.dismiss();
  });
  await dialog
    .getByRole("button", {
      name: "Create editable series-fan VAV project",
      exact: true,
    })
    .click();
  expect(confirmation).toContain("Replace the editor contents");
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
  await dialog
    .getByLabel("Primary maximum airflow", { exact: true })
    .fill("900");
  await expect(
    dialog.getByRole("region", { name: previewName, exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", {
      name: "Create editable series-fan VAV project",
      exact: true,
    }),
  ).toHaveCount(0);
  expect((await review(page, dialog)).choices.primary_flow_max).toBe(900);
  await dialog
    .getByRole("button", {
      name: "Cancel series-fan VAV wizard",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});
