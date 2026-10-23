import {
  test,
  expect,
  simulationServerResponseJSON,
  type Page,
} from "./simulationFixture";
import {
  sourceFixtureData,
  projectedSourceFixture,
  resealSourceFixture,
} from "./sourceTransportFixtures";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python"),
  title = "Portable heat-pump browser";
async function open(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Equipment wizard", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Heat-pump wizard", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "Heat-pump wizard",
    exact: true,
  });
  await expect(
    dialog.getByLabel("Heat-pump project name", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("Heat-pump project name", { exact: true })
    .fill(title);
  return dialog;
}
async function declare(dialog: ReturnType<Page["getByRole"]>, heating = false) {
  await dialog
    .getByLabel("Heat-pump reversing valve energized for", { exact: true })
    .selectOption(heating ? "on-for-heating" : "on-for-cooling");
  await dialog
    .getByLabel("Heat-pump initial mode", { exact: true })
    .selectOption(heating ? "heating" : "cooling");
  await dialog
    .getByLabel("Heat-pump fan policy", { exact: true })
    .selectOption("continuous-occupied");
  await dialog
    .getByLabel("Heat-pump condensate policy", { exact: true })
    .selectOption("disable-cooling");
  await dialog
    .getByLabel("Heat-pump default airflow permission", { exact: true })
    .check();
  for (const label of [
    "minimum compressor on",
    "minimum compressor off",
    "compressor-off before valve change",
    "valve settling before restart",
  ]) {
    await dialog
      .getByLabel(`Heat-pump ${label} (seconds)`, { exact: true })
      .fill("2");
  }
  if (heating)
    await dialog
      .getByLabel("Heat-pump default zone temperature", { exact: true })
      .fill("64");
}
async function review(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  const pending = page.waitForResponse(
    (r) => new URL(r.url()).pathname === "/api/heat-pump-wizard/preview",
  );
  await dialog
    .getByRole("button", { name: "Preview heat-pump project", exact: true })
    .click();
  const response = await pending;
  expect(response.status()).toBe(200);
  const report = projectedSourceFixture(await response.json());
  await expect(
    dialog.getByRole("region", { name: "Heat-pump preview", exact: true }),
  ).toBeVisible();
  return report;
}
async function create(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  page.once("dialog", (d) => d.accept());
  await dialog
    .getByRole("button", {
      name: "Create editable heat-pump project",
      exact: true,
    })
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
  return simulationServerResponseJSON(await receipt).history.at(-1).outputs;
}

test("declared cooling graph simulates compressor timing, retains exact review bytes and survives saved interchange", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog);
  await dialog
    .getByLabel("Heat-pump declared controller family", { exact: true })
    .selectOption("johnson-fx");
  await dialog
    .getByLabel("Heat-pump declared model", { exact: true })
    .fill("FX-PCG2611-0");
  const report = await review(page, dialog);
  expect(report.native_compile).toBe(false);
  expect(report.controller_writes).toBe(false);
  expect(report.program.target.model).toBe("FX-PCG2611-0");
  expect(Object.keys(report.outputs)).toHaveLength(12);
  let original: Buffer | undefined,
    header = "";
  await page.route("**/api/heat-pump-wizard/export", async (route) => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
    original = await response.body();
    header = response.headers()["x-file-sha256"];
    await route.fulfill({ response });
  });
  let downloading = page.waitForEvent("download");
  await dialog
    .getByRole("button", {
      name: "Export original heat-pump review JSON",
      exact: true,
    })
    .click();
  const file = (await (await downloading).path())!;
  expect(readFileSync(file)).toEqual(original);
  execFileSync(
    python,
    [
      "-c",
      "import json,hashlib,sys;from bms_tool.models import Program;b=open(sys.argv[1],'rb').read();assert hashlib.sha256(b).hexdigest()==sys.argv[2];r=json.loads(b);assert Program.model_validate(r['program']).digest()==r['program_sha256'];assert not r['native_compile'] and not r['controller_writes']",
      file,
      header,
    ],
    { cwd: root },
  );
  await create(page, dialog);
  let outputs = await step(page);
  expect(outputs.compressor).toBe(false);
  for (let scan = 0; scan < 11 && !outputs.compressor; scan++)
    outputs = await step(page);
  expect(outputs.compressor).toBe(true);
  expect(outputs.cooling_active).toBe(true);
  expect(outputs.heating_active).toBe(false);
  expect(outputs.reversing_valve).toBe(true);
  expect(outputs.fan).toBe(true);
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
    downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const download = await downloading;
    const digest = execFileSync(
      python,
      [
        "-c",
        "import sys;from bms_tool.formats import import_program;p=import_program(open(sys.argv[1],'rb').read(),sys.argv[2]);assert p.revision==1;assert not p.metadata['native_deployment_verified'];assert p.metadata['heat_pump_wizard']['choices']['reversing_polarity']=='on-for-cooling';p.revision=0;print(p.digest())",
        (await download.path())!,
        download.suggestedFilename(),
      ],
      { cwd: root, encoding: "utf8" },
    ).trim();
    expect(digest).toBe(report.program_sha256);
  }
  await page.reload();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    title,
  );
  const restored = await page.request.get("/api/projects/" + report.program.id);
  expect(restored.status()).toBe(200);
  const restoredDigest = execFileSync(
    python,
    [
      "-c",
      "import sys;from bms_tool.models import Program;p=Program.model_validate_json(sys.stdin.buffer.read());assert p.revision==1;p.revision=0;print(p.digest())",
    ],
    { cwd: root, input: await restored.body(), encoding: "utf8" },
  ).trim();
  expect(restoredDigest).toBe(report.program_sha256);
  expect(
    (await (await page.request.get("/api/session")).json()).field_network_open,
  ).toBe(false);
});

test("heating polarity and logical setpoint inputs produce an actual heating simulation", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog, true);
  await dialog
    .getByLabel("Heat-pump setpoint source", { exact: true })
    .selectOption("inputs");
  await dialog
    .getByLabel("Heat-pump fan policy", { exact: true })
    .selectOption("cycle-on-demand");
  const report = await review(page, dialog);
  expect(report.choices.setpoints).toBe("inputs");
  expect(
    report.program.nodes.filter((n: any) => n.kind === "Input").length,
  ).toBeGreaterThan(6);
  await create(page, dialog);
  let outputs = await step(page);
  for (let scan = 0; scan < 11 && !outputs.compressor; scan++)
    outputs = await step(page);
  expect(outputs.compressor).toBe(true);
  expect(outputs.heating_active).toBe(true);
  expect(outputs.cooling_active).toBe(false);
  expect(outputs.reversing_valve).toBe(true);
});

test("temperature units convert absolute values and hysteresis differences together without changing timing or declarations", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog);
  await dialog
    .getByLabel("Heat-pump demand off difference", { exact: true })
    .fill("0.5");
  await dialog
    .getByLabel("Heat-pump temperature units", { exact: true })
    .selectOption("degC");
  await expect
    .poll(async () =>
      Number(
        await dialog
          .getByLabel("Heat-pump default zone temperature", { exact: true })
          .inputValue(),
      ),
    )
    .toBeCloseTo(23.333333333333332, 12);
  expect(
    Number(
      await dialog
        .getByLabel("Heat-pump demand on difference", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(5 / 9, 12);
  expect(
    Number(
      await dialog
        .getByLabel("Heat-pump demand off difference", { exact: true })
        .inputValue(),
    ),
  ).toBeCloseTo(2.5 / 9, 12);
  await expect(
    dialog.getByLabel("Heat-pump minimum compressor off (seconds)", {
      exact: true,
    }),
  ).toHaveValue("2");
  let report = await review(page, dialog);
  expect(report.choices.temperature_unit).toBe("degC");
  await dialog
    .getByLabel("Heat-pump temperature units", { exact: true })
    .selectOption("degF");
  await expect(
    dialog.getByRole("region", { name: "Heat-pump preview", exact: true }),
  ).toHaveCount(0);
  report = await review(page, dialog);
  expect(report.choices.zone_default).toBeCloseTo(74, 10);
  expect(report.choices.demand_on_delta).toBeCloseTo(1, 10);
  await dialog
    .getByLabel("Heat-pump default unit enabled", { exact: true })
    .uncheck();
  await expect(
    dialog.getByRole("button", {
      name: "Create editable heat-pump project",
      exact: true,
    }),
  ).toHaveCount(0);
});

test("missing declarations, invalid hysteresis and fractional or nonaligned timing cannot replace the editor", async ({
  page,
}) => {
  const dialog = await open(page),
    original = await page
      .getByLabel("Program name", { exact: true })
      .inputValue();
  for (const label of [
    "Heat-pump reversing valve energized for",
    "Heat-pump initial mode",
    "Heat-pump fan policy",
    "Heat-pump condensate policy",
  ])
    await expect(dialog.getByLabel(label, { exact: true })).toHaveValue("");
  await dialog
    .getByRole("button", { name: "Preview heat-pump project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await declare(dialog);
  await dialog
    .getByLabel("Heat-pump demand on difference", { exact: true })
    .fill("0");
  await dialog
    .getByRole("button", { name: "Preview heat-pump project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("Heat-pump demand on difference", { exact: true })
    .fill("1");
  await dialog
    .getByLabel("Heat-pump minimum compressor on (seconds)", { exact: true })
    .fill("1.5");
  await dialog
    .getByRole("button", { name: "Preview heat-pump project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await dialog
    .getByLabel("Heat-pump minimum compressor on (seconds)", { exact: true })
    .fill("2");
  await dialog
    .getByLabel("Heat-pump scan interval (seconds)", { exact: true })
    .fill("3");
  await dialog
    .getByRole("button", { name: "Preview heat-pump project", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toBeVisible();
  await expect(
    dialog.getByRole("button", {
      name: "Create editable heat-pump project",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
});

test("declining replacement keeps the editor and accepted preview intact", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog);
  await review(page, dialog);
  const original = await page
    .getByLabel("Program name", { exact: true })
    .inputValue();
  page.once("dialog", (d) => d.dismiss());
  await dialog
    .getByRole("button", {
      name: "Create editable heat-pump project",
      exact: true,
    })
    .click();
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    original,
  );
  await create(page, dialog);
});

for (const kind of [
  "preview-source",
  "preview-close",
  "export-source",
  "export-back",
  "units-source",
  "units-close",
]) {
  test(`held ${kind} cannot authorize stale heat-pump changes or downloads`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await declare(dialog);
    if (kind.startsWith("export")) await review(page, dialog);
    const endpoint = kind.split("-")[0];
    let seen!: () => void, release!: () => void, done!: () => void;
    const requested = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      completed = new Promise<void>((r) => (done = r));
    let downloads = 0;
    page.on("download", () => downloads++);
    await page.route(`**/api/heat-pump-wizard/${endpoint}`, async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      seen();
      await gate;
      await route.fulfill({ response });
      done();
    });
    if (endpoint === "units")
      await dialog
        .getByLabel("Heat-pump temperature units", { exact: true })
        .selectOption("degC");
    else
      await dialog
        .getByRole("button", {
          name:
            endpoint === "preview"
              ? "Preview heat-pump project"
              : "Export original heat-pump review JSON",
          exact: true,
        })
        .click();
    await requested;
    if (kind.endsWith("source"))
      await page
        .getByLabel("Program name", { exact: true })
        .fill("Changed heat-pump source");
    else
      await dialog
        .getByRole("button", {
          name: kind.endsWith("back")
            ? "Back to equipment wizard"
            : "Cancel heat-pump wizard",
          exact: true,
        })
        .click();
    release();
    await completed;
    expect(downloads).toBe(0);
    await expect(
      page.getByRole("button", {
        name: "Create editable heat-pump project",
        exact: true,
      }),
    ).toHaveCount(0);
    if (kind.endsWith("source")) {
      await expect(dialog.getByRole("alert")).toContainText(
        "Current editor changed",
      );
      if (endpoint === "units")
        await expect(
          dialog.getByLabel("Heat-pump temperature units", { exact: true }),
        ).toHaveValue("degF");
    } else await expect(dialog).toHaveCount(0);
  });
}
for (const malformed of ["profile", "outputs", "native-target"]) {
  test(`malformed ${malformed} preview cannot authorize heat-pump creation`, async ({
    page,
  }) => {
    const dialog = await open(page);
    await declare(dialog);
    await page.route("**/api/heat-pump-wizard/preview", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
        envelope = await response.json(),
        value = sourceFixtureData(envelope);
      if (malformed === "profile") value.profile_sha256 = "0".repeat(64);
      else if (malformed === "outputs")
        value.outputs.compressor = "wrong-output";
      else value.program.metadata.native_deployment_verified = true;
      await route.fulfill({
        response,
        json: resealSourceFixture(envelope, value),
      });
    });
    await dialog
      .getByRole("button", { name: "Preview heat-pump project", exact: true })
      .click();
    await expect(dialog.getByRole("alert")).toContainText(
      "does not match these exact choices",
    );
    await expect(
      dialog.getByRole("button", {
        name: "Create editable heat-pump project",
        exact: true,
      }),
    ).toHaveCount(0);
  });
}

test("unit response with changed hysteresis cannot silently alter the declared draft", async ({
  page,
}) => {
  const dialog = await open(page);
  await declare(dialog);
  await page.route("**/api/heat-pump-wizard/units", async (route) => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 }),
      value = await response.json();
    value.choices.demand_on_delta = 17;
    await route.fulfill({ response, json: value });
  });
  await dialog
    .getByLabel("Heat-pump temperature units", { exact: true })
    .selectOption("degC");
  await expect(dialog.getByRole("alert")).toContainText(
    "does not match this exact heat-pump draft",
  );
  await expect(
    dialog.getByLabel("Heat-pump temperature units", { exact: true }),
  ).toHaveValue("degF");
  await expect(
    dialog.getByLabel("Heat-pump demand on difference", { exact: true }),
  ).toHaveValue("1");
  await expect(
    dialog.getByRole("button", {
      name: "Create editable heat-pump project",
      exact: true,
    }),
  ).toHaveCount(0);
});
