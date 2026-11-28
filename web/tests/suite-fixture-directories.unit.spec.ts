import { expect, test } from "@playwright/test";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { suiteFixtureDirectories } from "./suiteFixtureDirectories";

const create = suiteFixtureDirectories();
const owned: string[] = [];
let neighbour: string;

test.beforeAll(() => {
  neighbour = mkdtempSync(join(tmpdir(), "independent-fixture-"));
  for (let i = 0; i < 2; i++) {
    const directory = create("contract-input-");
    writeFileSync(join(directory, "seed"), String(i));
    owned.push(directory);
  }
});

test("independently seeded inputs remain available throughout the suite", () => {
  expect(new Set(owned).size).toBe(2);
  for (const directory of owned)
    expect(existsSync(join(directory, "seed"))).toBe(true);
});

// The directory owner's afterAll hook was registered first.
test.afterAll(() => {
  try {
    expect(owned.map(existsSync)).toEqual([false, false]);
    expect(existsSync(neighbour)).toBe(true);
  } finally {
    if (neighbour) rmSync(neighbour, { recursive: true, force: true });
  }
});
