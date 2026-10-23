import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { spawn, execFileSync } from "node:child_process";
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python"),
  BASE = "/api/bacnet/schedules/writes";
const peerSource = `
import asyncio,json,sys
from tests.test_native_schedule_write import WeeklyPeer
from tests.test_schedule_inventory import options
from tests.test_connections import free_udp
async def main():
 p=WeeklyPeer(routed=sys.argv[1]=='routed')
 atom=bytes.fromhex(sys.argv[2]);p.exception_count=0
 p.days=[bytes.fromhex('0eb408000000')+atom+bytes.fromhex('0f')]*7
 p.overrides['schedule,1','present-value',None]=atom
 p.overrides['schedule,1','schedule-default',None]=atom
 await asyncio.get_running_loop().create_datagram_endpoint(lambda:p,local_addr=('127.0.0.1',0))
 print(json.dumps({'options':options(p,object_ids=['schedule,1']),'local':f'127.0.0.1:{free_udp()}'}),flush=True)
 while True:
  line=await asyncio.to_thread(sys.stdin.readline)
  if not line:break
  cmd=json.loads(line)
  if cmd['kind']=='mode':p.mode=cmd['mode']
  if cmd['kind']=='hold':p.hold_property='schedule-default';p.entered.clear();p.release.clear()
  if cmd['kind']=='release':p.hold_property=None;p.release.set()
  print(json.dumps({'reads':len(p.requests),'writes':len(p.writes),'entered':p.entered.is_set(),'days':[d.hex() for d in p.days],'errors':[str(e) for e in p.errors]}),flush=True)
  if cmd['kind']=='stop':break
 p.close();await asyncio.sleep(.01)
asyncio.run(main())
`;
async function peer(routed: boolean, atom = "74006f6c64") {
  const child = spawn(
    python,
    ["-u", "-c", peerSource, routed ? "routed" : "direct", atom],
    { cwd: root },
  );
  const queue: any[] = [],
    waiters: ((data: any) => void)[] = [];
  let errors = "",
    closed = false;
  child.stderr.on("data", (value) => (errors += value));
  createInterface({ input: child.stdout }).on("line", (line) => {
    const value = JSON.parse(line),
      resolve = waiters.shift();
    if (resolve) resolve(value);
    else queue.push(value);
  });
  const next = () =>
    queue.length
      ? Promise.resolve(queue.shift())
      : new Promise<any>((r) => waiters.push(r));
  const ready = await next();
  async function command(kind: string, mode?: string) {
    child.stdin.write(JSON.stringify({ kind, mode }) + "\n");
    return next();
  }
  return {
    ...ready,
    command,
    async close() {
      if (closed) return;
      closed = true;
      const stats = await command("stop");
      expect(stats.errors).toEqual([]);
      child.stdin.end();
      const code = await new Promise<number | null>((resolve) =>
        child.once("exit", resolve),
      );
      expect(code, errors).toBe(0);
    },
  };
}
async function headers(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function disconnect(request: APIRequestContext) {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await headers(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
  expect(
    (await (await request.get("/api/bacnet/status")).json()).connected,
  ).toBe(false);
}
test.afterEach(async ({ request }) => {
  await disconnect(request);
});

const LIB = "/api/bacnet/schedules/library";
const STRING_DRAFT = "native-schedule-utf8-weekly-day-draft/1";
const STRING_WRITE = "native-schedule-reviewed-utf8-weekly-day-write/1";
async function setup(
  page: Page,
  request: APIRequestContext,
  routed = false,
  atom = "74006f6c64",
) {
  const server = await peer(routed, atom);
  try {
    const auth = await headers(request);
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers: auth,
          data: { local_address: server.local },
        })
      ).ok(),
    ).toBe(true);
    const observed = await request.post("/api/bacnet/schedules/read", {
      headers: auth,
      data: server.options,
    });
    expect(observed.ok()).toBe(true);
    const report = await observed.json();
    expect(report.complete).toBe(true);
    const saved = await request.post(LIB + "/save", {
      headers: auth,
      data: { id: report.id },
    });
    expect(saved.ok()).toBe(true);
    const capture = await saved.json();
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const library = page.getByRole("region", {
      name: "Native Schedule capture library",
      exact: true,
    });
    await library
      .getByRole("button", {
        name: `Open capture ${capture.id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    await expect(
      library.getByLabel("Native weekly day", { exact: true }),
    ).toBeVisible();
    return { server, library, capture };
  } catch (error) {
    await server.close();
    throw error;
  }
}
async function capture(
  page: Page,
  endpoint: string,
  work: () => Promise<void>,
) {
  const observed: { raw: Buffer; request: string | null }[] = [];
  const pattern = "**" + endpoint;
  await page.route(pattern, async (route) => {
    const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
    const body = await response.body();
    observed.push({
      raw: Buffer.from(body),
      request: route.request().postData(),
    });
    await route.fulfill({ response, body });
  });
  try {
    await work();
    expect(observed).toHaveLength(1);
    return { ...observed[0], data: JSON.parse(observed[0].raw.toString()) };
  } finally {
    await page.unroute(pattern);
  }
}
async function review(page: Page, library: ReturnType<Page["getByRole"]>) {
  return capture(page, LIB + "/drafts/review", async () => {
    await library
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await expect(
      library.getByLabel("Native weekly draft review", { exact: true }),
    ).toBeVisible();
  });
}
async function openWrite(page: Page) {
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
  await panel
    .getByLabel("Declared native write operator", { exact: true })
    .fill("String UI Operator");
  await panel
    .getByLabel("Native write rationale", { exact: true })
    .fill("Literal loopback String day");
  await expect(
    panel.getByRole("button", {
      name: "Preview fresh native weekly-day write",
      exact: true,
    }),
  ).toBeEnabled();
  return panel;
}
async function preview(page: Page, panel: ReturnType<Page["getByRole"]>) {
  return capture(page, BASE + "/preview", async () => {
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
  });
}
async function downloaded(page: Page, button: ReturnType<Page["getByRole"]>) {
  const pending = page.waitForEvent("download");
  await button.click();
  return readFileSync((await (await pending).path())!);
}
function expectedDay(text: string, withNull = false) {
  return execFileSync(
    python,
    [
      "-c",
      "from tests.test_native_schedule_strings import stringtag;import json,sys;print('0eb408000000'+stringtag(json.loads(sys.argv[1])).hex()+('b41100000000' if sys.argv[2]=='1' else '')+'0f')",
      JSON.stringify(text),
      withNull ? "1" : "0",
    ],
    { cwd: root },
  )
    .toString()
    .trim();
}
async function fillString(
  library: ReturnType<Page["getByRole"]>,
  text: string,
) {
  const editor = library.getByLabel(
    "Transition 1 CharacterString JSON literal",
    { exact: true },
  );
  await editor.fill(JSON.stringify(text));
  await expect(editor).toHaveValue(JSON.stringify(text));
}
for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} String day keeps literal controls and original export bytes through one Apply and reconciliation`, async ({
    page,
    request,
  }) => {
    const { server, library } = await setup(page, request, routed);
    try {
      const text = '  é e\u0301🌡"\\\x00\r\n\t  ';
      await fillString(library, text);
      await library
        .getByRole("button", { name: "Add daily transition", exact: true })
        .click();
      for (const [field, value] of [
        ["hour", "17"],
        ["minute", "0"],
        ["second", "0"],
        ["hundredth", "0"],
      ])
        await library
          .getByLabel(`Transition 2 ${field}`, { exact: true })
          .fill(value);
      await library
        .getByLabel("Transition 2 native type", { exact: true })
        .selectOption("Null");
      const reviewed = await review(page, library);
      expect(reviewed.data.profile).toBe(STRING_DRAFT);
      expect(reviewed.data.request.draft_profile).toBe(STRING_DRAFT);
      expect(reviewed.data.request.transitions[0].value_text).toBe(text);
      expect(reviewed.data.new.encoded_hex).toBe(expectedDay(text, true));
      const download = { bytes: Buffer.alloc(0) };
      const exported = await capture(page, LIB + "/drafts/export", async () => {
        download.bytes = await downloaded(
          page,
          library.getByRole("button", {
            name: "Export exact reviewed weekly draft",
            exact: true,
          }),
        );
      });
      // Review HTTP JSON and stored canonical export legitimately use different
      // serialization. Preserve the actual authoritative export endpoint bytes.
      expect(exported.data).toEqual(reviewed.data);
      expect(download.bytes.equals(exported.raw)).toBe(true);
      const panel = await openWrite(page),
        prepared = await preview(page, panel);
      expect(prepared.data.profile).toBe(STRING_WRITE);
      expect(prepared.data.native_draft.profile).toBe(STRING_DRAFT);
      const previewBytes = await downloaded(
        page,
        panel.getByRole("button", {
          name: "Export exact native write preview",
          exact: true,
        }),
      );
      expect(previewBytes.equals(prepared.raw)).toBe(true);
      const applied = await capture(page, BASE + "/apply", async () => {
        await panel
          .getByRole("button", {
            name: "Apply one native weekly-day request",
            exact: true,
          })
          .click();
        await expect(
          panel.getByLabel("Native write receipt", { exact: true }),
        ).toContainText("accepted");
      });
      expect(applied.data.profile).toBe(STRING_WRITE);
      expect(applied.data.readback.status).toBe("match");
      await panel
        .getByRole("button", {
          name: `Open native receipt ${applied.data.id.slice(0, 12)}`,
          exact: true,
        })
        .click();
      await expect(
        panel.getByLabel("Native write receipt", { exact: true }),
      ).toContainText(applied.data.id);
      expect(
        (
          await downloaded(
            page,
            panel.getByRole("button", {
              name: "Export exact native write receipt",
              exact: true,
            }),
          )
        ).equals(applied.raw),
      ).toBe(true);
      const stats = await server.command("stats");
      expect(stats.writes).toBe(1);
      expect(stats.days[0]).toBe(expectedDay(text, true));
      expect(new Set(stats.days.slice(1))).toEqual(
        new Set(["0eb40800000074006f6c640f"]),
      );
      const reconciled = await capture(page, BASE + "/reconcile", async () => {
        await panel
          .getByRole("button", {
            name: "Read-only reconcile selected receipt",
            exact: true,
          })
          .click();
        await expect(
          panel.getByLabel("Native write reconciliation", { exact: true }),
        ).toContainText("Readback: match");
      });
      expect(reconciled.data.profile).toBe(STRING_WRITE);
      expect(reconciled.data.writes_sent).toBe(0);
      expect(
        (
          await downloaded(
            page,
            panel.getByRole("button", {
              name: "Export exact native reconciliation",
              exact: true,
            }),
          )
        ).equals(reconciled.raw),
      ).toBe(true);
      expect((await server.command("stats")).writes).toBe(1);
      const stored = await request.get(BASE + "/receipts/" + applied.data.id);
      expect((await stored.body()).equals(applied.raw)).toBe(true);
    } finally {
      await server.close();
    }
  });

test("empty, literal null, explicit NativeNull and empty String days retain separate authority", async ({
  page,
  request,
}) => {
  const { server, library } = await setup(page, request);
  try {
    for (const text of ["", "null"]) {
      await fillString(library, text);
      const result = await review(page, library);
      expect(result.data.profile).toBe(STRING_DRAFT);
      expect(result.data.new.transitions[0].native_type).toBe(
        "CharacterString",
      );
      expect(result.data.new.transitions[0].wire_value_text).toBe(text);
      expect(result.data.new.encoded_hex).toBe(expectedDay(text));
    }
    await library
      .getByLabel("Transition 1 native type", { exact: true })
      .selectOption("Null");
    const nullDay = await review(page, library);
    expect(nullDay.data.profile).toBe(STRING_DRAFT);
    expect(nullDay.data.new.encoded_hex).toBe("0eb408000000000f");
    await library
      .getByRole("button", { name: "Remove transition 1", exact: true })
      .click();
    const emptyDay = await review(page, library);
    expect(emptyDay.data.profile).toBe(STRING_DRAFT);
    expect(emptyDay.data.new.encoded_hex).toBe("0e0f");
    const panel = await openWrite(page),
      plan = await preview(page, panel);
    expect(plan.data.profile).toBe(STRING_WRITE);
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    await server.close();
  }
});

test("JSON string editing preserves256wire bytes and refuses overflow, malformed JSON and lone surrogates before a request", async ({
  page,
  request,
}) => {
  const { server, library } = await setup(page, request);
  try {
    for (const text of ["\0".repeat(256), "🌡".repeat(64)]) {
      await fillString(library, text);
      const result = await review(page, library);
      expect(result.data.request.transitions[0].value_text).toBe(text);
      expect(result.data.new.encoded_hex).toBe(expectedDay(text));
    }
    let requests = 0;
    page.on("request", (r) => {
      if (r.url().endsWith(LIB + "/drafts/review")) requests++;
    });
    for (const invalid of [
      '"\\ud800"',
      '"\\udfff"',
      "null",
      '{"text":"x"}',
      '"unfinished',
      JSON.stringify("🌡".repeat(65)),
    ]) {
      const editor = library.getByLabel(
        "Transition 1 CharacterString JSON literal",
        { exact: true },
      );
      await editor.fill(invalid);
      await expect(editor).toHaveValue(invalid);
      await library
        .getByRole("button", {
          name: "Review native weekly draft",
          exact: true,
        })
        .click();
      await expect(library.getByRole("alert")).toContainText(/CharacterString/);
      await expect(
        library.getByLabel("Native weekly draft review", { exact: true }),
      ).toHaveCount(0);
      expect(requests).toBe(0);
    }
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    await server.close();
  }
});

test("String draft guards reject forged legacy profile, unknown rules, changed wire text and changed native time", async ({
  page,
  request,
}) => {
  const { server, library } = await setup(page, request);
  try {
    await fillString(library, "new");
    const mutations = [
      (r: any) => {
        r.profile = r.format = "native-schedule-weekly-day-draft/1";
      },
      (r: any) => {
        r.rules_sha256 = "a".repeat(64);
      },
      (r: any) => {
        r.new.transitions[0].wire_value_text = "other";
      },
      (r: any) => {
        r.new.transitions[0].time = [9, 0, 0, 0];
      },
    ];
    for (const mutate of mutations) {
      await page.route("**" + LIB + "/drafts/review", async (route) => {
        const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
        const data = await response.json();
        mutate(data);
        await route.fulfill({ response, json: data });
      });
      await library
        .getByRole("button", {
          name: "Review native weekly draft",
          exact: true,
        })
        .click();
      await expect(library.getByRole("alert")).toContainText(
        "native weekly-day draft review",
      );
      await expect(
        library.getByLabel("Native weekly draft review", { exact: true }),
      ).toHaveCount(0);
      await page.unroute("**" + LIB + "/drafts/review");
    }
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    await server.close();
  }
});

test("fresh String preview rejects mixed legacy authority and source edits suppress a held actual plan", async ({
  page,
  request,
}) => {
  const { server, library } = await setup(page, request);
  let release = () => {};
  try {
    await fillString(library, "new");
    await review(page, library);
    const panel = await openWrite(page);
    for (const mutate of [
      (r: any) => {
        r.profile = "native-schedule-reviewed-weekly-day-write/1";
      },
      (r: any) => {
        r.rules_sha256 = "b".repeat(64);
      },
      (r: any) => {
        r.native_draft.request.draft_profile =
          "native-schedule-weekly-day-draft/1";
      },
    ]) {
      await page.route("**" + BASE + "/preview", async (route) => {
        const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
        const data = await response.json();
        mutate(data);
        await route.fulfill({ response, json: data });
      });
      await panel
        .getByRole("button", {
          name: "Preview fresh native weekly-day write",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText(
        "Fresh native preview",
      );
      await expect(
        panel.getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        }),
      ).toHaveCount(0);
      await page.unroute("**" + BASE + "/preview");
    }
    let entered = () => {};
    const held = new Promise<void>((r) => (entered = r)),
      released = new Promise<void>((r) => (release = r));
    await page.route("**" + BASE + "/preview", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      const body = await response.body();
      entered();
      await released;
      await route.fulfill({ response, body });
    });
    await panel
      .getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      })
      .click();
    await held;
    await fillString(library, "newer");
    release();
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Cancel active native operation",
        exact: true,
      }),
    ).toHaveCount(0);
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    release();
    await server.close();
  }
});

const legacy = [
  ["Null", "4480000000", "null"],
  ["Boolean", "11", "false"],
  ["Unsigned", "2102", "4294967295"],
  ["Integer", "31ff", "-2147483648"],
  ["Enumerated", "9102", "4294967295"],
  ["Real", "4480000000", "0.1"],
  ["Double", "55088000000000000000", "1e20"],
];
for (const [kind, atom, text] of legacy)
  test(`legacy ${kind} keeps originalv1 draft and fresh write profiles`, async ({
    page,
    request,
  }) => {
    const { server, library } = await setup(page, request, false, atom);
    try {
      if (kind === "Null")
        await library
          .getByLabel("Transition 1 native type", { exact: true })
          .selectOption("Null");
      else
        await library
          .getByLabel("Transition 1 exact value text", { exact: true })
          .fill(text);
      const reviewed = await review(page, library);
      expect(reviewed.data.profile).toBe("native-schedule-weekly-day-draft/1");
      expect(reviewed.data.rules_sha256).toBe(
        "3a69e8f5e2de0cc74e21af9db7a0b6607cb1a1388d1667a5c3cd66cc6d1aff6e",
      );
      expect(reviewed.data.request.draft_profile).toBeUndefined();
      const panel = await openWrite(page),
        prepared = await preview(page, panel);
      expect(prepared.data.profile).toBe(
        "native-schedule-reviewed-weekly-day-write/1",
      );
      expect(prepared.data.rules_sha256).toBe(
        "5fda23c9c4b5a9ac07b621fe90507fe3626a913ba3014778a938750ca28cf98c",
      );
      expect((await server.command("stats")).writes).toBe(0);
    } finally {
      await server.close();
    }
  });

test("a valid oversized String day remains exportable but has no480byte native Apply authority", async ({
  page,
  request,
}) => {
  const { server, library } = await setup(page, request);
  try {
    await fillString(library, "\0".repeat(256));
    await library
      .getByRole("button", { name: "Add daily transition", exact: true })
      .click();
    for (const [field, value] of [
      ["hour", "17"],
      ["minute", "0"],
      ["second", "0"],
      ["hundredth", "0"],
    ])
      await library
        .getByLabel(`Transition 2 ${field}`, { exact: true })
        .fill(value);
    await library
      .getByLabel("Transition 2 CharacterString JSON literal", { exact: true })
      .fill(JSON.stringify("\0".repeat(256)));
    const reviewed = await review(page, library);
    expect(reviewed.data.new.encoded_hex.length / 2).toBeGreaterThan(480);
    const downloadedBytes = { bytes: Buffer.alloc(0) };
    const exported = await capture(page, LIB + "/drafts/export", async () => {
      downloadedBytes.bytes = await downloaded(
        page,
        library.getByRole("button", {
          name: "Export exact reviewed weekly draft",
          exact: true,
        }),
      );
    });
    expect(downloadedBytes.bytes.equals(exported.raw)).toBe(true);
    const panel = await openWrite(page);
    await panel
      .getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Fresh native write review", { exact: true }),
    ).toContainText("480-byte");
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    await server.close();
  }
});

test("an unknown String writer rules capability clears active authority without changing the draft", async ({
  page,
  request,
}) => {
  const { server, library } = await setup(page, request);
  try {
    await fillString(library, "new");
    await review(page, library);
    const panel = await openWrite(page);
    await preview(page, panel);
    await page.route("**" + BASE + "/profile", async (route) => {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0 });
      const data = await response.json();
      data.string_profile.rules_sha256 = "c".repeat(64);
      await route.fulfill({ response, json: data });
    });
    await panel
      .getByRole("button", {
        name: "Refresh native write journal",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "Native write profile",
    );
    await expect(
      panel.getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      library.getByLabel("Native weekly draft review", { exact: true }),
    ).toBeVisible();
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    await server.close();
  }
});
