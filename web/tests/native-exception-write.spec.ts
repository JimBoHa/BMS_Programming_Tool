import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "./nativeScheduleWriteFixture";
import { exceptionControllerPeer } from "./exception-controller-peer";
import { chooseWorkspaceTask } from "./workspace-navigation";
import { readFileSync } from "node:fs";

const base = "/api/bacnet/schedule-exceptions/writes";
async function auth(request: APIRequestContext) {
  return {
    "X-Studio-Token": (await (await request.get("/api/session")).json()).token,
  };
}
test.afterEach(async ({ request }) => {
  expect(
    (
      await request.post("/api/bacnet/disconnect", {
        headers: await auth(request),
        data: {},
      })
    ).ok(),
  ).toBe(true);
});
async function select(page: Page, target: any, initial = true) {
  if (initial) {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
  } else
    await page
      .getByRole("button", { name: "Change controller", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Known controller address", exact: true })
    .click();
  for (const [name, value] of [
    ["Known controller address", target.address],
    ["Known Device object", target.device],
    ["Known router", target.router || ""],
    ["Known network", target.dnet == null ? "" : String(target.dnet)],
  ])
    await page.getByLabel(name, { exact: true }).fill(value);
  await page
    .getByRole("region", { name: "Known controller connection", exact: true })
    .getByRole("button", { name: "Open controller", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Controller overview", exact: true }),
  ).toContainText("Native " + target.device);
  await chooseWorkspaceTask(page, "Schedules");
}
async function setup(page: Page, request: APIRequestContext, routed = false) {
  const peer = await exceptionControllerPeer(routed),
    headers = await auth(request);
  try {
    expect(
      (
        await request.post("/api/bacnet/connect", {
          headers,
          data: { local_address: peer.local },
        })
      ).ok(),
    ).toBe(true);
    const response = await request.post("/api/bacnet/schedules/read", {
      headers,
      data: {
        ...peer.target,
        object_ids: ["schedule,1"],
        operation_id:
          "exception_capture_" + crypto.randomUUID().replaceAll("-", ""),
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
    const report = await response.json();
    expect(report.complete).toBe(true);
    const saved = await request.post("/api/bacnet/schedules/library/save", {
      headers,
      data: { id: report.id },
    });
    expect(saved.ok()).toBe(true);
    const capture = await saved.json();
    await select(page, peer.target);
    const library = page.getByRole("region", {
      name: "Native Schedule capture library",
      exact: true,
    });
    await library
      .getByRole("button", {
        name: "Open capture " + capture.id.slice(0, 12),
        exact: true,
      })
      .click();
    const details = library.getByLabel("Captured Schedule exceptions", {
      exact: true,
    });
    if (!(await details.evaluate((node) => (node as HTMLDetailsElement).open)))
      await details.locator("summary").click();
    const editor = page.getByRole("region", {
      name: "Captured Schedule exception editor",
      exact: true,
    });
    await expect(
      editor.getByLabel("Captured Schedule for exceptions", { exact: true }),
    ).toHaveValue("schedule,1");
    await editor
      .getByLabel("Exception date year", { exact: true })
      .fill("2026");
    await editor
      .getByLabel("Exception date month", { exact: true })
      .selectOption("11");
    await editor
      .getByLabel("Exception date day", { exact: true })
      .selectOption("2");
    await editor
      .getByLabel("Exception date weekday", { exact: true })
      .selectOption("1");
    await editor
      .getByRole("button", { name: "Review exception draft", exact: true })
      .click();
    await expect(
      editor.getByLabel("Native exception draft review", { exact: true }),
    ).toBeVisible();
    const panel = editor.getByRole("region", {
      name: "Exception controller deployment",
      exact: true,
    });
    await panel
      .getByRole("button", {
        name: "Open exception deployment and receipts",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("table", {
        name: "Exception transfer journal",
        exact: true,
      }),
    ).toBeVisible();
    await panel
      .getByLabel("Declared Exception operator", { exact: true })
      .fill("Authored operator");
    await panel
      .getByLabel("Exception change rationale", { exact: true })
      .fill("Authored Exception replacement");
    return { peer, capture, editor, panel, headers };
  } catch (e) {
    await peer.close();
    throw e;
  }
}
async function preview(panel: ReturnType<Page["getByRole"]>) {
  await panel
    .getByRole("button", {
      name: "Review Exception controller change",
      exact: true,
    })
    .click();
  await expect(
    panel.getByRole("button", {
      name: "Apply Schedule exceptions",
      exact: true,
    }),
  ).toBeEnabled();
}
for (const routed of [false, true])
  test(`${routed ? "routed" : "direct"} Exception replacement sends exact dates once and keeps immutable receipts`, async ({
    page,
    request,
  }, info) => {
    const { peer, panel, editor, capture } = await setup(page, request, routed);
    try {
      await preview(panel);
      await panel
        .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
        .click();
      const receipt = panel.getByRole("region", {
        name: "Exception transfer receipt",
        exact: true,
      });
      await expect(receipt).toContainText(
        "Reviewed exceptions and other static Schedule fields matched at readback",
      );
      const id = (await receipt.textContent())!.match(
        /Receipt ([a-f0-9]{32})/,
      )![1];
      const original = await (
        await request.get(base + "/receipts/" + id)
      ).body();
      expect((await peer.stats()).values).toEqual([
        "0e0c7e0b02010f2eb4091e000044400000002f39081c018000022eb4091e000044400000002f3908",
      ]);
      await receipt
        .getByRole("button", {
          name: "Read back Exception receipt",
          exact: true,
        })
        .click();
      await expect(
        panel.getByRole("region", {
          name: "Exception receipt readback",
          exact: true,
        }),
      ).toContainText("Writes sent: 0.");
      const download = page.waitForEvent("download");
      await receipt
        .getByRole("button", { name: "Save Exception receipt", exact: true })
        .click();
      expect(readFileSync((await (await download).path())!)).toEqual(original);
      expect(
        await (await request.get(base + "/receipts/" + id)).body(),
      ).toEqual(original);
      expect((await peer.stats()).writes).toBe(1);
      await page.setViewportSize({ width: routed ? 390 : 1440, height: 1000 });
      await panel.scrollIntoViewIfNeeded();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: info.outputPath("calendar-deployment.png"),
        fullPage: true,
      });
      // Local source and unfinished text remain useful after a completed field action.
      await editor
        .getByLabel("Exception date year", { exact: true })
        .fill("20");
      await chooseWorkspaceTask(page, "Overview");
      await chooseWorkspaceTask(page, "Schedules");
      await page
        .getByRole("region", {
          name: "Native Schedule capture library",
          exact: true,
        })
        .getByRole("button", {
          name: "Open capture " + capture.id.slice(0, 12),
          exact: true,
        })
        .click();
      await expect(
        editor.getByLabel("Exception date year", { exact: true }),
      ).toHaveValue("20");
      await expect(
        editor.getByRole("button", {
          name: "Apply Schedule exceptions",
          exact: true,
        }),
      ).toHaveCount(0);
    } finally {
      await peer.close();
    }
  });

for (const mode of ["drop", "error", "reject"])
  test(`Exception ${mode} keeps protocol outcome separate from observed dates without retry`, async ({
    page,
    request,
  }) => {
    const { peer, panel } = await setup(page, request);
    try {
      await preview(panel);
      await peer.mode(mode);
      await panel
        .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
        .click();
      const receipt = panel.getByRole("region", {
        name: "Exception transfer receipt",
        exact: true,
      });
      await expect(receipt).toBeVisible();
      await expect(receipt.locator("dd")).toHaveText([
        "One dispatch admitted",
        mode === "drop" ? "Unknown" : "Rejected",
        mode === "reject" ? "mismatch" : "match",
      ]);
      const id = (await receipt.textContent())!.match(
        /Receipt ([a-f0-9]{32})/,
      )![1];
      const original = await (
        await request.get(base + "/receipts/" + id)
      ).body();
      const data = JSON.parse(original.toString());
      expect(data.protocol_accepted).toBe(mode === "drop" ? null : false);
      await receipt
        .getByRole("button", {
          name: "Read back Exception receipt",
          exact: true,
        })
        .click();
      await expect(
        panel.getByRole("region", {
          name: "Exception receipt readback",
          exact: true,
        }),
      ).toContainText("Writes sent: 0.");
      expect((await peer.stats()).writes).toBe(1);
      expect(
        await (await request.get(base + "/receipts/" + id)).body(),
      ).toEqual(original);
    } finally {
      await peer.close();
    }
  });

for (const changed of ["operation", "rules", "target", "request"])
  test(`a substituted Exception preview ${changed} cannot authorize Apply`, async ({
    page,
    request,
  }) => {
    const { peer, panel } = await setup(page, request);
    try {
      await page.route(
        "**/schedule-exceptions/writes/preview",
        async (route) => {
          const response = await route.fetch({ maxRetries: 0 }),
            data = await response.json();
          expect(data.can_apply).toBe(true);
          if (changed === "operation")
            data.operation_id = "another_exception_preview";
          if (changed === "rules") data.rules_sha256 = "0".repeat(64);
          if (changed === "target") data.target.address = "127.0.0.1:1";
          if (changed === "request")
            data.request_service_body_hex =
              data.request_service_body_hex.replace("7e0b0201", "7e0b0302");
          await route.fulfill({ response, json: data });
        },
      );
      await panel
        .getByRole("button", {
          name: "Review Exception controller change",
          exact: true,
        })
        .click();
      await expect(panel.getByRole("alert")).toContainText("Schedule exception review");
      await expect(
        panel.getByRole("button", {
          name: "Apply Schedule exceptions",
          exact: true,
        }),
      ).toHaveCount(0);
      expect((await peer.stats()).writes).toBe(0);
    } finally {
      await peer.close();
    }
  });

test("a substituted Exception Apply operation keeps local dates and the real journal receipt", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  try {
    let original: any;
    await page.route("**/schedule-exceptions/writes/apply", async (route) => {
      const response = await route.fetch({ maxRetries: 0 });
      original = await response.json();
      expect(original.readback.status).toBe("match");
      await route.fulfill({
        response,
        json: { ...original, operation_id: "another_exception_apply" },
      });
    });
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toContainText(
      "Apply outcome is unconfirmed",
    );
    await expect(
      panel.getByRole("region", {
        name: "Exception transfer receipt",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      editor.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("2026");
    await panel
      .getByRole("button", {
        name: "Open Exception receipt " + original.id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Exception transfer receipt",
        exact: true,
      }),
    ).toContainText("matched at readback");
    expect((await peer.stats()).writes).toBe(1);
  } finally {
    await peer.close();
  }
});

test("Exception target changes preserve the local draft while blocking foreign deployment and receipt readback", async ({
  page,
  request,
}) => {
  const { peer, panel, editor, capture } = await setup(page, request),
    other = await exceptionControllerPeer();
  try {
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "Exception transfer receipt",
      exact: true,
    });
    await expect(receipt).toContainText("matched at readback");
    const id = (await receipt.textContent())!.match(
      /Receipt ([a-f0-9]{32})/,
    )![1];
    await select(page, other.target, false);
    await page
      .getByRole("region", {
        name: "Native Schedule capture library",
        exact: true,
      })
      .getByRole("button", {
        name: "Open capture " + capture.id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      editor.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("2026");
    await editor
      .getByRole("button", { name: "Review exception draft", exact: true })
      .click();
    await panel
      .getByRole("button", {
        name: "Open exception deployment and receipts",
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("table", {
        name: "Exception transfer journal",
        exact: true,
      }),
    ).toBeVisible();
    await panel
      .getByLabel("Declared Exception operator", { exact: true })
      .fill("Authored operator");
    await panel
      .getByLabel("Exception change rationale", { exact: true })
      .fill("Foreign source qualification");
    await expect(
      panel.getByRole("button", {
        name: "Review Exception controller change",
        exact: true,
      }),
    ).toBeDisabled();
    await panel
      .getByRole("button", {
        name: "Open Exception receipt " + id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      panel.getByRole("button", {
        name: "Read back Exception receipt",
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      panel.getByRole("button", {
        name: "Save Exception receipt",
        exact: true,
      }),
    ).toBeEnabled();
    expect((await peer.stats()).writes).toBe(1);
    expect((await other.stats()).writes).toBe(0);
  } finally {
    await peer.close();
    await other.close();
  }
});

test("a held Exception preview cannot revive after local priority A to B to A", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  let release = () => {};
  try {
    let arrived!: () => void, finished!: () => void;
    const held = new Promise<void>((resolve) => {
        arrived = resolve;
      }),
      gate = new Promise<void>((resolve) => {
        release = resolve;
      }),
      delivered = new Promise<void>((resolve) => {
        finished = resolve;
      });
    await page.route(
      "**/schedule-exceptions/writes/preview",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        expect((await response.json()).can_apply).toBe(true);
        arrived();
        await gate;
        await route.fulfill({ response });
        finished();
      },
      { times: 1 },
    );
    await panel
      .getByRole("button", {
        name: "Review Exception controller change",
        exact: true,
      })
      .click();
    await held;
    for (const priority of ["9", "8"]) {
      await editor
        .getByLabel("Exception event priority", { exact: true })
        .fill(priority);
      await editor
        .getByRole("button", { name: "Review exception draft", exact: true })
        .click();
      await expect(
        editor.getByLabel("Native exception draft review", { exact: true }),
      ).toBeVisible();
    }
    release();
    await delivered;
    await expect(
      panel.getByRole("button", {
        name: "Review Exception controller change",
        exact: true,
      }),
    ).toBeEnabled();
    await expect(
      panel.getByRole("button", {
        name: "Apply Schedule exceptions",
        exact: true,
      }),
    ).toHaveCount(0);
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    release();
    await peer.close();
  }
});

test("Exception visibility retirement keeps local date text and requires a new field review", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  try {
    await preview(panel);
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await expect(
      panel.getByRole("button", {
        name: "Apply Schedule exceptions",
        exact: true,
      }),
    ).toHaveCount(0);
    await editor
      .getByRole("button", {
        name: "Refresh captured exception sources",
        exact: true,
      })
      .click();
    await expect(
      editor.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("2026");
    await expect(
      panel.getByRole("button", {
        name: "Review Exception controller change",
        exact: true,
      }),
    ).toBeDisabled();
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    await peer.close();
  }
});

test("Exception review expiry stays retired after a client clock rewind", async ({
  page,
  request,
}) => {
  const initial = Date.now();
  await page.clock.install({ time: initial });
  const { peer, panel } = await setup(page, request);
  try {
    await preview(panel);
    await page.clock.runFor(60000);
    await expect(
      panel.getByRole("button", {
        name: "Apply Schedule exceptions",
        exact: true,
      }),
    ).toBeDisabled();
    await page.clock.setSystemTime(initial);
    await expect(
      panel.getByRole("button", {
        name: "Apply Schedule exceptions",
        exact: true,
      }),
    ).toBeDisabled();
    expect((await peer.stats()).writes).toBe(0);
  } finally {
    await peer.close();
  }
});

test("an interrupted Exception intent remains unknown and supports separate explicit readback", async ({
  page,
  request,
  nativeScheduleWriteServer,
}) => {
  const { peer, panel } = await setup(page, request);
  try {
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
      .click();
    const receipt = panel.getByRole("region", {
      name: "Exception transfer receipt",
      exact: true,
    });
    await expect(receipt).toContainText("matched at readback");
    const id = (await receipt.textContent())!.match(
      /Receipt ([a-f0-9]{32})/,
    )![1];
    const { execFileSync } = await import("node:child_process"),
      { default: path } = await import("node:path");
    execFileSync(path.join(path.resolve(".."), ".venv/bin/python"), [
      "-c",
      "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]+'/studio.sqlite3'); db.execute('UPDATE native_exception_writes SET result=NULL WHERE id=?',(sys.argv[2],)); db.commit(); db.close()",
      nativeScheduleWriteServer.directory,
      id,
    ]);
    await panel
      .getByRole("button", { name: "Refresh Exception receipts", exact: true })
      .click();
    await panel
      .getByRole("button", {
        name: "Open Exception receipt " + id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(receipt).toContainText("Unresolved durable Exception intent");
    await expect(receipt.locator("dd")).toHaveText([
      "Unknown after interrupted intent",
      "Unknown",
      "unknown",
    ]);
    const original = await (await request.get(base + "/receipts/" + id)).body();
    await receipt
      .getByRole("button", { name: "Read back Exception receipt", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Exception receipt readback",
        exact: true,
      }),
    ).toContainText("Writes sent: 0.");
    expect(await (await request.get(base + "/receipts/" + id)).body()).toEqual(
      original,
    );
    expect((await peer.stats()).writes).toBe(1);
  } finally {
    await peer.close();
  }
});

test("late exception Apply keeps newer unfinished text and exposes its original receipt", async ({
  page,
  request,
}) => {
  const { peer, panel, editor } = await setup(page, request);
  let release = () => {};
  try {
    let arrived!: () => void,
      finished!: () => void,
      receiptId = "";
    const held = new Promise<void>((resolve) => {
        arrived = resolve;
      }),
      gate = new Promise<void>((resolve) => {
        release = resolve;
      }),
      delivered = new Promise<void>((resolve) => {
        finished = resolve;
      });
    await page.route(
      "**/schedule-exceptions/writes/apply",
      async (route) => {
        const response = await route.fetch({ maxRetries: 0 });
        const data = await response.json();
        expect(data.readback.status).toBe("match");
        receiptId = data.id;
        arrived();
        await gate;
        await route.fulfill({ response });
        finished();
      },
      { times: 1 },
    );
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
      .click();
    await held;
    await editor.getByLabel("Exception date year", { exact: true }).fill("20");
    release();
    await delivered;
    await expect(
      editor.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("20");
    await expect(
      panel.getByRole("region", {
        name: "Exception transfer receipt",
        exact: true,
      }),
    ).toHaveCount(0);
    await panel
      .getByRole("button", { name: "Refresh Exception receipts", exact: true })
      .click();
    await panel
      .getByRole("button", {
        name: "Open Exception receipt " + receiptId.slice(0, 12),
        exact: true,
      })
      .click();
    const original = await (
      await request.get(base + "/receipts/" + receiptId)
    ).body();
    await panel
      .getByRole("button", { name: "Read back Exception receipt", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Exception receipt readback",
        exact: true,
      }),
    ).toContainText("Writes sent: 0.");
    await expect(
      editor.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("20");
    expect(
      await (await request.get(base + "/receipts/" + receiptId)).body(),
    ).toEqual(original);
    expect((await peer.stats()).writes).toBe(1);
  } finally {
    release();
    await peer.close();
  }
});

test("CAF entry preserves the exception source and retires field review through workspace navigation", async ({
  page,
  request,
}) => {
  const { peer, panel, capture, editor } = await setup(page, request);
  try {
    const { execFileSync } = await import("node:child_process"),
      { default: path } = await import("node:path");
    const root = path.resolve("..");
    const buffer = execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "from tests.test_caf_graph import make_graph; import sys; sys.stdout.buffer.write(make_graph())",
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [path.join(root, "backend"), root].join(path.delimiter),
        },
      },
    );
    await preview(panel);
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "exception-work.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
    await chooseWorkspaceTask(page, "Schedules");
    const library = page.getByRole("region", {
      name: "Native Schedule capture library",
      exact: true,
    });
    await library
      .getByRole("button", {
        name: "Open capture " + capture.id.slice(0, 12),
        exact: true,
      })
      .click();
    await expect(
      editor.getByLabel("Exception date year", { exact: true }),
    ).toHaveValue("2026");
    await expect(
      panel.getByRole("button", {
        name: "Apply Schedule exceptions",
        exact: true,
      }),
    ).toHaveCount(0);
    await editor
      .getByRole("button", { name: "Review exception draft", exact: true })
      .click();
    await expect(
      editor.getByLabel("Native exception draft review", { exact: true }),
    ).toBeVisible();
    await panel
      .getByRole("button", {
        name: "Open exception deployment and receipts",
        exact: true,
      })
      .click();
    await panel
      .getByLabel("Declared Exception operator", { exact: true })
      .fill("Authored operator");
    await panel
      .getByLabel("Exception change rationale", { exact: true })
      .fill("CAF entry keeps the captured target");
    await preview(panel);
    await panel
      .getByRole("button", { name: "Apply Schedule exceptions", exact: true })
      .click();
    await expect(
      panel.getByRole("region", {
        name: "Exception transfer receipt",
        exact: true,
      }),
    ).toContainText("matched at readback");
    expect((await peer.stats()).writes).toBe(1);
  } finally {
    await peer.close();
  }
});
