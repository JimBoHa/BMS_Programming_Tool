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
async function peer(routed: boolean) {
  const child = spawn(
    python,
    ["-u", "-c", peerSource, routed ? "routed" : "direct"],
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
async function setup(
  page: Page,
  request: APIRequestContext,
  routed = false,
  negativeZero = false,
) {
  const server = await peer(routed);
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
    const response = await request.post("/api/bacnet/schedules/read", {
      headers: auth,
      data: server.options,
    });
    expect(response.ok()).toBe(true);
    const report = await response.json();
    expect(report.complete).toBe(true);
    const saved = await request.post("/api/bacnet/schedules/library/save", {
      headers: auth,
      data: { id: report.id },
    });
    expect(saved.ok()).toBe(true);
    const capture = await saved.json();
    await page.goto("/");
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Read native schedules", exact: true }),
    ).toBeEnabled();
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
    await library
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill(negativeZero ? "-0.0" : "2.5");
    if (negativeZero) {
      await library
        .getByRole("button", { name: "Add daily transition", exact: true })
        .click();
      for (const [field, value] of [
        ["hour", "17"],
        ["minute", "30"],
        ["second", "0"],
        ["hundredth", "0"],
      ])
        await library
          .getByLabel(`Transition 2 ${field}`, { exact: true })
          .fill(value);
      await library
        .getByLabel("Transition 2 native type", { exact: true })
        .selectOption("Null");
    }
    await library
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await expect(
      library.getByLabel("Native weekly draft review", { exact: true }),
    ).toBeVisible();
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
      .fill("Authored UI Operator");
    await panel
      .getByLabel("Native write rationale", { exact: true })
      .fill("Authored loopback day review");
    await expect(
      panel.getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      }),
    ).toBeEnabled();
    return { server, library, panel, capture };
  } catch (failure) {
    await server.close();
    throw failure;
  }
}
async function preview(panel: ReturnType<Page["getByRole"]>) {
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
}
async function download(page: Page, button: ReturnType<Page["getByRole"]>) {
  const pending = page.waitForEvent("download");
  await button.click();
  return readFileSync((await (await pending).path())!);
}
function verify(raw: Buffer, receiptId?: string) {
  execFileSync(
    python,
    [
      "-c",
      `import hashlib,json,sys
r=json.load(sys.stdin)
assert r['evidence_sha256']==hashlib.sha256(json.dumps({k:v for k,v in r.items() if k!='evidence_sha256'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
if sys.argv[1]:assert r['id']==sys.argv[1]
`,
      receiptId || "",
    ],
    { cwd: root, input: raw },
  );
}

for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} GUI applies one native day and exports exact signed-zero receipt and separate read-only reconciliation`, async ({
    page,
    request,
  }) => {
    const { server, panel } = await setup(page, request, routed, true);
    try {
      await preview(panel);
      expect((await server.command("stats")).writes).toBe(0);
      await panel
        .getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        })
        .click();
      const receipt = panel.getByLabel("Native write receipt", { exact: true });
      await expect(receipt).toContainText("accepted");
      await expect(receipt).toContainText("match");
      const raw = await download(
        page,
        receipt.getByRole("button", {
          name: "Export exact native write receipt",
          exact: true,
        }),
      );
      const body = JSON.parse(raw.toString());
      verify(raw, body.id);
      expect(body.protocol_status).toBe("accepted");
      expect(body.review.native_draft.new.transitions[0].wire_value_text).toBe(
        "-0.0",
      );
      expect(raw.includes(Buffer.from('"value":-0.0'))).toBe(true);
      const stats = await server.command("stats");
      expect(stats.writes).toBe(1);
      expect(stats.days[0]).toBe("0eb4080000004480000000b4111e0000000f");
      expect(new Set(stats.days.slice(1)).size).toBe(1);
      await receipt
        .getByRole("button", {
          name: "Read-only reconcile selected receipt",
          exact: true,
        })
        .click();
      const observation = panel.getByLabel("Native write reconciliation", {
        exact: true,
      });
      await expect(observation).toContainText("Readback: match");
      const observed = await download(
        page,
        observation.getByRole("button", {
          name: "Export exact native reconciliation",
          exact: true,
        }),
      );
      verify(observed);
      expect(JSON.parse(observed.toString()).writes_sent).toBe(0);
      expect((await server.command("stats")).writes).toBe(1);
      expect(
        await (await request.get(BASE + "/receipts/" + body.id)).body(),
      ).toEqual(raw);
      await disconnect(request);
      const before = await server.command("stats");
      await page.reload();
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      const reopened = page.getByRole("region", {
        name: "Native weekly-day deployment",
        exact: true,
      });
      await reopened
        .getByRole("button", {
          name: "Open native deployment and local history",
          exact: true,
        })
        .click();
      await reopened
        .getByRole("button", {
          name: `Open native receipt ${body.id.slice(0, 12)}`,
          exact: true,
        })
        .click();
      await expect(
        reopened.getByRole("button", {
          name: "Read-only reconcile selected receipt",
          exact: true,
        }),
      ).toBeDisabled();
      expect(
        await download(
          page,
          reopened.getByRole("button", {
            name: "Export exact native write receipt",
            exact: true,
          }),
        ),
      ).toEqual(raw);
      expect(await server.command("stats")).toEqual(before);
    } finally {
      await server.close();
    }
  });

for (const mode of ["drop", "error"])
  test(`native ${mode} keeps possible application, protocol and observed readback separate without retry`, async ({
    page,
    request,
  }) => {
    const { server, panel } = await setup(page, request);
    try {
      await preview(panel);
      await server.command("mode", mode);
      await panel
        .getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        })
        .click();
      const receipt = panel.getByLabel("Native write receipt", { exact: true });
      await expect(receipt).toContainText("May have applied");
      await expect(receipt).toContainText(
        mode === "drop" ? "unknown" : "rejected",
      );
      await expect(receipt).toContainText("match");
      if (mode === "error") await expect(receipt).toContainText("ErrorCode:");
      const raw = await download(
        page,
        receipt.getByRole("button", {
          name: "Export exact native write receipt",
          exact: true,
        }),
      );
      verify(raw);
      const body = JSON.parse(raw.toString());
      expect(body.may_have_applied).toBe(true);
      expect(body.protocol_status).toBe(
        mode === "drop" ? "unknown" : "rejected",
      );
      await page.waitForTimeout(150);
      expect((await server.command("stats")).writes).toBe(1);
      await expect(
        panel.getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      await server.close();
    }
  });

test("source edits suppress held real preview and Apply authority while preserving the actual journal receipt", async ({
  page,
  request,
}) => {
  const { server, library, panel } = await setup(page, request);
  try {
    let seen!: () => void, release!: () => void, done!: () => void;
    const entered = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      delivered = new Promise<void>((r) => (done = r));
    await page.route(
      "**/api/bacnet/schedules/writes/preview",
      async (route) => {
        const response = await route.fetch();
        seen();
        await gate;
        try {
          await route.fulfill({ response, body: await response.body() });
        } finally {
          done();
        }
      },
    );
    await panel
      .getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      })
      .click();
    await entered;
    await library
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill("3.5");
    release();
    await delivered;
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    expect((await server.command("stats")).writes).toBe(0);
    await page.unroute("**/api/bacnet/schedules/writes/preview");
    await library
      .getByRole("button", { name: "Review native weekly draft", exact: true })
      .click();
    await preview(panel);
    let applied!: () => void,
      send!: () => void,
      finished!: () => void,
      id = "";
    const committed = new Promise<void>((r) => (applied = r)),
      responseGate = new Promise<void>((r) => (send = r)),
      complete = new Promise<void>((r) => (finished = r));
    await page.route("**/api/bacnet/schedules/writes/apply", async (route) => {
      const response = await route.fetch();
      id = (await response.json()).id;
      applied();
      await responseGate;
      try {
        await route.fulfill({ response, body: await response.body() });
      } finally {
        finished();
      }
    });
    await panel
      .getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      })
      .click();
    await committed;
    await library
      .getByLabel("Transition 1 exact value text", { exact: true })
      .fill("4.5");
    send();
    await complete;
    await expect(
      panel.getByLabel("Native write receipt", { exact: true }),
    ).toHaveCount(0);
    await expect(
      library.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("4.5");
    await panel
      .getByRole("button", {
        name: `Open native receipt ${id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Native write receipt", { exact: true }),
    ).toContainText("May have applied");
    expect((await server.command("stats")).writes).toBe(1);
  } finally {
    await server.close();
  }
});

test("malformed fresh responses cannot crash the editor or enable Apply", async ({
  page,
  request,
}) => {
  const { server, library, panel } = await setup(page, request);
  try {
    for (const change of ["new", "target", "operation"]) {
      await page.route(
        "**/api/bacnet/schedules/writes/preview",
        async (route) => {
          const response = await route.fetch(),
            body = await response.json();
          if (change === "new") delete body.native_draft.new;
          else if (change === "target") body.target.address = "192.0.2.77";
          else body.operation_id = "wrong_operation";
          await route.fulfill({ response, json: body });
        },
      );
      await panel
        .getByRole("button", {
          name: "Preview fresh native weekly-day write",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText("does not match");
      await expect(
        panel.getByRole("button", {
          name: "Apply one native weekly-day request",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(
        library.getByLabel("Transition 1 exact value text", { exact: true }),
      ).toHaveValue("2.5");
      await page.unroute("**/api/bacnet/schedules/writes/preview");
    }
    expect((await server.command("stats")).writes).toBe(0);
  } finally {
    await server.close();
  }
});

test("reopened actual durable intent displays unknown dispatch and protocol instead of its pre-send snapshot", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const { server, panel } = await setup(page, request);
  try {
    await preview(panel);
    await panel
      .getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      })
      .click();
    const raw = await download(
      page,
      panel.getByRole("button", {
        name: "Export exact native write receipt",
        exact: true,
      }),
    );
    const id = JSON.parse(raw.toString()).id;
    await disconnect(request);
    // Authored storage interruption: retain this operation's actual before-send
    // intent while removing only its completion row, never synthesize native data.
    execFileSync(
      python,
      [
        "-c",
        `import sys
from bms_tool.storage import Store
s=Store(sys.argv[1])
with s.connect() as db:
 row=db.execute('SELECT intent FROM native_weekly_writes WHERE id=?',(sys.argv[2],)).fetchone()
 assert row and row[0]
 db.execute('UPDATE native_weekly_writes SET result=NULL WHERE id=?',(sys.argv[2],))
`,
        nativeScheduleWriteServer.directory,
        id,
      ],
      { cwd: root },
    );
    const before = await server.command("stats");
    await page.reload();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    const reopened = page.getByRole("region", {
      name: "Native weekly-day deployment",
      exact: true,
    });
    await reopened
      .getByRole("button", {
        name: "Open native deployment and local history",
        exact: true,
      })
      .click();
    await reopened
      .getByRole("button", {
        name: `Open native receipt ${id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    const receipt = reopened.getByLabel("Native write receipt", {
      exact: true,
    });
    await expect(receipt).toContainText("Unresolved durable write intent");
    await expect(receipt).toContainText("Unknown after interrupted intent");
    await expect(receipt).toContainText("May have applied");
    const recovered = await download(
      page,
      receipt.getByRole("button", {
        name: "Export exact native write receipt",
        exact: true,
      }),
    );
    verify(recovered, id);
    const body = JSON.parse(recovered.toString());
    expect(body.dispatch_started).toBeNull();
    expect(body.protocol_accepted).toBeNull();
    expect(body.readback.status).toBe("unknown");
    expect(body.intent_snapshot.dispatch_started).toBe(false);
    expect(await server.command("stats")).toEqual(before);
  } finally {
    await server.close();
  }
});

test("the received native review expires in the GUI without an Apply POST or clock-reversal revival", async ({
  page,
  request,
}) => {
  const { server, panel } = await setup(page, request);
  try {
    await preview(panel);
    const raw = await download(
      page,
      panel.getByRole("button", {
        name: "Export exact native write preview",
        exact: true,
      }),
    );
    const prepared = JSON.parse(raw.toString()),
      calls: string[] = [];
    page.on("request", (value) => {
      if (value.url().endsWith(BASE + "/apply"))
        calls.push(value.postData() || "");
    });
    await page.clock.install();
    await page.clock.setSystemTime(
      new Date(Date.parse(prepared.expires_at) + 1000),
    );
    await page.clock.runFor(300);
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByLabel("Fresh native write review", { exact: true }),
    ).toContainText("expired. Preview again");
    await page.clock.setSystemTime(new Date(Date.parse(prepared.created_at)));
    await page.clock.runFor(300);
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toBeDisabled();
    expect(calls).toEqual([]);
    expect((await server.command("stats")).writes).toBe(0);
    expect(
      await download(
        page,
        panel.getByRole("button", {
          name: "Export exact native write preview",
          exact: true,
        }),
      ),
    ).toEqual(raw);
  } finally {
    await server.close();
  }
});

test("connection draft changes retire ready authority and explicit cancellation stops an owned native preview", async ({
  page,
  request,
}) => {
  const { server, panel, library } = await setup(page, request);
  try {
    await preview(panel);
    const input = page.getByLabel("Schedule source address", { exact: true }),
      original = await input.inputValue();
    await input.fill("192.0.2.77");
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    await input.fill(original);
    await server.command("hold");
    await panel
      .getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      })
      .click();
    await expect
      .poll(async () => (await server.command("stats")).entered, {
        intervals: [10, 20, 50],
      })
      .toBe(true);
    await panel
      .getByRole("button", {
        name: "Cancel active native operation",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("button", {
        name: "Preview fresh native weekly-day write",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      library.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("2.5");
    await server.command("release");
    expect((await server.command("stats")).writes).toBe(0);
    await page.route("**/api/bacnet/schedules/writes/profile", (route) =>
      route.fulfill({ json: { profile: "unsupported", journal: {} } }),
    );
    await panel
      .getByRole("button", {
        name: "Refresh native write journal",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "profile is malformed or unsupported",
    );
    await expect(
      library.getByLabel("Transition 1 exact value text", { exact: true }),
    ).toHaveValue("2.5");
  } finally {
    await server.command("release");
    await server.close();
  }
});

test("leaving during a held actual write response cannot display late authority or retry the dispatched request", async ({
  page,
  request,
}) => {
  const { server, panel } = await setup(page, request);
  let release = () => {};
  try {
    await preview(panel);
    let seen!: () => void,
      done!: () => void,
      id = "";
    const entered = new Promise<void>((r) => (seen = r)),
      gate = new Promise<void>((r) => (release = r)),
      delivered = new Promise<void>((r) => (done = r));
    await page.route("**/api/bacnet/schedules/writes/apply", async (route) => {
      const response = await route.fetch();
      id = (await response.json()).id;
      seen();
      await gate;
      try {
        await route.fulfill({ response, body: await response.body() });
      } finally {
        done();
      }
    });
    await panel
      .getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      })
      .click();
    await entered;
    await page.getByRole("button", { name: "Reference", exact: true }).click();
    release();
    await delivered;
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await panel
      .getByRole("button", {
        name: "Open native deployment and local history",
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Native write receipt", { exact: true }),
    ).toHaveCount(0);
    await panel
      .getByRole("button", {
        name: `Open native receipt ${id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Native write receipt", { exact: true }),
    ).toContainText("May have applied");
    expect((await server.command("stats")).writes).toBe(1);
  } finally {
    release();
    await server.close();
  }
});

test("a mismatched actual Apply reply stays unconfirmed until its original journal receipt is explicitly opened", async ({
  page,
  request,
}) => {
  const { server, panel } = await setup(page, request);
  try {
    await preview(panel);
    let id = "";
    await page.route("**/api/bacnet/schedules/writes/apply", async (route) => {
      const response = await route.fetch(),
        body = await response.json();
      id = body.id;
      body.operation_id = "not_the_admitted_operation";
      await route.fulfill({ response, json: body });
    });
    await panel
      .getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "Apply outcome is unconfirmed",
    );
    await expect(
      panel.getByLabel("Native write receipt", { exact: true }),
    ).toHaveCount(0);
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
    await panel
      .getByRole("button", {
        name: `Open native receipt ${id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    await expect(
      panel.getByLabel("Native write receipt", { exact: true }),
    ).toContainText("May have applied");
    const raw = await download(
      page,
      panel.getByRole("button", {
        name: "Export exact native write receipt",
        exact: true,
      }),
    );
    verify(raw, id);
    expect(JSON.parse(raw.toString()).operation_id).not.toBe(
      "not_the_admitted_operation",
    );
    expect((await server.command("stats")).writes).toBe(1);
  } finally {
    await server.close();
  }
});

test("explicit post-dispatch cancellation leaves one uncertain operation in the durable journal without retry", async ({
  page,
  request,
}) => {
  const { server, panel } = await setup(page, request);
  try {
    await preview(panel);
    await server.command("mode", "hold");
    let id = "",
      finished!: () => void;
    const complete = new Promise<void>((r) => (finished = r));
    await page.route("**/api/bacnet/schedules/writes/apply", async (route) => {
      const response = await route.fetch();
      id = (await response.json()).id;
      try {
        await route.fulfill({ response, body: await response.body() });
      } finally {
        finished();
      }
    });
    await panel
      .getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      })
      .click();
    await expect
      .poll(async () => (await server.command("stats")).writes, {
        intervals: [10, 20, 50],
      })
      .toBe(1);
    await panel
      .getByRole("button", {
        name: "Cancel active native operation",
        exact: true,
      })
      .click();
    await complete;
    await panel
      .getByRole("button", {
        name: `Open native receipt ${id.slice(0, 12)}`,
        exact: true,
      })
      .click();
    const receipt = panel.getByLabel("Native write receipt", { exact: true });
    await expect(receipt).toContainText("May have applied");
    await expect(receipt).toContainText("unknown");
    const raw = await download(
      page,
      receipt.getByRole("button", {
        name: "Export exact native write receipt",
        exact: true,
      }),
    );
    verify(raw, id);
    const body = JSON.parse(raw.toString());
    expect(body.dispatch_started).toBe(true);
    expect(body.may_have_applied).toBe(true);
    await page.waitForTimeout(150);
    expect((await server.command("stats")).writes).toBe(1);
    await expect(
      panel.getByRole("button", {
        name: "Apply one native weekly-day request",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    await server.close();
  }
});
