import { test, expect } from "./nativeScheduleWriteFixture";
import { nativeDefaultPeer } from "./native-default-peer";
import { freePort } from "./workflow-peer";

test("real IP status and guided route changes retain the bind and open each selected routed controller", async ({
  page,
  request,
}) => {
  const first = await nativeDefaultPeer(),
    second = await nativeDefaultPeer();
  const mutations: string[] = [];
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/(apply|write|command|release|capture|preview)$/.test(
        new URL(r.url()).pathname,
      )
    )
      mutations.push(r.url());
  });
  try {
    await page.goto("/");
    await page
      .getByRole("button", { name: /^Connect to a controller/ })
      .click();
    const local = `127.0.0.1:${await freePort()}`;
    await page
      .getByLabel("Local bind address / UDP port", { exact: true })
      .fill(local);
    const opened = page.waitForResponse((r) =>
      r.url().endsWith("/api/bacnet/connect"),
    );
    await page
      .getByRole("button", { name: "Open interface", exact: true })
      .click();
    expect((await opened).ok()).toBe(true);
    const initial = await (await request.get("/api/bacnet/status")).json();
    expect(initial.connected).toBe(true);
    expect(initial.config).not.toHaveProperty("transport");
    const token = (await (await request.get("/api/session")).json()).token;
    const rejected = await request.post("/api/bacnet/connect", {
      headers: { "X-Studio-Token": token },
      data: { ...initial.config, transport: "ip" },
    });
    expect(rejected.status()).toBe(422);
    expect(
      (await (await request.get("/api/bacnet/status")).json()).config,
    ).toEqual(initial.config);
    for (const [index, peer] of [first, second].entries()) {
      if (index)
        await page
          .getByRole("button", { name: "Change controller", exact: true })
          .click();
      await page
        .getByRole("button", { name: "Known controller address", exact: true })
        .click();
      for (const [label, value] of [
        ["Known controller address", "3001:7"],
        ["Known Device object", "device,5136"],
        ["Known router", peer.router],
        ["Known network", "3001"],
      ])
        await page.getByLabel(label, { exact: true }).fill(value);
      const switching = page.waitForResponse(
        (r) =>
          r.url().endsWith("/api/bacnet/connect") &&
          r.request().method() === "POST",
      );
      await page
        .getByRole("region", {
          name: "Known controller connection",
          exact: true,
        })
        .getByRole("button", { name: "Open controller", exact: true })
        .click();
      const response = await switching;
      expect(response.ok(), await response.text()).toBe(true);
      const body = response.request().postDataJSON();
      expect(body).not.toHaveProperty("transport");
      expect(body.local_address).toBe(local);
      expect(body.router).toBe(peer.router);
      expect(body.dnet).toBe(3001);
      await expect(
        page.getByRole("region", { name: "Controller overview", exact: true }),
      ).toContainText("Authored controller");
      await expect(
        page.getByLabel("Working context", { exact: true }),
      ).toContainText(peer.router);
      const status = await (await request.get("/api/bacnet/status")).json();
      expect(status.config.local_address).toBe(local);
      expect(status.config.router).toBe(peer.router);
      expect(status.config.dnet).toBe(3001);
      const stats = await peer.command("stats");
      expect(stats.router_errors).toEqual([]);
      expect(
        stats.request_types.some((type: string) =>
          /Write|Reinitialize/.test(type),
        ),
      ).toBe(false);
    }
    expect(mutations).toEqual([]);
  } finally {
    first.close();
    second.close();
    const token = (await (await request.get("/api/session")).json()).token;
    expect(
      (
        await request.post("/api/bacnet/disconnect", {
          headers: { "X-Studio-Token": token },
          data: {},
        })
      ).ok(),
    ).toBe(true);
  }
});
