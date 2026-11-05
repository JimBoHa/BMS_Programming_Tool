/** Browser-local primitives that also work on explicitly configured LAN HTTP. */
import { sha256 } from "@noble/hashes/sha2.js";

export async function sha256Digest(value: BufferSource): Promise<ArrayBuffer> {
  const subtle = globalThis.crypto?.subtle;
  if (typeof subtle?.digest === "function") {
    // Preserve native failures; an available provider must not be silently
    // bypassed. Call-time feature detection also preserves verification hooks.
    return subtle.digest("SHA-256", value);
  }
  const bytes = ArrayBuffer.isView(value)
    ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
    : new Uint8Array(value);
  return Uint8Array.from(sha256(bytes)).buffer;
}

export function randomUUID(): ReturnType<Crypto["randomUUID"]> {
  const provider = globalThis.crypto;
  if (typeof provider?.randomUUID === "function") return provider.randomUUID();
  if (typeof provider?.getRandomValues !== "function") {
    throw new Error(
      "This browser cannot generate secure operation identifiers.",
    );
  }
  const bytes = provider.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
