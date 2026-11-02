import { test, expect } from "@playwright/test";
import {
  emptyIdentityWork,
  rememberIdentityWork,
  releaseEmptyIdentityWork,
  identityDraftDocument,
  IDENTITY_DRAFT_LIMIT,
} from "../src/nativeIdentityWork";
const key = (i: number) =>
  JSON.stringify([
    false,
    "authored interface",
    "192.0.2." + (i + 1),
    "device," + (i + 1),
    null,
    null,
    "name",
  ]);
test("empty identity views and passive receipts use no slot; active reservations are released without deleting a completed draft", () => {
  const work = new Map();
  for (let i = 0; i < 40; i++)
    expect(
      rememberIdentityWork(work, key(i), {
        ...emptyIdentityWork(),
        receipt: { intent: { id: String(i) } },
      }),
    ).toBe(true);
  expect(work.size).toBe(0);
  expect(rememberIdentityWork(work, key(1), emptyIdentityWork(), true)).toBe(
    true,
  );
  expect(work.size).toBe(1);
  releaseEmptyIdentityWork(work, key(1));
  expect(work.size).toBe(0);
  rememberIdentityWork(work, key(1), emptyIdentityWork(), true);
  rememberIdentityWork(work, key(1), {
    ...emptyIdentityWork(),
    newName: "  unfinished  ",
  });
  releaseEmptyIdentityWork(work, key(1));
  expect(work.get(key(1)).newName).toBe("  unfinished  ");
});
test("a 33rd identity source is refused without evicting earlier names, numbers, captures or recovery evidence", () => {
  const work = new Map();
  for (let i = 0; i < IDENTITY_DRAFT_LIMIT; i++)
    expect(
      rememberIdentityWork(work, key(i), {
        capture: { id: String(i) },
        receipt: { intent: { id: "receipt" + i } },
        newName: "Draft" + i,
        number: "1e-",
        recovery: { data: { origin_sha256: "original" + i } },
      }),
    ).toBe(true);
  const before = JSON.stringify([...work]);
  expect(
    rememberIdentityWork(work, key(33), {
      ...emptyIdentityWork(),
      newName: "new",
    }),
  ).toBe(false);
  expect(JSON.stringify([...work])).toBe(before);
  expect(
    rememberIdentityWork(work, key(0), {
      ...work.get(key(0)),
      newName: "updated",
    }),
  ).toBe(true);
  expect(work.size).toBe(32);
  expect(work.get(key(31)).recovery.data.origin_sha256).toBe("original31");
  rememberIdentityWork(work, key(0), emptyIdentityWork());
  expect(work.size).toBe(31);
  expect(
    rememberIdentityWork(work, key(33), {
      ...emptyIdentityWork(),
      number: "6000",
    }),
  ).toBe(true);
  expect(work.size).toBe(32);
  expect(work.has(key(31))).toBe(true);
});
test("local identity export retains raw text and separates context from captured source without any transfer authority", () => {
  const state = {
    capture: {
      id: "c".repeat(32),
      snapshot_evidence_sha256: "f".repeat(64),
      target: {
        device: "device,5136",
        address: "3001:7",
        router: "127.0.0.1:47808",
        dnet: 3001,
      },
    },
    receipt: { intent: { id: "receipt", token: "must-not-export" } },
    newName: "  unreviewed  ",
    number: "1e-",
    recovery: {
      data: { origin_sha256: "a".repeat(64) },
      blob: new Blob(["original evidence"]),
    },
  };
  const original = JSON.stringify(state);
  const out = identityDraftDocument(key(1), state);
  expect(out.new_name).toBe("  unreviewed  ");
  expect(out.new_instance_text).toBe("1e-");
  expect(out.selection.device).toBe("device,2");
  expect(out.captured_target.device).toBe("device,5136");
  expect(out.field_authority).toBe(false);
  expect(JSON.stringify(out)).not.toContain("must-not-export");
  expect(JSON.stringify(state)).toBe(original);
});
