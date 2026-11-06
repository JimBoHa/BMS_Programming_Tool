import { expect, test } from "@playwright/test";
import { python, simulation } from "./caf-simulation-fixture";

for (const classId of ["528", "529"]) {
  test(`scenario profile distinguishes an isolated ${classId === "528" ? "Input" : "Output"} Enum`, async ({
    page,
  }) => {
    const buffer = python(
      `from bms_tool.caf import CafArchive
from tests.test_caf_enum_simulation import source
from tests.test_caf_simulation import pack
import sys
xml=CafArchive(source(cid=int(sys.argv[1]))).xml
xml=xml.replace(b'classid="526"',b'classid="999"').replace(b'classid="530"',b'classid="999"')
sys.stdout.buffer.write(pack(xml))`,
      classId,
    );
    await page.goto("/");
    await page
      .getByLabel("Open local CAF application", { exact: true })
      .setInputFiles({
        name: "authored-enum-only.caf",
        mimeType: "application/octet-stream",
        buffer,
      });
    await expect(
      page.getByLabel("Current CAF archive", { exact: true }),
    ).toHaveText("authored-enum-only.caf");
    await simulation(page);
    const active = () => page.locator(".caf-local-scenarios:visible");
    await expect(active()).toContainText(
      "No supported saved input startup records",
    );
    await page
      .getByLabel("Local scenario input profile", { exact: true })
      .selectOption("2");
    if (classId === "528") {
      await expect(active()).toContainText("1 supported inputs");
      await expect(
        active()
          .getByLabel("Local event input", { exact: true })
          .locator("option"),
      ).toHaveCount(1);
    } else {
      await expect(active()).toContainText(
        "No supported saved input startup records",
      );
      expect(await active().innerText()).not.toContain(
        "Output blocks, enums and unknown records cannot become local inputs.",
      );
      await expect(
        active().getByRole("button", {
          name: "Preview input stimuli",
          exact: true,
        }),
      ).toHaveCount(0);
    }
  });
}
