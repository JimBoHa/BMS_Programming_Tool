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
  base = "/api/unit-ventilator-cycle3-wizard",
  title = "Portable occupied UV Cycle III",
  previewName = "Unit ventilator Cycle III preview";
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
    .getByRole("button", {
      name: "Unit ventilator Cycle III wizard",
      exact: true,
    })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Unit ventilator Cycle III wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("UV Cycle III project name", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("UV Cycle III project name", { exact: true })
    .fill(title);
  return dialog;
}
async function configure(
  dialog: Locator,
  short = true,
  policy = "disable-cooling",
) {
  await dialog
    .getByLabel("UV condensate policy", { exact: true })
    .selectOption(policy);
  for (const label of [
    "Initial occupied",
    "Initial unit enabled",
    "Initial airflow proven",
  ])
    await dialog.getByLabel(label, { exact: true }).check();
  if (short) {
    await dialog
      .getByLabel("Stable proof interval (seconds)", { exact: true })
      .fill("2");
    await dialog
      .getByLabel("Startup deadline (seconds)", { exact: true })
      .fill("3");
  }
}
async function units(dialog: Locator, temperature: string) {
  if (
    (await dialog
      .getByLabel("UV Cycle III temperature units", { exact: true })
      .inputValue()) !== temperature
  ) {
    await dialog
      .getByLabel("UV Cycle III temperature units", { exact: true })
      .selectOption(temperature);
    await expect(dialog.getByRole("status")).toHaveCount(0);
  }
}
async function proportional(dialog: Locator) {
  for (const label of [
    "Heating integral gain",
    "Cooling integral gain",
    "Mixed-air integral gain",
    "Zone-limit integral gain",
  ])
    await dialog.getByLabel(label, { exact: true }).fill("0");
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
      name: "Preview unit ventilator Cycle III project",
      exact: true,
    })
    .click();
  await expect(
    dialog.getByRole("region", { name: previewName, exact: true }),
  ).toBeVisible();
  expect(original).toBeDefined();
  await test.info().attach("original-uv-cycle3-preview-source-response", {
    body: original!,
    contentType: "application/json",
  });
  return projectedSourceFixture(JSON.parse(original!.toString()));
}
async function create(page: Page, dialog: Locator) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", {
      name: "Create editable unit ventilator Cycle III project",
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
  const rows = [await step(page), await step(page)];
  expect(rows.map((r) => r.unit_state)).toEqual([1, 2]);
  return rows[1];
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
  await test.info().attach("original-uv-cycle3-scenario-response", {
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
      name: "Export original unit ventilator Cycle III review JSON",
      exact: true,
    })
    .click();
  const download = await waiting,
    bytes = readFileSync((await download.path())!);
  expect(bytes).toEqual(original);
  expect(sha(bytes)).toBe(header);
  await test.info().attach("original-upstream-uv-cycle3-review", {
    body: original!,
    contentType: "application/json",
  });
  await test.info().attach("original-downloaded-uv-cycle3-review", {
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
test("condensate policy starts blank and must be selected before preview or unit conversion", async ({
  page,
}) => {
  let requests = 0;
  await page.route("**" + base + "/{preview,units}", async (route) => {
    requests++;
    await route.continue();
  });
  const dialog = await open(page);
  await expect(
    dialog.getByLabel("UV condensate policy", { exact: true }),
  ).toHaveValue("");
  await expect(
    dialog.getByLabel("UV Cycle III temperature units", { exact: true }),
  ).toBeDisabled();
  await expect(
    dialog.getByRole("button", {
      name: "Preview unit ventilator Cycle III project",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(dialog).toContainText("position floor");
  await expect(dialog).toContainText("Latent correction");
  expect(requests).toBe(0);
});
for (const unit of ["degF", "degC"])
  for (const policy of ["disable-cooling", "shutdown-unit"])
    test(`authors occupied UV Cycle III ${unit}/${policy}, simulates and preserves original revision interchange`, async ({
      page,
    }) => {
      const dialog = await open(page);
      await configure(dialog, true, policy);
      await proportional(dialog);
      await dialog
        .getByLabel("UV Cycle III declared controller family", { exact: true })
        .selectOption("johnson-fx");
      await dialog
        .getByLabel("UV Cycle III declared model", { exact: true })
        .fill("Declared FX-PCG");
      await dialog
        .getByLabel("Zone temperature default", { exact: true })
        .fill("80");
      await dialog
        .getByLabel("Mixed-air temperature default", { exact: true })
        .fill("65");
      await units(dialog, unit);
      const report = await review(page, dialog),
        original = await downloading(page, dialog);
      expect(report.inputs).toHaveLength(13);
      expect(report.outputs).toHaveLength(29);
      expect(report.program.nodes).toHaveLength(
        policy === "shutdown-unit" ? 197 : 198,
      );
      expect(report.choices.cycle).toBe("authored-cycle-3");
      expect(report.choices.coils).toBe("separate-proportional-hydronic");
      expect(report.choices.mixing_action).toBe("cold-outdoor-only");
      expect(
        String(
          report.program.nodes.find((n: any) => n.id === "uv_negative_release")
            .params.value,
        ),
      ).toBe("-0.0");
      expect(report.choices.condensate_policy).toBe(policy);
      expect(report.native_compile).toBe(false);
      expect(report.controller_writes).toBe(false);
      await expect(
        dialog
          .getByRole("table", {
            name: "Unit ventilator Cycle III inputs",
            exact: true,
          })
          .locator("tbody tr"),
      ).toHaveCount(13);
      await expect(
        dialog
          .getByRole("table", {
            name: "Unit ventilator Cycle III outputs",
            exact: true,
          })
          .locator("tbody tr"),
      ).toHaveCount(29);
      await create(page, dialog);
      let out = await ready(page);
      expect(out.cooling_valve).toBeCloseTo(24, 8);
      expect(out.heating_valve).toBe(0);
      expect(out.outdoor_damper).toBeCloseTo(55, 8);
      await page
        .getByLabel("Simulate condensate_alarm", { exact: true })
        .check();
      out = await step(page);
      expect(out.cooling_valve).toBe(0);
      expect(out.condensate_inhibits_cooling).toBe(true);
      expect(out.raw_run_request).toBe(true);
      expect(out.fan_fault).toBe(false);
      if (policy === "shutdown-unit") {
        expect(out.condensate_shutdown).toBe(true);
        expect(out.fan_enable).toBe(false);
        expect(out.outdoor_damper).toBe(0);
      } else {
        expect(out.condensate_shutdown).toBe(false);
        expect(out.fan_ready).toBe(true);
        expect(out.outdoor_damper).toBeCloseTo(55, 8);
      }
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
        await test.info().attach("original-uv-cycle3-interchange-" + format, {
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
      await test.info().attach("original-saved-uv-cycle3-project", {
        body: savedBytes,
        contentType: "application/json",
      });
      const checked = execFileSync(
        python,
        [
          "-c",
          "import base64,hashlib,json,math,sys;from bms_tool.models import Program;from bms_tool.formats import import_program;v=json.load(sys.stdin);raw=base64.b64decode(v['review']);assert hashlib.sha256(raw).hexdigest()==v['review_sha'];r=json.loads(raw);p=Program.model_validate(r['program']);assert p.digest()==v['digest'];assert not r['native_compile'] and not r['controller_writes'];out=[p.digest()];items=[(base64.b64decode(x['body_base64']),x['filename']) for x in v['exports']]+[(base64.b64decode(v['saved']),'restored.json')];\nfor raw,name in items:\n p=import_program(raw,name);assert p.revision==1;assert not p.metadata['native_deployment_verified'];assert math.copysign(1,next(n for n in p.nodes if n.id=='uv_negative_release').params['value'])==-1;assert p.metadata['unit_ventilator_cycle3_wizard']['choices']['cycle']=='authored-cycle-3';assert p.metadata['unit_ventilator_cycle3_wizard']['choices']['condensate_policy']==v['policy'];p.revision=0;out.append(p.digest())\nprint(json.dumps(out))",
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
            policy,
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
test("default five-second proof starts fan on the first requested scan without a close delay", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, false);
  const report = await review(page, dialog);
  expect(report.choices.proof_seconds).toBe(5);
  expect(report.choices.startup_timeout_seconds).toBe(60);
  expect(report.choices).not.toHaveProperty("close_seconds");
  await create(page, dialog);
  const rows = await scenario(page, 5);
  expect(rows).toHaveLength(5);
  expect(rows.every((r: any) => r.outputs.fan_enable)).toBe(true);
  expect(rows.map((r: any) => r.outputs.fan_ready)).toEqual([
    false,
    false,
    false,
    false,
    true,
  ]);
});
test("proof chatter spans a bounded deadline and exact-deadline stable proof wins", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  let rows = await scenario(page, 3, [
    { time: 0, inputs: { airflow_proven: false } },
    { time: 1, inputs: { airflow_proven: true } },
  ]);
  expect(rows.map((r: any) => r.outputs.unit_state)).toEqual([1, 1, 2]);
  expect(rows[2].outputs.startup_deadline_reached).toBe(true);
  expect(rows[2].outputs.fan_fault).toBe(false);
  rows = await scenario(page, 3, [
    { time: 1, inputs: { airflow_proven: false } },
    { time: 2, inputs: { airflow_proven: true } },
  ]);
  expect(rows[2].outputs.fan_fault).toBe(true);
  expect(rows[2].outputs.fan_enable).toBe(false);
  expect(rows[2].outputs.outdoor_damper).toBe(0);
});
test("running proof loss latches and only raw-off fresh reset clears it", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  await ready(page);
  await page.getByLabel("Simulate airflow_proven", { exact: true }).uncheck();
  let out = await step(page);
  expect(out.fan_fault).toBe(true);
  expect(out.fan_enable).toBe(false);
  expect(out.outdoor_damper).toBe(0);
  expect(out.heating_valve).toBe(0);
  expect(out.cooling_valve).toBe(0);
  await page.getByLabel("Simulate airflow_proven", { exact: true }).check();
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
  expect(out.reset_accepted).toBe(true);
  expect(out.fan_fault).toBe(false);
  await page
    .getByLabel("Simulate heating_setpoint", { exact: true })
    .fill("70");
  await page.getByLabel("Simulate unit_enable", { exact: true }).check();
  expect((await ready(page)).fan_ready).toBe(true);
});
test("good invalid temperatures and targets inhibit without fault and restart proof", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await create(page, dialog);
  await ready(page);
  for (const [field, bad, valid, flag] of [
    ["zone_temperature", "-100", "72", "temperature_range_valid"],
    ["mixed_air_temperature", "300", "55", "temperature_range_valid"],
    ["mixed_air_setpoint", "300", "55", "setpoints_valid"],
    ["heating_setpoint", "90", "70", "setpoints_valid"],
  ]) {
    await page.getByLabel("Simulate " + field, { exact: true }).fill(bad);
    const out = await step(page);
    expect(out.raw_run_request).toBe(true);
    expect(out[flag]).toBe(false);
    expect(out.fan_fault).toBe(false);
    expect(out.fan_enable).toBe(false);
    expect(out.fan_ready).toBe(false);
    expect(out.outdoor_damper).toBe(0);
    await page.getByLabel("Simulate " + field, { exact: true }).fill(valid);
    await ready(page);
  }
});
test("first bad quality has no seeded snapshot and later faults retain positive commands despite off request", async ({
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
    .getByLabel("Quality mixed_air_temperature", { exact: true })
    .selectOption("open-circuit");
  const first = await scan(page);
  expect(first.data.history).toEqual([]);
  expect(first.data.session).toBeNull();
  expect(first.data.completed_steps).toBe(0);
  expect(first.data.last).toBeNull();
  expect(first.data.snapshot.outputs).toEqual({});
  expect(first.data.snapshot.state).toEqual({});
  await test.info().attach("original-uv-first-fault", {
    body: simulationServerResponseText(first.response),
    contentType: "application/json",
  });
  await page
    .getByLabel("Quality mixed_air_temperature", { exact: true })
    .selectOption("good");
  const positive = await ready(page);
  expect(positive.heating_valve).toBeGreaterThan(0);
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  await page
    .getByLabel("Quality condensate_alarm", { exact: true })
    .selectOption("stale");
  const fault = await scan(page);
  expect(fault.data.history.at(-1).outputs).toEqual(positive);
  expect(fault.data.scan_error).toContain("stale");
  await test.info().attach("original-uv-positive-rollback", {
    body: simulationServerResponseText(fault.response),
    contentType: "application/json",
  });
});
test("zone limiter uses previous selected heating saturation and cannot boost heat from cold MAT", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await proportional(dialog);
  await dialog
    .getByLabel("Zone temperature default", { exact: true })
    .fill("40");
  await dialog
    .getByLabel("Mixed-air temperature default", { exact: true })
    .fill("80");
  await review(page, dialog);
  await create(page, dialog);
  let out = await ready(page);
  expect(out.heating_valve).toBe(100);
  expect(out.outdoor_damper).toBe(100);
  expect(out.zone_limit_active).toBe(false);
  out = await step(page);
  expect(out.zone_limit_active).toBe(true);
  expect(out.zone_limit_restricting).toBe(true);
  expect(out.zone_limit_correction).toBe(100);
  expect(out.zone_limit_allowed).toBe(0);
  expect(out.outdoor_damper).toBe(10);
  expect(out.heating_valve).toBe(100);
  await page
    .getByLabel("Simulate zone_temperature", { exact: true })
    .fill("72");
  await page
    .getByLabel("Simulate mixed_air_temperature", { exact: true })
    .fill("40");
  out = await step(page);
  expect(out.heating_valve).toBe(0);
  expect(out.cooling_valve).toBe(0);
  expect(out.outdoor_damper).toBe(10);
  expect(out.zone_limit_active).toBe(false);
});
test("unavailable heat selects a damper allowance while cooling permission does not disable MAT control", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await proportional(dialog);
  await dialog
    .getByLabel("Zone temperature default", { exact: true })
    .fill("65");
  await dialog
    .getByLabel("Mixed-air temperature default", { exact: true })
    .fill("80");
  await review(page, dialog);
  await create(page, dialog);
  expect((await ready(page)).heating_valve).toBe(20);
  await page
    .getByLabel("Simulate heating_available", { exact: true })
    .uncheck();
  let out = await step(page);
  expect(out.heating_requested).toBe(true);
  expect(out.heating_active).toBe(false);
  expect(out.heating_valve).toBe(0);
  expect(out.zone_limit_active).toBe(true);
  expect(out.zone_limit_correction).toBe(25);
  expect(out.zone_limit_allowed).toBe(75);
  expect(out.outdoor_damper).toBe(75);
  await page
    .getByLabel("Simulate zone_temperature", { exact: true })
    .fill("80");
  await page
    .getByLabel("Simulate cooling_available", { exact: true })
    .uncheck();
  out = await step(page);
  expect(out.cooling_requested).toBe(true);
  expect(out.cooling_active).toBe(false);
  expect(out.cooling_valve).toBe(0);
  expect(out.fan_ready).toBe(true);
  expect(out.outdoor_damper).toBe(100);
});
test("minimum100 is defined and an active limiter cannot reduce below declared position floor", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await proportional(dialog);
  await dialog
    .getByLabel("Minimum outdoor-air position (percent)", { exact: true })
    .fill("100");
  await dialog
    .getByLabel("Zone temperature default", { exact: true })
    .fill("40");
  await review(page, dialog);
  await create(page, dialog);
  await ready(page);
  const out = await step(page);
  expect(out.zone_limit_active).toBe(true);
  expect(out.zone_limit_restricting).toBe(false);
  expect(out.outdoor_damper).toBe(100);
  expect(out.mixed_air_damper_demand).toBe(100);
});
test("active PI retains command at target and inactive loops retain latent state", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await dialog
    .getByLabel("Zone temperature default", { exact: true })
    .fill("76");
  await dialog
    .getByLabel("Mixed-air temperature default", { exact: true })
    .fill("60");
  await dialog.getByLabel("Cooling integral gain", { exact: true }).fill("0.5");
  await review(page, dialog);
  await create(page, dialog);
  let out = await ready(page);
  expect(out.cooling_valve).toBe(9);
  expect(out.outdoor_damper).toBeCloseTo(32.95, 8);
  await page
    .getByLabel("Simulate zone_temperature", { exact: true })
    .fill("74");
  out = await step(page);
  expect(out.cooling_requested).toBe(true);
  expect(out.cooling_valve).toBe(1);
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  out = await step(page);
  expect(out.cooling_requested).toBe(false);
  expect(out.cooling_valve).toBe(0);
  expect(out.outdoor_damper).toBe(0);
  await page.getByLabel("Simulate unit_enable", { exact: true }).check();
  await page
    .getByLabel("Simulate zone_temperature", { exact: true })
    .fill("76");
  expect((await ready(page)).cooling_valve).toBe(10);
});
test("coupled unit conversion preserves policy flags timing and minimum while converting five absolutes and eight gains", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await units(dialog, "degC");
  let report = await review(page, dialog);
  for (const [field, f] of [
    ["zone_default", 72],
    ["mixed_air_default", 55],
    ["heating_setpoint", 70],
    ["cooling_setpoint", 74],
    ["mixed_air_setpoint", 55],
  ] as const)
    expect(report.choices[field]).toBe(temperature(f, "degC"));
  expect(report.choices.entry_delta).toBe(5 / 9);
  for (const field of ["heating_kp", "cooling_kp"])
    expect(report.choices[field]).toBe(4 / (5 / 9));
  for (const field of ["mixed_air_kp", "zone_limit_kp"])
    expect(report.choices[field]).toBe(5 / (5 / 9));
  for (const field of [
    "heating_ki",
    "cooling_ki",
    "mixed_air_ki",
    "zone_limit_ki",
  ])
    expect(report.choices[field]).toBe(0.1 / (5 / 9));
  expect(report.choices.minimum_outdoor_position).toBe(10);
  expect(report.choices.proof_seconds).toBe(2);
  expect(report.choices.airflow_proven_default).toBe(true);
  expect(report.choices.condensate_policy).toBe("disable-cooling");
  await units(dialog, "degF");
  report = await review(page, dialog);
  expect(report.choices.heating_setpoint).toBeCloseTo(70, 10);
});
test("adjacent difference conversion refusal preserves original Celsius draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await units(dialog, "degC");
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
    .getByLabel("UV Cycle III temperature units", { exact: true })
    .selectOption("degF");
  const response = await pending;
  expect(response.status()).toBe(422);
  await test.info().attach("original-uv-unit-collapse-refusal", {
    body: await response.body(),
    contentType: "application/json",
  });
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("UV Cycle III temperature units", { exact: true }),
  ).toHaveValue("degC");
  expect((await review(page, dialog)).choices).toEqual(report.choices);
});
test("invalid engineering order position or nonaligned timing cannot replace editor", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  const original = await page
    .getByLabel("Program name", { exact: true })
    .inputValue();
  for (const [label, invalid, restored] of [
    ["Entry difference", "0", "1"],
    ["Minimum outdoor-air position (percent)", "101", "10"],
    ["Stable proof interval (seconds)", "1.5", "2"],
    ["UV Cycle III scan interval (seconds)", "3", "1"],
  ]) {
    await dialog.getByLabel(label, { exact: true }).fill(invalid);
    await dialog
      .getByRole("button", {
        name: "Preview unit ventilator Cycle III project",
        exact: true,
      })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable unit ventilator Cycle III project",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
      original,
    );
    await dialog.getByLabel(label, { exact: true }).fill(restored);
  }
});
test("scientific original Program values survive original review creation and save", async ({
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
  await test.info().attach("original-scientific-saved-uv-project", {
    body: raw,
    contentType: "application/json",
  });
  execFileSync(
    python,
    [
      "-c",
      "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;assert p.metadata['unit_ventilator_cycle3_wizard']['choices']['entry_delta']==1e-6;assert next(n for n in p.nodes if n.id=='heating_setpoint').params['default']==1e-6;p.revision=0;assert p.digest()==sys.argv[1]",
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
  test(`held ${kind} cannot authorize a stale unit ventilator project or original download`, async ({
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
          .getByLabel("UV Cycle III temperature units", { exact: true })
          .selectOption("degC");
      else
        await dialog
          .getByRole("button", {
            name:
              endpoint === "preview"
                ? "Preview unit ventilator Cycle III project"
                : "Export original unit ventilator Cycle III review JSON",
            exact: true,
          })
          .click();
      await gate.incoming;
      if (kind.endsWith("source"))
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed source while unit ventilator request pending");
      else
        await dialog
          .getByRole("button", {
            name: kind.endsWith("discard")
              ? "Discard pending unit ventilator Cycle III response"
              : kind.endsWith("back")
                ? "Back to equipment wizard"
                : "Cancel unit ventilator Cycle III wizard",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      expect(downloads).toBe(0);
      await expect(
        page.getByRole("button", {
          name: "Create editable unit ventilator Cycle III project",
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
  "output-unit",
  "native-claim",
])
  test(`refuse ${malformed} preview as unit ventilator project authority`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog);
    await page.route("**" + base + "/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "choices") value.choices.proof_seconds = 3;
      else if (malformed === "manifest")
        value.inputs.find((r: any) => r.id === "airflow_proven").value_type =
          "number";
      else if (malformed === "output-unit")
        value.outputs.find((r: any) => r.id === "outdoor_damper").unit = "degC";
      else value.program.metadata.native_deployment_verified = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", {
        name: "Preview unit ventilator Cycle III project",
        exact: true,
      })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable unit ventilator Cycle III project",
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
    value.choices.proof_seconds = 3;
    await route.fulfill({ response, json: value });
  });
  await dialog
    .getByLabel("UV Cycle III temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("UV Cycle III temperature units", { exact: true }),
  ).toHaveValue("degF");
  await expect(
    dialog.getByLabel("Stable proof interval (seconds)", { exact: true }),
  ).toHaveValue("2");
});
test("wrong original export byte digest prevents a unit ventilator review download", async ({
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
      name: "Export original unit ventilator Cycle III review JSON",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(downloads).toBe(0);
});
test("unsupported same-ID catalog rules cannot initialize a unit ventilator draft", async ({
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
    .getByRole("button", {
      name: "Unit ventilator Cycle III wizard",
      exact: true,
    })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Unit ventilator Cycle III wizard",
    exact: true,
  });
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("UV Cycle III project name", { exact: true }),
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
      name: "Create editable unit ventilator Cycle III project",
      exact: true,
    })
    .click();
  expect(confirmation).toContain("Replace the editor contents");
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
  await dialog
    .getByLabel("Minimum outdoor-air position (percent)", { exact: true })
    .fill("25");
  await expect(
    dialog.getByRole("region", { name: previewName, exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", {
      name: "Create editable unit ventilator Cycle III project",
      exact: true,
    }),
  ).toHaveCount(0);
  expect((await review(page, dialog)).choices.minimum_outdoor_position).toBe(
    25,
  );
  await dialog
    .getByRole("button", {
      name: "Cancel unit ventilator Cycle III wizard",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});

for (const policy of ["disable-cooling", "shutdown-unit"])
  test(`typed signed-zero gains survive ${policy} preview, coupled units, original export and save`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, true, policy);
    for (const label of ["Heating integral gain", "Zone-limit integral gain"]) {
      await dialog.getByLabel(label, { exact: true }).fill("-0");
      await expect(dialog.getByLabel(label, { exact: true })).toHaveValue("-0");
    }
    await dialog
      .getByLabel("Cooling integral gain", { exact: true })
      .fill("0.000001");
    const check = (r: any) => {
      expect(Object.is(r.choices.heating_ki, -0)).toBe(true);
      expect(Object.is(r.choices.zone_limit_ki, -0)).toBe(true);
      for (const id of ["uv_heating_loop", "uv_zone_limit_loop"])
        expect(
          String(r.program.nodes.find((n: any) => n.id === id).params.ki),
        ).toBe("-0.0");
      expect(
        String(
          r.program.metadata.unit_ventilator_cycle3_wizard.choices.heating_ki,
        ),
      ).toBe("-0.0");
    };
    let report = await review(page, dialog);
    check(report);
    let original = await downloading(page, dialog);
    expect(original.bytes.toString()).toContain('"ki":-0.0');
    let unitRequests = 0;
    await page.route("**" + base + "/units", async (route) => {
      const body = route.request().postData()!,
        parsed = JSON.parse(body);
      expect(Object.is(parsed.choices.heating_ki, -0)).toBe(true);
      expect(Object.is(parsed.choices.zone_limit_ki, -0)).toBe(true);
      await test
        .info()
        .attach("original-signed-zero-unit-request-" + unitRequests, {
          body,
          contentType: "application/json",
        });
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        raw = await response.body();
      await test
        .info()
        .attach("original-signed-zero-unit-response-" + unitRequests, {
          body: raw,
          contentType: "application/json",
        });
      unitRequests++;
      await route.fulfill({ response, body: raw });
    });
    for (const unit of ["degC", "degF"]) {
      await units(dialog, unit);
      await expect(
        dialog.getByLabel("Heating integral gain", { exact: true }),
      ).toHaveValue("-0");
      report = await review(page, dialog);
      check(report);
      original = await downloading(page, dialog);
      expect(original.bytes.toString()).toContain('"ki":-0.0');
    }
    expect(unitRequests).toBe(2);
    await create(page, dialog);
    await page
      .getByRole("button", { name: "Save revision", exact: true })
      .click();
    await expect(
      page.getByLabel("Last saved revision", { exact: true }),
    ).toContainText("r1");
    const response = await page.request.get(
        "/api/projects/" + report.program.id,
      ),
      raw = await response.body();
    expect(response.status()).toBe(200);
    await test.info().attach("original-signed-zero-saved-project", {
      body: raw,
      contentType: "application/json",
    });
    execFileSync(
      python,
      [
        "-c",
        "import math,sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;assert math.copysign(1,p.metadata['unit_ventilator_cycle3_wizard']['choices']['heating_ki'])==-1;assert all(math.copysign(1,next(n for n in p.nodes if n.id==k).params['ki'])==-1 for k in ['uv_heating_loop','uv_zone_limit_loop']);p.revision=0;assert p.digest()==sys.argv[1]",
        report.program_sha256,
      ],
      { cwd: root, env: environment(), input: raw },
    );
  });

test("zero-to-negative-zero edits retire preview authority and blank input refuses cleanly before recovery", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  const field = dialog.getByLabel("Heating integral gain", { exact: true });
  await field.fill("0");
  await review(page, dialog);
  await field.fill("-0");
  await expect(field).toHaveValue("-0");
  await expect(
    dialog.getByRole("region", { name: previewName, exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", {
      name: "Create editable unit ventilator Cycle III project",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(Object.is((await review(page, dialog)).choices.heating_ki, -0)).toBe(
    true,
  );
  await field.fill("");
  await expect(field).toHaveValue("");
  let sent = 0;
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === base + "/preview") sent++;
  });
  await dialog
    .getByRole("button", {
      name: "Preview unit ventilator Cycle III project",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  expect(sent).toBe(0);
  await field.fill("-0");
  expect(Object.is((await review(page, dialog)).choices.heating_ki, -0)).toBe(
    true,
  );
  expect(sent).toBe(1);
});

test("unit conversion refuses a changed zero sign while retaining original signed source draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await dialog.getByLabel("Heating integral gain", { exact: true }).fill("-0");
  await page.route("**" + base + "/units", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      raw = await response.body(),
      value = JSON.parse(raw.toString());
    expect(Object.is(value.source_choices.heating_ki, -0)).toBe(true);
    expect(Object.is(value.choices.heating_ki, -0)).toBe(true);
    await test
      .info()
      .attach("original-signed-zero-unit-before-forged-sign", {
        body: raw,
        contentType: "application/json",
      });
    value.choices.heating_ki = 0;
    const { sourceStringify } = await import("../src/programSource");
    await route.fulfill({ response, body: sourceStringify(value) });
  });
  await dialog
    .getByLabel("UV Cycle III temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByLabel("UV Cycle III temperature units", { exact: true }),
  ).toHaveValue("degF");
  await expect(
    dialog.getByLabel("Heating integral gain", { exact: true }),
  ).toHaveValue("-0");
  expect(Object.is((await review(page, dialog)).choices.heating_ki, -0)).toBe(
    true,
  );
});
