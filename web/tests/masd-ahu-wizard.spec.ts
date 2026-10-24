import {
  test,
  expect,
  simulationServerResponseJSON,
  type Page,
  type Locator,
} from "./simulationFixture";
import {
  sourceFixtureData,
  projectedSourceFixture,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../..", import.meta.url)),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/masd-ahu-wizard",
  title = "Portable AHU browser";
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Mixed-air AHU wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Mixed-air AHU wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("AHU project name", { exact: true }),
  ).toBeVisible();
  await dialog.getByLabel("AHU project name", { exact: true }).fill(title);
  return dialog;
}
async function configure(
  dialog: Locator,
  fan = "constant-speed",
  econ = "off",
  temperature = 70,
) {
  await dialog.getByLabel("AHU supply fan", { exact: true }).selectOption(fan);
  await dialog
    .getByLabel("AHU economizer suitability", { exact: true })
    .selectOption(econ);
  await dialog.getByLabel("AHU default occupied", { exact: true }).check();
  await dialog.getByLabel("AHU default unit enabled", { exact: true }).check();
  await dialog.getByLabel("AHU default fan proven", { exact: true }).check();
  for (const [name, value] of [
    ["continuous proof interval", "1"],
    ["stabilization interval", "1"],
    ["startup deadline", "4"],
    ["proof-loss recovery deadline", "4"],
    ["low-command release interval", "1"],
  ])
    await dialog
      .getByLabel(`AHU ${name} (seconds)`, { exact: true })
      .fill(value);
  if (econ !== "off")
    await dialog
      .getByLabel("AHU economizer high-command assist interval (seconds)", {
        exact: true,
      })
      .fill("1");
  await dialog
    .getByLabel("AHU default supply-air temperature", { exact: true })
    .fill(String(temperature));
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
    .getByRole("button", { name: "Preview AHU project", exact: true })
    .click();
  await expect(
    dialog.getByRole("region", { name: "AHU preview", exact: true }),
  ).toBeVisible();
  expect(original).toBeDefined();
  return projectedSourceFixture(JSON.parse(original!.toString()));
}
async function create(page: Page, dialog: Locator) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", { name: "Create editable AHU project", exact: true })
    .click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
}
async function step(page: Page) {
  const receipt = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/simulation/step",
  );
  await page
    .getByRole("button", { name: "Step simulation", exact: true })
    .click();
  const response = await receipt;
  expect(response.status()).toBe(200);
  return simulationServerResponseJSON(response).history.at(-1).outputs;
}
async function downloading(page: Page, dialog: Locator) {
  const waiting = page.waitForEvent("download");
  await dialog
    .getByRole("button", {
      name: "Export original AHU review JSON",
      exact: true,
    })
    .click();
  const file = (await (await waiting).path())!;
  return { file, bytes: readFileSync(file) };
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
for (const [fan, econ, unit, temperature] of [
  ["constant-speed", "off", "degF", 50],
  ["variable-speed", "off", "degC", 70],
  ["constant-speed", "fixed-drybulb", "degC", 57],
  ["variable-speed", "fixed-drybulb", "degF", 70],
  ["constant-speed", "differential-drybulb", "degF", 57],
  ["variable-speed", "differential-drybulb", "degC", 70],
] as const)
  test(`authors ${fan} ${econ} in ${unit} and simulates an ordinary editable AHU`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, fan, econ, temperature);
    await dialog
      .getByLabel("AHU declared controller family", { exact: true })
      .selectOption("johnson-metasys");
    await dialog
      .getByLabel("AHU declared model", { exact: true })
      .fill("MS-FAC2611-0");
    if (unit === "degC") {
      await dialog
        .getByLabel("AHU temperature units", { exact: true })
        .selectOption(unit);
      await expect(
        dialog.getByLabel("AHU temperature units", { exact: true }),
      ).toHaveValue(unit);
      await expect(dialog.getByRole("status")).toHaveCount(0);
    }
    const report = await review(page, dialog);
    expect(report.native_compile).toBe(false);
    expect(report.controller_writes).toBe(false);
    expect(report.can_create).toBe(true);
    expect(report.program.target.model).toBe("MS-FAC2611-0");
    expect(report.inputs.some((r: any) => r.id === "duct_pressure")).toBe(
      fan === "variable-speed",
    );
    expect(report.inputs.some((r: any) => r.id === "outdoor_temperature")).toBe(
      econ !== "off",
    );
    expect(report.inputs.some((r: any) => r.id === "return_temperature")).toBe(
      econ === "differential-drybulb",
    );
    expect(report.outputs.some((r: any) => /airflow/i.test(r.id))).toBe(false);
    let raw: Buffer | undefined,
      header = "";
    await page.route("**" + base + "/export", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
      raw = await response.body();
      header = response.headers()["x-file-sha256"];
      await route.fulfill({ response, body: raw });
    });
    const exported = await downloading(page, dialog);
    expect(exported.bytes).toEqual(raw);
    execFileSync(
      python,
      [
        "-c",
        "import json,hashlib,sys;from bms_tool.models import Program;b=open(sys.argv[1],'rb').read();r=json.loads(b);assert hashlib.sha256(b).hexdigest()==sys.argv[2];assert Program.model_validate(r['program']).digest()==r['program_sha256'];assert not r['native_compile'] and not r['controller_writes']",
        exported.file,
        header,
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      },
    );
    await create(page, dialog);
    let outputs = await step(page);
    for (let i = 0; i < 8 && !outputs.fan_ready; i++)
      outputs = await step(page);
    for (let i = 0; i < 3; i++) outputs = await step(page);
    expect(outputs.fan_enable).toBe(true);
    expect(outputs.fan_ready).toBe(true);
    expect(outputs.fan_fault).toBe(false);
    expect(outputs.heating_valve > 0 && outputs.cooling_valve > 0).toBe(false);
    if (temperature === 50) {
      expect(outputs.heating_valve).toBeGreaterThan(0);
      expect(outputs.cooling_valve).toBe(0);
    } else if (econ === "off" || temperature === 70) {
      expect(outputs.cooling_valve).toBeGreaterThan(0);
      expect(outputs.heating_valve).toBe(0);
    } else {
      expect(outputs.economizer_active_output).toBe(true);
      expect(outputs.cooling_valve).toBe(0);
    }
    expect(outputs.mixing_damper).toBeGreaterThanOrEqual(10);
    if (econ === "off") expect(outputs.mixing_damper).toBe(10);
    if (fan === "variable-speed") {
      expect(outputs.fan_speed).toBeGreaterThanOrEqual(20);
      expect(outputs.fan_speed).toBeLessThanOrEqual(100);
    }
    if (fan === "constant-speed" && econ === "off") {
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
        await page.getByRole("button", { name: "Export", exact: true }).click();
        const file = await waiting;
        const digest = execFileSync(
          python,
          [
            "-c",
            "import sys;from bms_tool.formats import import_program;p=import_program(open(sys.argv[1],'rb').read(),sys.argv[2]);assert p.revision==1;assert not p.metadata['native_deployment_verified'];assert p.metadata['masd_ahu_wizard']['choices']['fan']=='constant-speed';p.revision=0;print(p.digest())",
            (await file.path())!,
            file.suggestedFilename(),
          ],
          {
            cwd: root,
            encoding: "utf8",
            env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
          },
        ).trim();
        expect(digest).toBe(report.program_sha256);
      }
      await page.reload();
      await expect(
        page.getByLabel("Program name", { exact: true }),
      ).toHaveValue(title);
      const restored = await page.request.get(
        "/api/projects/" + report.program.id,
      );
      expect(restored.status()).toBe(200);
      const restoredDigest = execFileSync(
        python,
        [
          "-c",
          "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;p.revision=0;print(p.digest())",
        ],
        {
          cwd: root,
          input: await restored.body(),
          encoding: "utf8",
          env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
        },
      ).trim();
      expect(restoredDigest).toBe(report.program_sha256);
    }
    expect(
      (await (await page.request.get("/api/session")).json())
        .field_network_open,
    ).toBe(false);
  });

test("temperature conversion couples absolute, difference and reciprocal gains while preserving Pa and branch defaults", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "variable-speed", "differential-drybulb");
  await dialog
    .getByLabel("AHU pressure proportional gain (%/Pa)", { exact: true })
    .fill("0.25");
  await dialog
    .getByLabel("AHU duct static setpoint (Pa)", { exact: true })
    .fill("321.25");
  await dialog
    .getByLabel("AHU heating proportional gain (%/degree)", { exact: true })
    .fill("18");
  await dialog
    .getByLabel("AHU temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  expect(
    Number(
      await dialog
        .getByLabel("AHU supply-air center setpoint", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(115 / 9, 10);
  expect(
    Number(
      await dialog
        .getByLabel("AHU heating/cooling temperature band", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(10 / 9, 10);
  expect(
    Number(
      await dialog
        .getByLabel("AHU heating proportional gain (%/degree)", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(32.4, 10);
  await expect(
    dialog.getByLabel("AHU duct static setpoint (Pa)", { exact: true }),
  ).toHaveValue("321.25");
  await expect(
    dialog.getByLabel("AHU pressure proportional gain (%/Pa)", { exact: true }),
  ).toHaveValue("0.25");
  let report = await review(page, dialog);
  expect(report.choices.economizer_control.differential_on).toBeCloseTo(
    5 / 3,
    10,
  );
  await dialog
    .getByLabel("AHU temperature units", { exact: true })
    .selectOption("degF");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  report = await review(page, dialog);
  expect(report.choices.sat_setpoint).toBeCloseTo(55, 10);
  expect(report.choices.heating_kp).toBeCloseTo(18, 10);
  expect(report.choices.variable_fan.setpoint_pa).toBe(321.25);
});

test("fan proof loss closes coils and OA, times out, and requires a rising reset with no run request", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "variable-speed", "off");
  await review(page, dialog);
  await create(page, dialog);
  let out = await step(page);
  for (let i = 0; i < 8 && !out.fan_ready; i++) out = await step(page);
  expect(out.fan_ready).toBe(true);
  await page.getByLabel("Simulate fan_proven", { exact: true }).uncheck();
  out = await step(page);
  expect(out.fan_ready).toBe(false);
  expect(out.heating_valve).toBe(0);
  expect(out.cooling_valve).toBe(0);
  expect(out.mixing_damper).toBe(0);
  for (let i = 0; i < 6 && !out.fan_fault; i++) out = await step(page);
  expect(out.fan_fault).toBe(true);
  expect(out.fan_enable).toBe(false);
  await page.getByLabel("Simulate fan_reset", { exact: true }).check();
  out = await step(page);
  expect(out.fan_fault).toBe(true);
  await page.getByLabel("Simulate unit_enable", { exact: true }).uncheck();
  out = await step(page);
  expect(out.fan_fault).toBe(true);
  await page.getByLabel("Simulate fan_reset", { exact: true }).uncheck();
  await step(page);
  await page.getByLabel("Simulate fan_reset", { exact: true }).check();
  out = await step(page);
  expect(out.fan_fault).toBe(false);
  expect(out.fan_enable).toBe(false);
});

test("explicit selections, temperature band, aligned timing and declined editor replacement preserve current work", async ({
  page,
}) => {
  const dialog = await open(page),
    original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
  await expect(
    dialog.getByRole("button", { name: "Preview AHU project", exact: true }),
  ).toBeDisabled();
  await configure(dialog);
  await dialog
    .getByLabel("AHU heating/cooling temperature band", { exact: true })
    .fill("0.25");
  await dialog
    .getByRole("button", { name: "Preview AHU project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("AHU heating/cooling temperature band", { exact: true })
    .fill("2");
  await dialog
    .getByLabel("AHU continuous proof interval (seconds)", { exact: true })
    .fill("1.5");
  await dialog
    .getByRole("button", { name: "Preview AHU project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("AHU continuous proof interval (seconds)", { exact: true })
    .fill("1");
  await dialog
    .getByLabel("AHU scan interval (seconds)", { exact: true })
    .fill("2");
  await dialog
    .getByRole("button", { name: "Preview AHU project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("AHU scan interval (seconds)", { exact: true })
    .fill("1");
  await review(page, dialog);
  page.once("dialog", (d) => d.dismiss());
  await dialog
    .getByRole("button", { name: "Create editable AHU project", exact: true })
    .click();
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});

for (const kind of [
  "preview-source",
  "preview-discard",
  "export-source",
  "export-back",
  "units-close",
])
  test(`held ${kind} cannot authorize stale AHU editor changes or downloads`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, "variable-speed", "differential-drybulb");
    const endpoint = kind.split("-")[0];
    if (endpoint === "export") await review(page, dialog);
    const gate = await held(page, endpoint);
    let downloads = 0;
    page.on("download", () => downloads++);
    try {
      if (endpoint === "units")
        await dialog
          .getByLabel("AHU temperature units", { exact: true })
          .selectOption("degC");
      else
        await dialog
          .getByRole("button", {
            name:
              endpoint === "preview"
                ? "Preview AHU project"
                : "Export original AHU review JSON",
            exact: true,
          })
          .click();
      await gate.incoming;
      if (kind.endsWith("source"))
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Different current AHU source");
      else if (kind.endsWith("discard"))
        await dialog
          .getByRole("button", {
            name: "Discard pending AHU response",
            exact: true,
          })
          .click();
      else
        await dialog
          .getByRole("button", {
            name: kind.endsWith("back")
              ? "Back to equipment wizard"
              : "Cancel AHU wizard",
            exact: true,
          })
          .click();
      gate.release();
      await gate.finished;
      expect(downloads).toBe(0);
      await expect(
        page.getByRole("button", {
          name: "Create editable AHU project",
          exact: true,
        }),
      ).toHaveCount(0);
      if (kind.endsWith("source"))
        await expect(dialog.getByRole("alert")).toContainText(
          "Current editor changed",
        );
      if (kind.endsWith("discard")) {
        await expect(dialog.getByRole("alert")).toContainText("ignored");
        await dialog
          .getByLabel("AHU project name", { exact: true })
          .fill("Revised after cancellation");
      }
    } finally {
      gate.release();
    }
  });
for (const malformed of ["profile", "choices", "manifest", "native-claim"])
  test(`malformed ${malformed} preview cannot authorize AHU creation`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await configure(dialog, "variable-speed", "differential-drybulb");
    await page.route("**" + base + "/preview", async (route) => {
      const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "choices") value.choices.minimum_oa_percent = 99;
      else if (malformed === "manifest")
        value.inputs.find((r: any) => r.id === "duct_pressure").unit = "kPa";
      else value.program.metadata.native_deployment_verified = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", { name: "Preview AHU project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: "Create editable AHU project",
        exact: true,
      }),
    ).toHaveCount(0);
  });
test("unit conversion cannot silently change Pa options or a different source draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "variable-speed", "differential-drybulb");
  await page.route("**" + base + "/units", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 }),
      value = await response.json();
    value.choices.variable_fan.setpoint_pa += 1;
    await route.fulfill({ response, json: value });
  });
  await dialog
    .getByLabel("AHU temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toContainText("Pa");
  await expect(
    dialog.getByLabel("AHU temperature units", { exact: true }),
  ).toHaveValue("degF");
});
test("an incorrect original-export byte digest blocks the download", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog);
  await review(page, dialog);
  await page.route("**" + base + "/export", async (route) => {
    const response = await route.fetch({ maxRetries: 0, maxRedirects: 0 });
    await route.fulfill({
      response,
      headers: { ...response.headers(), "x-file-sha256": "0".repeat(64) },
    });
  });
  let downloads = 0;
  page.on("download", () => downloads++);
  await dialog
    .getByRole("button", {
      name: "Export original AHU review JSON",
      exact: true,
    })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("changed after");
  expect(downloads).toBe(0);
});
test("branch switches remove irrelevant pressure and RA options and restore unit-qualified defaults", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "variable-speed", "differential-drybulb");
  await dialog
    .getByLabel("AHU temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("status")).toHaveCount(0);
  await dialog
    .getByLabel("AHU supply fan", { exact: true })
    .selectOption("constant-speed");
  await dialog
    .getByLabel("AHU economizer suitability", { exact: true })
    .selectOption("off");
  let report = await review(page, dialog);
  expect(report.choices.variable_fan).toBeNull();
  expect(report.choices.economizer_control).toBeNull();
  expect(
    report.inputs.some(
      (r: any) =>
        r.id === "outdoor_temperature" ||
        r.id === "duct_pressure" ||
        r.id === "return_temperature",
    ),
  ).toBe(false);
  await dialog
    .getByLabel("AHU economizer suitability", { exact: true })
    .selectOption("fixed-drybulb");
  await expect(
    dialog.getByLabel("AHU default outdoor-air temperature", { exact: true }),
  ).toHaveValue("10");
  report = await review(page, dialog);
  expect(report.choices.economizer_control.ra_default).toBeNull();
  expect(report.choices.economizer_control.differential_on).toBeNull();
});

test("a same-ID catalog with an unsupported rules hash cannot initialize AHU choices", async ({
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
    .getByRole("button", { name: "Mixed-air AHU wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Mixed-air AHU wizard",
    exact: true,
  });
  await expect(dialog.getByRole("alert")).toContainText("unsupported");
  await expect(
    dialog.getByLabel("AHU project name", { exact: true }),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "Preview AHU project", exact: true }),
  ).toBeDisabled();
});

test("valid scientific gain and input-default tokens preserve original Program bytes through preview and export", async ({
  page,
}) => {
  const dialog = await open(page);
  await configure(dialog, "constant-speed", "off");
  await dialog
    .getByLabel("AHU heating proportional gain (%/degree)", { exact: true })
    .fill("0.000001");
  await dialog
    .getByLabel("AHU default supply-air temperature", { exact: true })
    .fill("0.000001");
  const value = await review(page, dialog);
  expect(value.choices.heating_kp).toBe(0.000001);
  expect(value.choices.sat_default).toBe(0.000001);
  const result = await downloading(page, dialog);
  expect(result.bytes.toString()).toContain("1e-06");
  execFileSync(
    python,
    [
      "-c",
      "import json,sys;from bms_tool.models import Program;r=json.load(open(sys.argv[1]));p=Program.model_validate(r['program']);assert p.digest()==r['program_sha256'];assert p.metadata['masd_ahu_wizard']['choices']['heating_kp']==1e-6;assert next(n for n in p.nodes if n.id=='sat').params['default']==1e-6",
      result.file,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
    },
  );
  await dialog
    .getByLabel("AHU default supply-air temperature", { exact: true })
    .fill("-0");
  expect((await review(page, dialog)).choices.sat_default).toBe(0);
});
