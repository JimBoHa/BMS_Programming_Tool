import {
  test,
  expect,
  type APIRequestContext,
  type Page,
  type Locator,
  type Route,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python"),
  base = "/api/plant-signals";
const py = (code: string, input?: string) =>
  execFileSync(python, ["-c", code], {
    cwd: root,
    input,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
  });
function fixture() {
  return JSON.parse(
    py(
      "import json,tempfile;from tests.test_plant_signals import make_case,programs\nwith tempfile.TemporaryDirectory() as d:\n service,plan=make_case(d);print(json.dumps({'programs':[p.model_dump_json() for p in programs()],'plan':plan}))",
    ),
  );
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function post(request: APIRequestContext, suffix: string, data: unknown) {
  const response = await request.post(base + suffix, {
    headers: await headers(request),
    data,
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response;
}
async function seed(request: APIRequestContext) {
  const f = fixture();
  for (const raw of f.programs) {
    const response = await request.post(base + "/sources/import", {
      headers: await headers(request),
      multipart: {
        file: {
          name: "source.json",
          mimeType: "application/json",
          buffer: Buffer.from(raw),
        },
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  const profile = await (await request.get(base + "/profile")).json();
  const review = await (
    await post(request, "/review", {
      profile_sha256: profile.profile.sha256,
      plan: f.plan,
    })
  ).json();
  const capture = await (
    await post(request, "/captures/save", {
      id: review.id,
      content_sha256: review.content_sha256,
    })
  ).json();
  return { ...f, review, capture };
}
async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Plant I/O and network engineering schedule",
    exact: true,
  });
  await panel
    .getByRole("button", {
      name: "Open offline plant engineering schedule",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("table", {
      name: "Retained plant Program sources",
      exact: true,
    }),
  ).toBeVisible();
  return panel;
}
async function openCapture(panel: Locator, id: string) {
  await panel
    .getByRole("button", {
      name: "Open plant capture " + id.slice(0, 8),
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("Reviewed plant engineering schedule", { exact: true }),
  ).toBeVisible();
}
async function downloaded(page: Page, panel: Locator, name: string) {
  const waiting = page.waitForEvent("download");
  await panel.getByRole("button", { name, exact: true }).click();
  const result = await waiting,
    file = (await result.path())!;
  return { file, bytes: readFileSync(file) };
}
async function holdActual(page: Page, suffix: string) {
  let release!: () => void,
    entered!: (data: { body: Buffer; request: any }) => void,
    done!: () => void;
  const gate = new Promise<void>((resolve) => {
      release = resolve;
    }),
    incoming = new Promise<{ body: Buffer; request: any }>((resolve) => {
      entered = resolve;
    }),
    finished = new Promise<void>((resolve) => {
      done = resolve;
    });
  const pattern = "**" + base + suffix;
  const handler = async (route: Route) => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
    const body = await response.body();
    entered({ body, request: route.request().postDataJSON() });
    await gate;
    try {
      await route.fulfill({ response, body });
    } finally {
      done();
    }
  };
  await page.route(pattern, handler);
  return {
    incoming,
    release,
    finished,
    dispose: () => page.unroute(pattern, handler),
  };
}
function checkSealed(file: string) {
  const output = execFileSync(
    python,
    [
      "-c",
      `
import csv,hashlib,json,math,sys
v=json.load(open(sys.argv[1]));canonical=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
assert v['content_sha256']==hashlib.sha256(canonical({k:x for k,x in v.items() if k!='content_sha256'})).hexdigest()
assert v['plan_sha256']==hashlib.sha256(canonical(v['plan'])).hexdigest()
assert v['field_queries'] is False and v['field_writes'] is False
for s in v['sources']:
 assert s['id']==hashlib.sha256(s['source_json'].encode()).hexdigest()
 p=json.loads(s['source_json'])
 if p['id']=='plant-sender':
  a=p['metadata']['opaque'];assert type(a[0]) is int and a[0]==9007199254740993;assert type(a[1]) is float and a[1]==1.0;assert type(a[2]) is float and math.copysign(1,a[2])==-1
print(json.dumps({'id':v['id'],'content_sha256':v['content_sha256'],'ports':len(v['analysis']['io_schedule']),'links':len(v['analysis']['network_schedule'])}))
`,
      file,
    ],
    { encoding: "utf8" },
  );
  return JSON.parse(output);
}

test("authors exact source-bound plant declarations, exports sealed original schedules and reopens a durable capture offline", async ({
  page,
  request,
}) => {
  const f = fixture(),
    unexpected: string[] = [];
  page.on("request", (r) => {
    if (
      /\/api\/(bacnet|modbus|runtime|native|serial)\//.test(
        new URL(r.url()).pathname,
      )
    )
      unexpected.push(r.url());
  });
  const panel = await open(page);
  for (const [index, raw] of f.programs.entries()) {
    await panel
      .getByLabel("Plant Program source file", { exact: true })
      .setInputFiles({
        name: `program-${index}.json`,
        mimeType: "application/json",
        buffer: Buffer.from(raw),
      });
    await expect(panel.getByRole("status")).toContainText(
      "Exact Program source retained",
    );
  }
  for (const label of ["Declared chiller host", "Declared pump host"]) {
    await panel.getByLabel("New plant host label", { exact: true }).fill(label);
    await panel
      .getByRole("button", { name: "Add declared plant host", exact: true })
      .click();
  }
  for (const [index, instance] of f.plan.instances.entries()) {
    await panel
      .getByLabel("New plant instance label", { exact: true })
      .fill(instance.label);
    await panel
      .getByLabel("New plant instance source", { exact: true })
      .selectOption(instance.source_id);
    await panel
      .getByLabel("New plant instance host", { exact: true })
      .selectOption("host" + (index + 1));
    await panel
      .getByLabel("New plant subsystem " + instance.subsystems[0], {
        exact: true,
      })
      .check();
    await panel
      .getByRole("button", {
        name: "Add source-bound plant instance",
        exact: true,
      })
      .click();
  }
  await expect(
    panel.getByLabel("Plant role instance1/flow_sensor", { exact: true }),
  ).toHaveValue("unassigned");
  await expect(
    panel.getByLabel("Plant terminal instance1/flow_sensor", { exact: true }),
  ).toHaveValue("");
  await expect(
    panel.getByRole("table", { name: "Declared plant interface roles" }),
  ).toContainText("Source hint only: UI1");
  const assignments = [
    ["instance1/flow_sensor", "sensor", "UI1"],
    ["instance1/flow_source", "network-source", ""],
    ["instance2/flow_dest", "network-destination", ""],
    ["instance2/pump_speed", "command", "AO1"],
  ];
  for (const [id, role, terminal] of assignments) {
    await panel
      .getByLabel("Plant role " + id, { exact: true })
      .selectOption(role);
    if (terminal)
      await panel
        .getByLabel("Plant terminal " + id, { exact: true })
        .fill(terminal);
  }
  await panel
    .getByLabel("Plant link source", { exact: true })
    .selectOption(JSON.stringify(["instance1", "flow_source"]));
  await panel
    .getByLabel("Plant link target", { exact: true })
    .selectOption(JSON.stringify(["instance2", "flow_dest"]));
  await panel
    .getByRole("button", { name: "Add explicit plant link", exact: true })
    .click();
  await panel
    .getByRole("button", {
      name: "Review plant I/O and network schedule",
      exact: true,
    })
    .click();
  await expect(
    panel.getByLabel("Reviewed plant engineering schedule", { exact: true }),
  ).toContainText(
    "Software-consistent declarations; hardware remains unverified",
  );
  await expect(
    panel.getByRole("table", {
      name: "Reviewed plant network schedule",
      exact: true,
    }),
  ).toContainText("fanout 1");
  const json = await downloaded(page, panel, "Export sealed plant review JSON"),
    seal = checkSealed(json.file);
  expect(seal.ports).toBe(4);
  expect(seal.links).toBe(1);
  const authoritative = await post(request, "/reviews/export/json", {
    id: seal.id,
    content_sha256: seal.content_sha256,
  });
  expect(json.bytes.equals(await authoritative.body())).toBe(true);
  const csv = await downloaded(page, panel, "Export plant I/O and network CSV");
  const csvRows = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "import csv,json,sys;print(json.dumps(list(csv.DictReader(open(sys.argv[1])))))",
        csv.file,
      ],
      { encoding: "utf8" },
    ),
  );
  expect(csvRows).toHaveLength(5);
  expect(
    csvRows.every((r: any) => r.review_content_sha256 === seal.content_sha256),
  ).toBe(true);
  const saving = page.waitForResponse((r) =>
    r.url().endsWith(base + "/captures/save"),
  );
  await panel
    .getByRole("button", {
      name: "Save reviewed plant capture locally",
      exact: true,
    })
    .click();
  const capture = await (await saving).json();
  await expect(
    panel.getByRole("button", {
      name: "Open plant capture " + capture.id.slice(0, 8),
      exact: true,
    }),
  ).toBeVisible();
  const exported = await downloaded(
    page,
    panel,
    "Export capture JSON " + capture.id.slice(0, 8),
  );
  expect(exported.bytes.equals(json.bytes)).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  const restored = page.getByRole("region", {
    name: "Plant I/O and network engineering schedule",
    exact: true,
  });
  await restored
    .getByRole("button", {
      name: "Open offline plant engineering schedule",
      exact: true,
    })
    .click();
  await openCapture(restored, capture.id);
  const reopened = await downloaded(
    page,
    restored,
    "Export sealed plant review JSON",
  );
  expect(reopened.bytes.equals(json.bytes)).toBe(true);
  expect(unexpected).toEqual([]);
});

test("current and selected saved revisions preserve opaque numeric source tokens without source execution", async ({
  page,
  request,
}) => {
  const f = fixture(),
    raw = f.programs[0];
  await page.goto("/");
  await page.locator('input[type=file][accept*=".st"]').setInputFiles({
    name: "exact-plant.bms.json",
    mimeType: "application/json",
    buffer: Buffer.from(raw),
  });
  await expect(page.getByLabel("Program name", { exact: true })).toHaveValue(
    "Flow sender",
  );
  const saving = page.waitForResponse(
    (r) => r.url().endsWith("/api/projects") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Save revision", exact: true })
    .click();
  expect((await saving).ok()).toBe(true);
  await expect(page.locator(".validation-bar")).toContainText("r1");
  await page.getByRole("button", { name: "System sim", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Plant I/O and network engineering schedule",
    exact: true,
  });
  await panel
    .getByRole("button", {
      name: "Open offline plant engineering schedule",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("table", {
      name: "Retained plant Program sources",
      exact: true,
    }),
  ).toBeVisible();
  const imported = page.waitForResponse((r) =>
    r.url().endsWith(base + "/sources/import"),
  );
  await panel
    .getByRole("button", {
      name: "Retain exact current Program source",
      exact: true,
    })
    .click();
  const source = await (await imported).json();
  const first = await downloaded(
    page,
    panel,
    "Export source " + source.id.slice(0, 8),
  );
  const projected = JSON.parse(
    execFileSync(
      python,
      [
        "-c",
        "import json,math,sys;v=json.load(open(sys.argv[1]));a=v['metadata']['opaque'];assert type(a[0]) is int and a[0]==9007199254740993;assert type(a[1]) is float;assert math.copysign(1,a[2])==-1;print(json.dumps({'id':v['id'],'revision':v['revision']}))",
        first.file,
      ],
      { encoding: "utf8" },
    ),
  );
  const selected = page.waitForRequest((r) =>
    r.url().includes("/api/projects/" + projected.id + "?revision="),
  );
  const secondImport = page.waitForResponse((r) =>
    r.url().endsWith(base + "/sources/import"),
  );
  await panel
    .getByLabel("Retain saved Program revision", { exact: true })
    .selectOption(projected.id);
  expect((await selected).url()).toContain("?revision=" + projected.revision);
  const saved = await (await secondImport).json();
  const second = await downloaded(
    page,
    panel,
    "Export source " + saved.id.slice(0, 8),
  );
  expect(second.bytes.equals(first.bytes)).toBe(true);
});

test("review diagnoses unassigned roles, conflicting terminal declarations and duplicate writers without guessing", async ({
  page,
  request,
}) => {
  const seeded = await seed(request),
    panel = await open(page);
  await openCapture(panel, seeded.capture.id);
  await panel
    .getByLabel("Plant role chillers/flow_source", { exact: true })
    .selectOption("unassigned");
  await panel
    .getByLabel("Plant instance host pumps", { exact: true })
    .selectOption("controller_a");
  await panel
    .getByLabel("Plant terminal pumps/pump_speed", { exact: true })
    .fill("UI1");
  await panel
    .getByLabel("Plant link source", { exact: true })
    .selectOption(JSON.stringify(["chillers", "flow_source"]));
  await panel
    .getByLabel("Plant link target", { exact: true })
    .selectOption(JSON.stringify(["pumps", "flow_dest"]));
  await panel
    .getByRole("button", { name: "Add explicit plant link", exact: true })
    .click();
  await panel
    .getByRole("button", {
      name: "Review plant I/O and network schedule",
      exact: true,
    })
    .click();
  const review = panel.getByLabel("Reviewed plant engineering schedule", {
    exact: true,
  });
  await expect(review).toContainText("Unresolved plant declarations");
  for (const code of [
    "unassigned_interface",
    "terminal_collision",
    "multiple_writers",
    "link_direction_role",
  ])
    await expect(review).toContainText(code);
  await expect(
    panel.getByLabel("Plant role chillers/flow_source", { exact: true }),
  ).toHaveValue("unassigned");
});

test("held actual reviews are rejected after host, current Program and source-revision edits", async ({
  page,
  request,
}) => {
  const seeded = await seed(request),
    panel = await open(page);
  await openCapture(panel, seeded.capture.id);
  for (const kind of ["host", "program", "source"] as const) {
    const held = await holdActual(page, "/review");
    try {
      await panel
        .getByRole("button", {
          name: "Review plant I/O and network schedule",
          exact: true,
        })
        .click();
      await held.incoming;
      if (kind === "host")
        await panel
          .getByLabel("Plant host label controller_a", { exact: true })
          .fill("New host declaration");
      else if (kind === "program")
        await page
          .getByLabel("Program name", { exact: true })
          .fill("Changed exact current source");
      else {
        page.once("dialog", (d) => d.accept());
        await panel
          .getByLabel("Plant instance source chillers", { exact: true })
          .selectOption(seeded.plan.instances[1].source_id);
      }
      held.release();
      await held.finished;
      await expect(
        panel
          .getByRole("status")
          .filter({ hasText: "Reviewing declared plant schedule" }),
      ).toHaveCount(0);
      await expect(
        panel.getByLabel("Reviewed plant engineering schedule", {
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        panel.getByRole("button", {
          name: "Export sealed plant review JSON",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      held.release();
      await held.dispose();
    }
  }
});

test("delayed original-byte exports are discarded after a declaration edit or workspace unmount", async ({
  page,
  request,
}) => {
  const seeded = await seed(request),
    panel = await open(page);
  await openCapture(panel, seeded.capture.id);
  const downloads: string[] = [];
  page.on("download", (d) => downloads.push(d.suggestedFilename()));
  const held = await holdActual(page, "/reviews/export/json");
  try {
    await panel
      .getByRole("button", {
        name: "Export sealed plant review JSON",
        exact: true,
      })
      .click();
    await held.incoming;
    await panel
      .getByLabel("Plant host label controller_a", { exact: true })
      .fill("Edited during original-byte export");
    held.release();
    await held.finished;
    await expect(
      panel
        .getByRole("status")
        .filter({ hasText: "Exporting reviewed schedule" }),
    ).toHaveCount(0);
    expect(downloads).toEqual([]);
  } finally {
    held.release();
    await held.dispose();
  }
  page.once("dialog", (d) => d.accept());
  await openCapture(panel, seeded.capture.id);
  const leaving = await holdActual(page, "/captures/export/json");
  try {
    await panel
      .getByRole("button", {
        name: "Export capture JSON " + seeded.capture.id.slice(0, 8),
        exact: true,
      })
      .click();
    await leaving.incoming;
    await page.getByRole("button", { name: "Program", exact: true }).click();
    leaving.release();
    await leaving.finished;
    await page.getByRole("button", { name: "System sim", exact: true }).click();
    await expect(
      page.getByRole("button", {
        name: "Open offline plant engineering schedule",
        exact: true,
      }),
    ).toBeVisible();
    expect(downloads).toEqual([]);
  } finally {
    leaving.release();
    await leaving.dispose();
  }
});

test("capture import never silently replaces a plan and dirty replacement can be refused", async ({
  page,
  request,
}) => {
  const seeded = await seed(request),
    panel = await open(page);
  await openCapture(panel, seeded.capture.id);
  const archive = await downloaded(
    page,
    panel,
    "Export capture JSON " + seeded.capture.id.slice(0, 8),
  );
  await panel
    .getByLabel("Plant schedule name", { exact: true })
    .fill("Retain this unexported declaration");
  await panel
    .getByLabel("Sealed plant capture file", { exact: true })
    .setInputFiles({
      name: "plant-capture.json",
      mimeType: "application/json",
      buffer: archive.bytes,
    });
  await expect(panel.getByRole("status")).toContainText(
    "Capture retained. Open it below",
  );
  await expect(
    panel.getByLabel("Plant schedule name", { exact: true }),
  ).toHaveValue("Retain this unexported declaration");
  let openPosts = 0;
  page.on("request", (r) => {
    if (r.url().endsWith(base + "/captures/open")) openPosts++;
  });
  page.once("dialog", (d) => d.dismiss());
  await panel
    .getByRole("button", {
      name: "Open plant capture " + seeded.capture.id.slice(0, 8),
      exact: true,
    })
    .click();
  expect(openPosts).toBe(0);
  await expect(
    panel.getByLabel("Plant schedule name", { exact: true }),
  ).toHaveValue("Retain this unexported declaration");
  page.once("dialog", (d) => d.accept());
  await openCapture(panel, seeded.capture.id);
  const original = await downloaded(
    page,
    panel,
    "Export sealed plant review JSON",
  );
  expect(original.bytes.equals(archive.bytes)).toBe(true);
});

test("malformed local profile, mismatched source summaries and review rows preserve editable declarations", async ({
  page,
  request,
}) => {
  const seeded = await seed(request),
    panel = await open(page);
  await openCapture(panel, seeded.capture.id);
  await page.route("**" + base + "/profile", (r) =>
    r.fulfill({
      contentType: "application/json",
      body: '{"profile":{"id":"distributed-plant-signals/1"},"sources":null,"captures":null}',
    }),
  );
  await panel
    .getByRole("button", { name: "Refresh local plant catalog", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("profile is malformed");
  await expect(
    panel.getByLabel("Plant instance label chillers", { exact: true }),
  ).toHaveValue("Chiller subsystem");
  await page.unroute("**" + base + "/profile");
  const retained = await (await request.get(base + "/profile")).json();
  const originalSource = retained.sources.find(
    (s: any) => s.id === seeded.plan.instances[0].source_id,
  );
  // Deliberate malformed-response fault. Actual browser multipart ingress is
  // independently exercised by the authoring case, without replaying files.
  await page.route("**" + base + "/sources/import", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: { ...originalSource, id: "0".repeat(64) },
    }),
  );
  await panel
    .getByLabel("Plant Program source file", { exact: true })
    .setInputFiles({
      name: "unchanged-source.json",
      mimeType: "application/json",
      buffer: Buffer.from(seeded.programs[0]),
    });
  await expect(panel.getByRole("alert")).toContainText(
    "does not match the exact uploaded bytes",
  );
  await page.unroute("**" + base + "/sources/import");
  for (const malformed of ["missing_rows", "wrong_source"] as const) {
    await page.route("**" + base + "/review", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      const value = await response.json();
      if (malformed === "missing_rows") value.analysis.io_schedule = null;
      else value.analysis.io_schedule[0].source_id = "0".repeat(64);
      await route.fulfill({ response, json: value });
    });
    await panel
      .getByRole("button", {
        name: "Review plant I/O and network schedule",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      malformed === "missing_rows"
        ? "analysis is malformed"
        : "rows do not bind",
    );
    await expect(
      panel.getByLabel("Plant instance label chillers", { exact: true }),
    ).toHaveValue("Chiller subsystem");
    await page.unroute("**" + base + "/review");
  }
});
