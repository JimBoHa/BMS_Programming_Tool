import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { createSocket } from "node:dgram";
import path from "node:path";

const root = path.resolve(".."),
  python = path.join(root, ".venv/bin/python");
function checkPython(code: string, value: unknown) {
  return execFileSync(python, ["-c", code], {
    cwd: root,
    input: JSON.stringify(value),
    encoding: "utf8",
  });
}
async function freePort(): Promise<number> {
  const socket = createSocket("udp4");
  return new Promise((resolve, reject) => {
    socket.once("error", reject);
    socket.bind(0, "127.0.0.1", () => {
      const address = socket.address();
      const port = typeof address === "string" ? 0 : address.port;
      socket.close(() => resolve(port));
    });
  });
}
async function peer() {
  const child = spawn(
    python,
    [
      "-u",
      "-c",
      `import asyncio,json,sys
from tests.test_connections import application,point,free_udp
from tests.test_bacnet_commands import binary
async def main():
    port=free_udp(); app=application(port,4190098); analog=point(); discrete=binary(); app.add_object(analog); app.add_object(discrete)
    counts={'reads':0,'writes':0}; read=app.do_ReadPropertyRequest; write=app.do_WritePropertyRequest
    async def read_counted(request):
        counts['reads']+=1
        await read(request)
    async def write_counted(request):
        counts['writes']+=1
        await write(request)
    app.do_ReadPropertyRequest=read_counted; app.do_WritePropertyRequest=write_counted
    print(json.dumps({'port':port}),flush=True)
    try:
        while True:
            command=(await asyncio.to_thread(sys.stdin.readline)).strip()
            if command!='stats': break
            print(json.dumps({**counts,'analog':float(analog.presentValue),'binary':int(discrete.presentValue)}),flush=True)
    finally:
        app.close(); await asyncio.sleep(.05)
asyncio.run(main())`,
    ],
    { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
  );
  let buffer = "",
    error = "";
  const queued: string[] = [],
    waiting: ((text: string) => void)[] = [];
  child.stdout.on("data", (data) => {
    buffer += data.toString();
    while (buffer.includes("\n")) {
      const index = buffer.indexOf("\n"),
        line = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      const receiver = waiting.shift();
      if (receiver) receiver(line);
      else queued.push(line);
    }
  });
  child.stderr.on("data", (data) => {
    error += data.toString();
  });
  const next = () =>
    new Promise<any>((resolve, reject) => {
      const line = queued.shift();
      if (line !== undefined) {
        resolve(JSON.parse(line));
        return;
      }
      const timer = setTimeout(
        () => reject(new Error("Isolated peer timeout: " + error)),
        5000,
      );
      waiting.push((text) => {
        clearTimeout(timer);
        resolve(JSON.parse(text));
      });
    });
  const ready = await next();
  return {
    child,
    port: ready.port,
    async stats() {
      child.stdin.write("stats\n");
      return next();
    },
  };
}
async function connect(page: Page, request: APIRequestContext, port: number) {
  await page.goto("/");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .getByLabel("Local bind address / UDP port", { exact: true })
    .fill(`127.0.0.1:${await freePort()}`);
  await page.getByLabel("Router IP (optional)", { exact: true }).fill("");
  await page
    .getByLabel("MS/TP destination network (optional)", { exact: true })
    .fill("");
  await page
    .getByLabel("BBMD address / UDP port (optional)", { exact: true })
    .fill("");
  await page
    .getByRole("button", { name: "Open interface", exact: true })
    .click();
  await expect(
    page.getByText("BACnet interface open", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Unicast target", { exact: true })
    .fill(`127.0.0.1:${port}`);
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
async function preview(page: Page, text: string) {
  await page.getByLabel("Command value", { exact: true }).fill(text);
  let received!: (row: { request: string; response: string }) => void;
  const captured = new Promise<{ request: string; response: string }>(
    (resolve) => (received = resolve),
  );
  await page.route("**/api/bacnet/write-plan", async (route) => {
    const response = await route.fetch(),
      raw = await response.text();
    expect(response.ok(), raw).toBe(true);
    // Keep the independently fetched server body before Chromium consumes the
    // page response as Blob; its CDP response body can then be unavailable.
    await route.fulfill({ response, body: raw });
    received({ request: route.request().postData()!, response: raw });
  });
  try {
    await page
      .getByRole("button", { name: "Preview command", exact: true })
      .click();
    const row = await captured;
    await expect(
      page.getByLabel("BACnet command preview", { exact: true }),
    ).toHaveText(row.response);
    return row;
  } finally {
    await page.unroute("**/api/bacnet/write-plan");
  }
}
async function close(
  request: APIRequestContext,
  headers: Record<string, string>,
  child: ReturnType<typeof spawn>,
) {
  await request.post("/api/bacnet/disconnect", { headers, data: {} });
  child.stdin?.end("close\n");
  child.kill();
}

test("unsafe numeric or nonscalar command intent refuses before any preview request or wire write", async ({
  page,
  request,
}) => {
  const device = await peer(),
    headers = await connect(page, request, device.port);
  const previews: string[] = [],
    writes: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/api/bacnet/write-plan"))
      previews.push(r.postData()!);
    if (r.url().endsWith("/api/bacnet/write-apply")) writes.push(r.postData()!);
  });
  try {
    for (const value of [
      "9007199254740993",
      "-9007199254740993",
      "1" + "0".repeat(400),
      "1e999",
      "-1e999",
      "NaN",
      "Infinity",
      "-Infinity",
      "01",
      "+1",
      ".5",
      "1e",
      "-",
      "null",
      "[]",
      "{}",
      '"unterminated',
      "true false",
    ]) {
      await page.getByLabel("Command value", { exact: true }).fill(value);
      await page
        .getByRole("button", { name: "Preview command", exact: true })
        .click();
      await expect(page.getByRole("alert")).toContainText("Command value");
      await expect(
        page.getByRole("button", { name: "Preview command", exact: true }),
      ).toBeEnabled();
      await expect(
        page.getByRole("button", {
          name: "Apply previewed command",
          exact: true,
        }),
      ).toHaveCount(0);
    }
    expect(previews).toEqual([]);
    expect(writes).toEqual([]);
    expect(await device.stats()).toEqual({
      reads: 0,
      writes: 0,
      analog: 12.5,
      binary: 0,
    });
  } finally {
    await close(request, headers, device.child);
  }
});

test("exact integer tokens and explicit native float rounding survive actual HTTP and raw preview text", async ({
  page,
  request,
}) => {
  const device = await peer(),
    headers = await connect(page, request, device.port);
  const rows: { token: string; request: string; response: string }[] = [];
  try {
    for (const token of [
      "9007199254740992",
      "1152921504606846976",
      "9007199254740994",
      "-1152921504606846976",
      "123.456789",
      "-0.0",
      "1.0",
      "1e-7",
      "9007199254740993.0",
    ])
      rows.push({ token, ...(await preview(page, token)) });
    checkPython(
      `import json,sys,math,struct
for row in json.load(sys.stdin):
    token=row['token']; expected=json.loads(token); request=json.loads(row['request']); response=json.loads(row['response'])
    assert type(request['value']) is type(expected), (token,request)
    assert request['value']==expected and response['requested_value']==expected, token
    assert type(response['requested_value']) is type(expected), token
    native=struct.unpack('!f',struct.pack('!f',expected))[0]
    assert response['value']==native, (token,response)
    if token=='-0.0': assert math.copysign(1,request['value'])==math.copysign(1,response['requested_value'])==math.copysign(1,response['value'])==-1
    if token=='1152921504606846976': assert request['value']==2**60 and str(request['value'])=='1152921504606846976'
    if token=='9007199254740994': assert response['requested_value']==2**53+2 and response['value']==2**53
`,
      rows,
    );
    const stats = await device.stats();
    expect(stats.reads).toBeGreaterThan(0);
    expect(stats.writes).toBe(0);
    expect(stats.analog).toBe(12.5);
    await page
      .getByLabel("Command value", { exact: true })
      .fill("9007199254740993");
    await expect(
      page.getByRole("button", {
        name: "Apply previewed command",
        exact: true,
      }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "Preview command", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText("not exactly");
  } finally {
    await close(request, headers, device.child);
  }
});

test("bare or quoted enum labels and Boolean commands retain owned apply and relinquish semantics", async ({
  page,
  request,
}) => {
  const device = await peer(),
    headers = await connect(page, request, device.port);
  try {
    await page
      .getByLabel("Object identifier", { exact: true })
      .fill("binary-value,1");
    for (const [input, expected, kind] of [
      ["active", 1, "str"],
      ['"inactive"', 0, "str"],
      ["true", 1, "bool"],
      ["false", 0, "bool"],
    ] as const) {
      const row = await preview(page, input);
      checkPython(
        `import json,sys
r=json.load(sys.stdin); q=json.loads(r['request']); p=json.loads(r['response']); assert type(q['value']).__name__==r['kind']; assert p['value']==r['expected']; assert p['requested_value']==q['value']`,
        { ...row, expected, kind },
      );
      await page
        .getByRole("button", { name: "Apply previewed command", exact: true })
        .click();
      await expect(page.locator(".owned-command")).toHaveCount(1);
      expect((await device.stats()).binary).toBe(expected);
      await page
        .getByRole("button", { name: "Relinquish", exact: true })
        .click();
      await expect(page.locator(".owned-command")).toHaveCount(0);
      expect((await device.stats()).binary).toBe(0);
    }
    expect((await device.stats()).writes).toBe(8);
  } finally {
    await close(request, headers, device.child);
  }
});

test("mismatched source or adjacent unrepresentable requested receipt never enables Apply", async ({
  page,
  request,
}) => {
  const device = await peer(),
    headers = await connect(page, request, device.port);
  try {
    for (const mode of ["requested", "target"]) {
      await page.route("**/api/bacnet/write-plan", async (route) => {
        const response = await route.fetch(),
          raw = await response.text();
        const body =
          mode === "requested"
            ? raw.replace(
                '"requested_value":1152921504606846976',
                '"requested_value":1152921504606846977',
              )
            : raw.replace(
                `"address":"127.0.0.1:${device.port}"`,
                '"address":"127.0.0.1:1"',
              );
        expect(body).not.toBe(raw);
        await route.fulfill({ response, body });
      });
      await page
        .getByLabel("Command value", { exact: true })
        .fill("1152921504606846976");
      await page
        .getByRole("button", { name: "Preview command", exact: true })
        .click();
      await expect(page.getByRole("alert")).toContainText("Command preview");
      await expect(
        page.getByRole("button", {
          name: "Apply previewed command",
          exact: true,
        }),
      ).toHaveCount(0);
      await page.unroute("**/api/bacnet/write-plan");
    }
    expect((await device.stats()).writes).toBe(0);
  } finally {
    await close(request, headers, device.child);
  }
});

test("delayed real preflight receipt after navigation cannot revive a command plan", async ({
  page,
  request,
}) => {
  const device = await peer(),
    headers = await connect(page, request, device.port);
  let release!: () => void, seen!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve)),
    arrived = new Promise<void>((resolve) => (seen = resolve));
  await page.route("**/api/bacnet/write-plan", async (route) => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    seen();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await page
      .getByRole("button", { name: "Preview command", exact: true })
      .click();
    await arrived;
    await page.getByRole("button", { name: "Program", exact: true }).click();
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Connections", exact: true }),
    ).toBeVisible();
    const settled = page.waitForResponse((r) =>
      r.url().endsWith("/api/bacnet/write-plan"),
    );
    release();
    await settled;
    await expect(
      page.getByRole("button", {
        name: "Apply previewed command",
        exact: true,
      }),
    ).toHaveCount(0);
    expect((await device.stats()).writes).toBe(0);
  } finally {
    release();
    await close(request, headers, device.child);
  }
});
