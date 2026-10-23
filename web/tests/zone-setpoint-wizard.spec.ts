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
  base = "/api/zone-setpoint-wizard",
  title = "Portable zone target browser";
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Zone setpoint wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Zone setpoint wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Zone target project name", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("Zone target project name", { exact: true })
    .fill(title);
  return dialog;
}
async function configure(dialog: Locator, population = "off", window = "off") {
  await dialog
    .getByLabel("Population target branch", { exact: true })
    .selectOption(population);
  await dialog
    .getByLabel("Window target branch", { exact: true })
    .selectOption(window);
  await dialog
    .getByLabel("Initial scheduled occupied", { exact: true })
    .check();
  if (population !== "off") {
    await dialog
      .getByLabel("Population entry dwell (seconds)", { exact: true })
      .fill("2");
    await dialog
      .getByLabel("Population release dwell (seconds)", { exact: true })
      .fill("2");
    await dialog.getByLabel("Initial populated", { exact: true }).uncheck();
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
    .getByRole("button", { name: "Preview zone target project", exact: true })
    .click();
  await expect(
    dialog.getByRole("region", { name: "Zone target preview", exact: true }),
  ).toBeVisible();
  expect(original).toBeDefined();
  await test.info().attach("original-preview-source-response", {
    body: original!,
    contentType: "application/json",
  });
  return projectedSourceFixture(JSON.parse(original!.toString()));
}
async function create(page: Page, dialog: Locator) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", {
      name: "Create editable zone target project",
      exact: true,
    })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
}
async function scan(page: Page) {
  const receipt = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await receipt;
  expect(response.status()).toBe(200);
  return simulationServerResponseJSON(response).history.at(-1);
}
async function step(page: Page) {
  return (await scan(page)).outputs;
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
      name: "Export original zone target review JSON",
      exact: true,
    })
    .click();
  const download = await waiting,
    file = (await download.path())!,
    bytes = readFileSync(file);
  expect(bytes).toEqual(original);
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(header);
  await test.info().attach("original-upstream-zone-review", {
    body: original!,
    contentType: "application/json",
  });
  await test.info().attach("original-downloaded-zone-review", {
    body: bytes,
    contentType: "application/json",
  });
  return { file, bytes, header };
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

const environment = () => ({
  ...process.env,
  PYTHONPATH: path.join(root, "backend"),
});
const absolute = (f: number, unit: string) =>
  unit === "degC" ? ((f - 32) * 5) / 9 : f;
for (const population of ["off", "timed-offset"])
  for (const window of ["off", "absolute-pair"])
    for (const unit of ["degF", "degC"])
      test(`authors ${population}/${window} in ${unit}, simulates selected targets and preserves original review bytes`, async ({
        page,
      }) => {
        const dialog = await open(page);
        await configure(dialog, population, window);
        await dialog
          .getByLabel("Zone target declared controller family", { exact: true })
          .selectOption("johnson-metasys");
        await dialog
          .getByLabel("Zone target declared model", { exact: true })
          .fill("MS-VMA1630-0");
        if (unit === "degC") {
          await dialog
            .getByLabel("Zone target temperature units", { exact: true })
            .selectOption(unit);
          await expect(dialog.getByRole("status")).toHaveCount(0);
        }
        const report = await review(page, dialog);
        expect(report.can_create).toBe(true);
        expect(report.native_compile).toBe(false);
        expect(report.controller_writes).toBe(false);
        expect(report.program.target.model).toBe("MS-VMA1630-0");
        expect(report.inputs).toHaveLength(
          1 + Number(population !== "off") + Number(window !== "off"),
        );
        expect(report.outputs).toHaveLength(8);
        expect(report.inputs.map((r: any) => r.id).sort()).toEqual(
          [
            "scheduled_occupied",
            ...(population !== "off" ? ["populated"] : []),
            ...(window !== "off" ? ["window_open"] : []),
          ].sort(),
        );
        expect(
          report.outputs.some((r: any) => /fan|enable|airflow/.test(r.id)),
        ).toBe(false);
        const exported = await downloading(page, dialog);
        execFileSync(
          python,
          [
            "-c",
            "import json,hashlib,sys;from bms_tool.models import Program;b=open(sys.argv[1],'rb').read();r=json.loads(b);assert hashlib.sha256(b).hexdigest()==sys.argv[2];assert Program.model_validate(r['program']).digest()==r['program_sha256'];assert r['program']['metadata']['application']=='zone-effective-setpoints';assert not r['native_compile'] and not r['controller_writes']",
            exported.file,
            exported.header,
          ],
          { cwd: root, env: environment() },
        );
        await create(page, dialog);
        let outputs = await step(page);
        expect(outputs.effective_heating_setpoint).toBeCloseTo(
          absolute(70, unit),
          10,
        );
        expect(outputs.effective_cooling_setpoint).toBeCloseTo(
          absolute(74, unit),
          10,
        );
        expect(outputs.setpoint_profile).toBe(1);
        outputs = await step(page);
        const applied = population !== "off";
        expect(outputs.population_offset_applied).toBe(applied);
        expect(outputs.population_setback_ready).toBe(applied);
        expect(outputs.occupied_base_selected).toBe(true);
        expect(outputs.setpoint_profile).toBe(applied ? 2 : 1);
        expect(outputs.effective_heating_setpoint).toBeCloseTo(
          absolute(applied ? 69 : 70, unit),
          10,
        );
        expect(outputs.effective_cooling_setpoint).toBeCloseTo(
          absolute(applied ? 75 : 74, unit),
          10,
        );
        expect(outputs.applied_population_offset).toBeCloseTo(
          applied ? (unit === "degC" ? 5 / 9 : 1) : 0,
          10,
        );
        if (window !== "off") {
          await page
            .getByLabel("Simulate window_open", { exact: true })
            .check();
          outputs = await step(page);
          expect(outputs.setpoint_profile).toBe(3);
          expect(outputs.population_setback_ready).toBe(applied);
          expect(outputs.population_offset_applied).toBe(false);
          expect(outputs.applied_population_offset).toBe(0);
          expect(outputs.occupied_base_selected).toBe(false);
          expect(outputs.effective_heating_setpoint).toBeCloseTo(
            absolute(40, unit),
            10,
          );
          expect(outputs.effective_cooling_setpoint).toBeCloseTo(
            absolute(120, unit),
            10,
          );
        }
        if (population !== "off" && window !== "off") {
          await page
            .getByRole("button", { name: "Save revision", exact: true })
            .click();
          await expect(
            page.getByLabel("Last saved revision", { exact: true }),
          ).toContainText("r1");
          for (const format of ["json", "st", "plcopen", "graphml"]) {
            await page
              .getByLabel("Export format", { exact: true })
              .selectOption(format);
            const waiting = page.waitForEvent("download");
            await page
              .getByRole("button", { name: "Export", exact: true })
              .click();
            const file = await waiting;
            const digest = execFileSync(
              python,
              [
                "-c",
                "import sys;from bms_tool.formats import import_program;p=import_program(open(sys.argv[1],'rb').read(),sys.argv[2]);assert p.revision==1;assert p.metadata['zone_setpoint_wizard']['choices']['population']=='timed-offset';assert not p.metadata['native_deployment_verified'];p.revision=0;print(p.digest())",
                (await file.path())!,
                file.suggestedFilename(),
              ],
              { cwd: root, env: environment(), encoding: "utf8" },
            ).trim();
            expect(digest).toBe(report.program_sha256);
          }
          await page.reload();
          await expect(
            page.getByLabel("Program name", { exact: true }),
          ).toHaveValue(title);
          const response = await page.request.get(
              "/api/projects/" + report.program.id,
            ),
            raw = await response.body();
          await test.info().attach("original-saved-zone-project", {
            body: raw,
            contentType: "application/json",
          });
          const digest = execFileSync(
            python,
            [
              "-c",
              "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;p.revision=0;print(p.digest())",
            ],
            { cwd: root, env: environment(), input: raw, encoding: "utf8" },
          ).trim();
          expect(digest).toBe(report.program_sha256);
        }
        expect(
          (await (await page.request.get("/api/session")).json())
            .field_network_open,
        ).toBe(false);
      });

test("window precedence keeps population timer latent, closing reveals it, and unoccupied clears it", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "timed-offset", "absolute-pair");
  await dialog.getByLabel("Initial window open", { exact: true }).check();
  await review(page, dialog);
  await create(page, dialog);
  let out = await step(page);
  expect(out.setpoint_profile).toBe(3);
  expect(out.population_setback_ready).toBe(false);
  out = await step(page);
  expect(out.population_setback_ready).toBe(true);
  expect(out.population_offset_applied).toBe(false);
  expect(out.applied_population_offset).toBe(0);
  await page.getByLabel("Simulate window_open", { exact: true }).uncheck();
  out = await step(page);
  expect(out.setpoint_profile).toBe(2);
  expect(out.effective_heating_setpoint).toBe(69);
  expect(out.effective_cooling_setpoint).toBe(75);
  await page.getByLabel("Simulate populated", { exact: true }).check();
  out = await step(page);
  expect(out.population_setback_ready).toBe(true);
  out = await step(page);
  expect(out.population_setback_ready).toBe(false);
  expect(out.setpoint_profile).toBe(1);
  await page.getByLabel("Simulate window_open", { exact: true }).check();
  await page
    .getByLabel("Simulate scheduled_occupied", { exact: true })
    .uncheck();
  out = await step(page);
  expect(out.population_setback_ready).toBe(false);
  expect(out.setpoint_profile).toBe(3);
  await page.getByLabel("Simulate window_open", { exact: true }).uncheck();
  out = await step(page);
  expect(out.setpoint_profile).toBe(0);
  expect(out.effective_heating_setpoint).toBe(61);
  expect(out.effective_cooling_setpoint).toBe(82);
});

test("bad required quality before startup has no preseeded safe pair and later faults retain targets behind a window", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "timed-offset", "absolute-pair");
  await dialog.getByLabel("Initial window open", { exact: true }).check();
  await review(page, dialog);
  await create(page, dialog);
  await page
    .getByLabel("Quality populated", { exact: true })
    .selectOption("open-circuit");
  const faultReceipt = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await faultReceipt,
    fault = simulationServerResponseJSON(response);
  expect(response.status()).toBe(200);
  expect(fault.history).toEqual([]);
  expect(fault.last).toBeNull();
  expect(fault.session).toBeNull();
  expect(fault.completed_steps).toBe(0);
  expect(fault.scan_error).toContain("open-circuit");
  expect(fault.snapshot.outputs).toEqual({});
  expect(fault.snapshot.state).toEqual({});
  expect(fault.snapshot.time).toBe(0);
  await test
    .info()
    .attach("original-startup-fault-response", {
      body: simulationServerResponseText(response),
      contentType: "application/json",
    });
  await page
    .getByLabel("Quality populated", { exact: true })
    .selectOption("good");
  let out = await step(page);
  expect(out.population_setback_ready).toBe(false);
  out = await step(page);
  expect(out.population_setback_ready).toBe(true);
  const previous = out;
  await page
    .getByLabel("Quality scheduled_occupied", { exact: true })
    .selectOption("stale");
  await page.getByLabel("Simulate window_open", { exact: true }).uncheck();
  out = await step(page);
  expect(out).toEqual(previous);
  await page
    .getByLabel("Quality scheduled_occupied", { exact: true })
    .selectOption("good");
  out = await step(page);
  expect(out.setpoint_profile).toBe(2);
  expect(out.population_offset_applied).toBe(true);
});

test("coupled conversion preserves all absolute pairs, population delta, flags and seconds and restores selected-unit defaults", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "timed-offset", "absolute-pair");
  await dialog
    .getByLabel("Population offset (temperature difference)", { exact: true })
    .fill("2");
  await dialog
    .getByLabel("Zone target temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  let report = await review(page, dialog);
  expect(report.choices.occupied_heating_setpoint).toBe(190 / 9);
  expect(report.choices.unoccupied_cooling_setpoint).toBe(250 / 9);
  expect(report.choices.population_control.offset).toBe(10 / 9);
  expect(report.choices.population_control.entry_seconds).toBe(2);
  expect(report.choices.population_control.populated_default).toBe(false);
  await dialog
    .getByLabel("Population target branch", { exact: true })
    .selectOption("off");
  await dialog
    .getByLabel("Window target branch", { exact: true })
    .selectOption("off");
  report = await review(page, dialog);
  expect(report.choices.population_control).toBeNull();
  expect(report.choices.window_control).toBeNull();
  expect(report.inputs).toHaveLength(1);
  await dialog
    .getByLabel("Population target branch", { exact: true })
    .selectOption("timed-offset");
  await dialog
    .getByLabel("Window target branch", { exact: true })
    .selectOption("absolute-pair");
  report = await review(page, dialog);
  expect(report.choices.population_control.offset).toBe(5 / 9);
  expect(report.choices.window_control.heating_setpoint).toBe(40 / 9);
});

test("tiny positive delta follows actual binary64 conversion without an invented minimum", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "timed-offset", "off");
  await dialog
    .getByLabel("Population offset (temperature difference)", { exact: true })
    .fill("5e-324");
  await dialog
    .getByLabel("Zone target temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  expect((await review(page, dialog)).choices.population_control.offset).toBe(
    5e-324,
  );
  await dialog
    .getByLabel("Zone target temperature units", { exact: true })
    .selectOption("degF");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  expect((await review(page, dialog)).choices.population_control.offset).toBe(
    1e-323,
  );
});

test("scientific absolute and delta tokens survive original Program review, creation and save", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "timed-offset", "off");
  await dialog
    .getByLabel("Occupied heating target", { exact: true })
    .fill("0.000001");
  await dialog
    .getByLabel("Population offset (temperature difference)", { exact: true })
    .fill("0.000001");
  const report = await review(page, dialog);
  const file = await downloading(page, dialog);
  expect(file.bytes.toString()).toContain("1e-06");
  execFileSync(
    python,
    [
      "-c",
      "import json,sys;from bms_tool.models import Program;r=json.load(open(sys.argv[1]));p=Program.model_validate(r['program']);assert p.digest()==r['program_sha256'];assert p.metadata['zone_setpoint_wizard']['choices']['population_control']['offset']==1e-6;assert next(n for n in p.nodes if n.id=='occupied_heating').params['value']==1e-6",
      file.file,
    ],
    { cwd: root, env: environment() },
  );
  await create(page, dialog);
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  await expect(
    page.getByLabel("Last saved revision", { exact: true }),
  ).toContainText("r1");
  const saved = await page.request.get("/api/projects/" + report.program.id);
  await test.info().attach("original-scientific-saved-zone-project", {
    body: await saved.body(),
    contentType: "application/json",
  });
});

test("explicit branches, reachable target order and aligned whole timings block invalid creation without replacing current work", async ({
  page,
}) => {
  const dialog = await open(page),
    original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
  await expect(
    dialog.getByRole("button", {
      name: "Preview zone target project",
      exact: true,
    }),
  ).toBeDisabled();
  await configure(dialog, "timed-offset", "absolute-pair");
  for (const [label, bad, good] of [
    ["Occupied heating target", "74", "70"],
    ["Population offset (temperature difference)", "150", "1"],
    ["Population entry dwell (seconds)", "1.5", "2"],
    ["Window-open heating target", "130", "40"],
  ]) {
    await dialog.getByLabel(label, { exact: true }).fill(bad);
    await dialog
      .getByRole("button", { name: "Preview zone target project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await dialog.getByLabel(label, { exact: true }).fill(good);
  }
  await review(page, dialog);
  page.once("dialog", (d) => d.dismiss());
  await dialog
    .getByRole("button", {
      name: "Create editable zone target project",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
  await expect(dialog).toBeVisible();
});

for (const kind of [
  "preview-source",
  "preview-discard",
  "export-source",
  "export-back",
  "units-close",
])
  test(`held ${kind} cannot authorize stale zone-target edits or original exports`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, "timed-offset", "absolute-pair");
    const endpoint = kind.split("-")[0];
    if (endpoint === "export") await review(page, dialog);
    const gate = await held(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (endpoint === "units")
        await dialog
          .getByLabel("Zone target temperature units", { exact: true })
          .selectOption("degC");
      else
        await dialog
          .getByRole("button", {
            name:
              endpoint === "preview"
                ? "Preview zone target project"
                : "Export original zone target review JSON",
            exact: true,
          })
          .click();
      await gate.incoming;
      if (kind.endsWith("source"))
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed editor source");
      else
        await dialog
          .getByRole("button", {
            name: kind.endsWith("discard")
              ? "Discard pending zone target response"
              : kind.endsWith("back")
                ? "Back to equipment wizard"
                : "Cancel zone setpoint wizard",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      expect(downloads).toBe(0);
      await expect(
        page.getByRole("button", {
          name: "Create editable zone target project",
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
  "delta-unit",
  "native-claim",
])
  test(`refuse ${malformed} preview as authority for a zone-target project`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, "timed-offset", "absolute-pair");
    await page.route("**" + base + "/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "choices")
        value.choices.occupied_heating_setpoint = 69;
      else if (malformed === "manifest")
        value.inputs.find((r: any) => r.id === "populated").value_type =
          "number";
      else if (malformed === "delta-unit")
        value.outputs.find(
          (r: any) => r.id === "applied_population_offset",
        ).unit = "degF";
      else value.program.metadata.native_deployment_verified = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", { name: "Preview zone target project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable zone target project",
        exact: true,
      }),
    ).toHaveCount(0);
  });
test("unit response cannot silently change timing or the independent source draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "timed-offset", "absolute-pair");
  await page.route("**" + base + "/units", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.choices.population_control.entry_seconds += 1;
    await route.fulfill({ response, json: value });
  });
  await dialog
    .getByLabel("Zone target temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toContainText("conversion changed");
  await expect(
    dialog.getByLabel("Zone target temperature units", { exact: true }),
  ).toHaveValue("degF");
});
test("incorrect original-export byte hash prevents a zone-review download", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await page.route("**" + base + "/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({
      response,
      body: await response.body(),
      headers: { ...response.headers(), "x-file-sha256": "0".repeat(64) },
    });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await dialog
    .getByRole("button", {
      name: "Export original zone target review JSON",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("changed after");
  expect(downloads).toBe(0);
});
test("unsupported same-ID catalog rules cannot initialize zone-target choices", async ({
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
    .getByRole("button", { name: "Zone setpoint wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Zone setpoint wizard",
    exact: true,
  });
  await expect(dialog.getByRole("alert")).toContainText("unsupported");
  await expect(
    dialog.getByLabel("Zone target project name", { exact: true }),
  ).toHaveCount(0);
});
