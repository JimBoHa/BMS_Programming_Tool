import { test, expect } from "@playwright/test";
import { createHash, webcrypto } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { sha256Digest, randomUUID } from "../src/browserCrypto";
import { checkCatalog } from "../src/modelTransportContract";

const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
const use = (value: unknown) =>
  Object.defineProperty(globalThis, "crypto", { configurable: true, value });
const hex = (bytes: ArrayBuffer) => Buffer.from(bytes).toString("hex");
test.afterEach(() => {
  if (original) Object.defineProperty(globalThis, "crypto", original);
  else Reflect.deleteProperty(globalThis, "crypto");
});

test("fallback SHA-256 matches standard vectors, Unicode, block boundaries and sliced buffers", async () => {
  use({ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) });
  const vectors = [
    ["", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    ["abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
    [
      "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    ],
  ];
  for (const [text, expected] of vectors)
    expect(hex(await sha256Digest(new TextEncoder().encode(text)))).toBe(
      expected,
    );
  const unicode = new TextEncoder().encode("Temperature °C · 中 · 😀");
  expect(hex(await sha256Digest(unicode))).toBe(
    createHash("sha256").update(unicode).digest("hex"),
  );
  for (const size of [0, 1, 55, 56, 63, 64, 65, 4096, 1_000_000]) {
    const full = Uint8Array.from({ length: size + 14 }, (_, i) => i % 251);
    const sliced = full.subarray(7, 7 + size),
      before = full.slice();
    const expected = createHash("sha256").update(sliced).digest("hex");
    expect(hex(await sha256Digest(sliced))).toBe(expected);
    expect(hex(await sha256Digest(new DataView(full.buffer, 7, size)))).toBe(
      expected,
    );
    expect(full).toEqual(before);
  }
});

test("an available native digest is called with its receiver and errors are propagated", async () => {
  const bytes = new Uint8Array([1, 2, 3]);
  let calls = 0;
  const subtle = {
    async digest(algorithm: string, value: BufferSource) {
      expect(this).toBe(subtle);
      expect(algorithm).toBe("SHA-256");
      expect(value).toBe(bytes);
      calls++;
      throw new Error("native provider refusal");
    },
  };
  use({ subtle });
  await expect(sha256Digest(bytes)).rejects.toThrow("native provider refusal");
  expect(calls).toBe(1);
});

test("UUID fallback uses secure random bytes and retains RFC version/variant bits", () => {
  let calls = 0;
  use({
    getRandomValues(bytes: Uint8Array) {
      calls++;
      bytes.set(Array.from({ length: 16 }, (_, i) => i));
      return bytes;
    },
  });
  expect(randomUUID()).toBe("00010203-0405-4607-8809-0a0b0c0d0e0f");
  expect(calls).toBe(1);
  use({ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) });
  const ids = Array.from({ length: 1000 }, () => randomUUID());
  expect(new Set(ids).size).toBe(ids.length);
  expect(
    ids.every((id) =>
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
        id,
      ),
    ),
  ).toBe(true);
});

test("native UUIDs are retained and missing secure randomness is refused", () => {
  const provider = {
    randomUUID() {
      expect(this).toBe(provider);
      return "00000000-0000-4000-8000-000000000000";
    },
  };
  use(provider);
  expect(randomUUID()).toBe("00000000-0000-4000-8000-000000000000");
  use({});
  expect(() => randomUUID()).toThrow("secure operation identifiers");
  use(undefined);
  expect(() => randomUUID()).toThrow("secure operation identifiers");
});

test("fallback catalog verification still rejects changed metadata and altered seals", async () => {
  use({ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) });
  const root = path.resolve("..");
  const actual = JSON.parse(
    execFileSync(
      path.join(root, ".venv/bin/python"),
      [
        "-c",
        "import json; from bms_tool.model_transport import catalog; print(json.dumps(catalog()))",
      ],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "backend") },
      },
    ).toString(),
  );
  expect(await checkCatalog(actual)).toEqual(actual);
  const changed = structuredClone(actual);
  changed.profile.injected = true;
  await expect(checkCatalog(changed)).rejects.toThrow(
    "altered model transport profile",
  );
  const resealed = structuredClone(changed);
  const { canonical } = await import("../src/modelTransportContract");
  resealed.profile_sha256 = createHash("sha256")
    .update(canonical(resealed.profile))
    .digest("hex");
  await expect(checkCatalog(resealed)).rejects.toThrow(
    "altered model transport profile",
  );
});
