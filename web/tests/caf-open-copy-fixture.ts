import { expect, type Page, type Locator } from "@playwright/test";
import { logic, python, source as floatSource } from "./caf-constant-fixture";
import { source as booleanSource } from "./caf-boolean-fixture";
import { source as enumSource } from "./caf-enum-creation-fixture";
import { source as comparisonSource } from "./caf-comparison-fixture";
import { source as enumComparisonSource } from "./caf-enum-comparison-fixture";
import { source as mathSource } from "./caf-math-fixture";
import { source as booleanLogicSource } from "./caf-boolean-logic-fixture";
import { source as timerSource } from "./caf-timer-fixture";
import { source as reliabilitySource } from "./caf-reliability-fixture";
import { source as multiplexerSource } from "./caf-float-multiplexer-fixture";
import { source as enumMultiplexerSource } from "./caf-enum-selector-multiplexer-fixture";
import { constantKinds, type ConstantKind } from "../src/cafConstantContract";
export { python, logic };
export type Family = {
  name: string;
  kind: ConstantKind;
  primitive: boolean;
  source: () => Buffer;
};
export const families: Family[] = [
  {
    name: "Float constant",
    kind: "float",
    primitive: false,
    source: () => floatSource(),
  },
  {
    name: "Boolean constant",
    kind: "boolean",
    primitive: false,
    source: () => booleanSource(),
  },
  {
    name: "Enum constant",
    kind: "enumeration",
    primitive: false,
    source: () => enumSource(),
  },
  {
    name: "Float comparison",
    kind: "comparison",
    primitive: true,
    source: () => comparisonSource(),
  },
  {
    name: "Enum comparison",
    kind: "comparison",
    primitive: true,
    source: () => enumComparisonSource(),
  },
  { name: "Math", kind: "math", primitive: true, source: () => mathSource() },
  {
    name: "Boolean logic",
    kind: "booleanLogic",
    primitive: true,
    source: () => booleanLogicSource(),
  },
  {
    name: "Timer",
    kind: "timer",
    primitive: true,
    source: () => timerSource(),
  },
  {
    name: "Float reliability",
    kind: "reliability",
    primitive: true,
    source: () => reliabilitySource(),
  },
  {
    name: "Enum reliability",
    kind: "reliability",
    primitive: true,
    source: () => reliabilitySource("enum"),
  },
  {
    name: "Boolean selector",
    kind: "multiplexer",
    primitive: true,
    source: () => multiplexerSource(),
  },
  {
    name: "Enum selector",
    kind: "multiplexer",
    primitive: true,
    source: () => enumMultiplexerSource(),
  },
];
export function editorFor(page: Page, family: Family) {
  return page.getByRole("region", {
    name: family.primitive ? "CAF block creation" : "CAF constant creation",
    exact: true,
  });
}
export async function inspectFamily(page: Page, family: Family) {
  const details = page.locator(".caf-constant-copy:visible");
  if ((await details.getAttribute("open")) === null)
    await details.locator("summary").first().click();
  const editor = editorFor(page, family),
    subject = family.primitive ? "block" : "constant";
  await editor
    .getByRole("button", { name: `Inspect ${subject} prototype`, exact: true })
    .click();
  await expect(
    editor.getByLabel(`New ${subject} X`, { exact: true }),
  ).toBeVisible();
  return editor;
}
export async function enterFamily(
  page: Page,
  family = families[0],
  buffer?: Buffer,
) {
  await page.goto("/");
  await page
    .getByLabel("Open local CAF application", { exact: true })
    .setInputFiles({
      name: "authored.caf",
      mimeType: "application/octet-stream",
      buffer: buffer || family.source(),
    });
  await expect(
    page.getByLabel("Current CAF archive", { exact: true }),
  ).toHaveText("authored.caf");
  await logic(page);
  return inspectFamily(page, family);
}
export async function savedCopy(
  page: Page,
  family = families[0],
  editor?: Locator,
) {
  const current = editor || editorFor(page, family),
    subject = family.primitive ? "block" : "constant";
  let proof: any;
  const path = `**/${constantKinds[family.kind].path}/preview`;
  await page.route(path, async (route) => {
    const response = await route.fetch({ maxRetries: 0 });
    proof = JSON.parse((await response.body()).toString());
    await route.fulfill({ response });
  });
  await current
    .getByRole("button", { name: `Review ${subject} CAF copy`, exact: true })
    .click();
  const review = current.getByRole("region", {
    name: family.primitive
      ? "Reviewed CAF block copy"
      : "Reviewed CAF constant copy",
    exact: true,
  });
  await expect(review).toBeVisible();
  await page.unroute(path);
  const downloading = page.waitForEvent("download");
  await review
    .getByRole("button", { name: `Save ${subject} CAF copy`, exact: true })
    .click();
  await downloading;
  await expect(
    current.getByRole("button", { name: "Open CAF copy", exact: true }),
  ).toBeVisible();
  return proof;
}
