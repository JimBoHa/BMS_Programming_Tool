import { test, expect } from "@playwright/test";
import { routerChoices } from "../src/routerChoices";

test("ordinary IP responders remain selectable without router advertisements or model assumptions", () => {
  const before = [{ router: "192.0.2.4", networks: [2001] }];
  const snapshot = JSON.stringify(before);
  const choices = routerChoices(before, [
    { address: "192.0.2.4:47808", device: "device,50" },
    { address: "198.51.100.8", device: "device,50" },
  ]);
  expect(choices).toHaveLength(2);
  expect(choices[0]).toMatchObject({
    router: "192.0.2.4",
    networks: [2001],
    device: "device,50",
    ipDiscovered: true,
  });
  expect(choices[1]).toMatchObject({
    router: "198.51.100.8",
    networks: [],
    device: "device,50",
  });
  expect(JSON.stringify(before)).toBe(snapshot);
});

test("one endpoint announcing different identities never gets an arbitrary Device label", () => {
  const choices = routerChoices(
    [],
    [
      { address: "192.0.2.4", device: "device,1" },
      { address: "192.0.2.4:47808", device: "device,2" },
      { address: "192.0.2.4", device: "device,1" },
    ],
  );
  expect(choices).toHaveLength(1);
  expect(choices[0].identityConflict).toBe(true);
  expect(choices[0].device).toBeUndefined();
});
