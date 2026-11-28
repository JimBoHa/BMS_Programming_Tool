import { expect } from "@playwright/test";
import {
  snapshotFixture,
  openSnapshot,
} from "./native-snapshot-restore-browser-fixture";
import { chooseWorkspaceTask } from "./workspace-navigation";

snapshotFixture(true)(
  "hardware survey follows the selected sensor link and retires a stale value",
  async ({ page, snapshot }) => {
    const target = snapshot.seeded.target;
    const status = await (await page.request.get("/api/bacnet/status")).json();
    const id = "sensor-survey",
      survey = {
        id,
        profile: "bacnet-hardware-survey/1",
        target,
        identity: { name: "Authored controller" },
        inventory: {
          objects: ["627,7", "627,18"],
          read: 2,
          total: 2,
          complete: true,
        },
        inputs: [],
        modules: [],
        candidates: [],
        errors: [],
        warnings: [],
      };
    await page.route("**/api/bacnet/hardware/status", (r) =>
      r.fulfill({
        json: { jobs: [], reports: [survey], archives: [], captures: [] },
      }),
    );
    await page.route("**/api/bacnet/hardware/reports/" + id, (r) =>
      r.fulfill({ json: survey }),
    );
    let reads = 0;
    await page.route("**/api/bacnet/controller/properties", async (r) => {
      const q = r.request().postDataJSON();
      if (!q.read_linked_zone_temperature) return r.continue();
      reads++;
      const sensor = q.object_ids[0];
      expect(q).toEqual({
        ...target,
        object_ids: [sensor],
        properties: ["object-name", "913", "941"],
        read_linked_zone_temperature: true,
      });
      const link =
        sensor === "627,7"
          ? {
              status: "observed",
              sensor,
              object: "analog-input,17",
              quality: "good",
              properties: {
                "present-value": { value: 21.25 },
                units: { value: { name: "degrees-celsius" } },
              },
            }
          : {
              status: "unconfirmed",
              reason:
                "The input did not confirm the sensor's exact item reference.",
            };
      await r.fulfill({
        json: {
          target,
          connector_config: status.config,
          identity_verified: true,
          finished_at: new Date().toISOString(),
          objects: [
            {
              object: sensor,
              identity_verified: true,
              properties: { "object-name": { value: "West zone sensor" } },
            },
          ],
          linked_zone_temperature: link,
        },
      });
    });
    await openSnapshot(page, snapshot.seeded);
    await chooseWorkspaceTask(page, "Points & I/O");
    const tools = page.getByRole("navigation", {
      name: "Controller task tools",
      exact: true,
    });
    const select = tools.getByRole("combobox");
    if (await select.isVisible())
      await select.selectOption({ label: "Hardware survey" });
    else
      await tools
        .getByRole("button", { name: "Hardware survey", exact: true })
        .click();
    const panel = page.getByRole("region", {
      name: "Controller hardware and input survey",
    });
    await panel
      .getByLabel("Saved hardware report", { exact: true })
      .selectOption(id);
    await panel
      .getByRole("button", { name: "Open saved hardware report" })
      .click();
    await panel.getByText("Room sensor temperature", { exact: true }).click();
    expect(reads).toBe(0);
    const button = panel.getByRole("button", {
      name: "Read linked room temperature",
    });
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(
      panel.getByRole("status").filter({ hasText: "West zone sensor" }),
    ).toContainText("21.25 °C. Quality good.");
    await panel
      .getByLabel("Room sensor", { exact: true })
      .selectOption("627,18");
    await expect(panel.getByText(/21.25 °C/)).toHaveCount(0);
    await button.click();
    await expect(panel.getByRole("alert")).toContainText("did not confirm");
    expect(reads).toBe(2);
  },
);
