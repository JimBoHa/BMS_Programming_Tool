import { defaultWireTransferProfile } from "./nativeDefaultWireTransferContract";
type Data = Record<string, any>;
const ref = (v: unknown) =>
  typeof v === "string" &&
  v.length > 0 &&
  v.length <= 512 &&
  !/[\u0000-\u001f\u007f]/.test(v);
const tuple = (v: unknown) =>
  Array.isArray(v) &&
  v.length === 4 &&
  v.every((n) => Number.isInteger(n) && n >= 0 && n <= 65535);
function value(bits: string) {
  const view = new DataView(new ArrayBuffer(4));
  view.setUint32(0, Number.parseInt(bits, 16), false);
  return view.getFloat32(0, false);
}
export function recordedDefaultWire(v: unknown): Data | null {
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const d = v as Data;
  if (
    d.state !== "recorded" ||
    d.profile !== defaultWireTransferProfile ||
    ![
      d.record_ref,
      d.diagram_ref,
      d.old_source_ref,
      d.source_ref,
      d.target_ref,
    ].every(ref) ||
    ![d.before_bits, d.after_bits].every(
      (b) =>
        typeof b === "string" &&
        /^[a-f0-9]{8}$/.test(b) &&
        Number.isFinite(value(b)),
    ) ||
    !Number.isInteger(d.wire_index) ||
    d.wire_index < 0 ||
    d.wire_index > 4095 ||
    !tuple(d.old) ||
    !tuple(d.new) ||
    !d.new.slice(1).every((n: number, i: number) => n === d.old[i + 1]) ||
    typeof d.compiled_native_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(d.compiled_native_sha256) ||
    d.transfer_confirmation_recorded !== true ||
    d.field_authority !== false ||
    typeof d.scope !== "string"
  )
    return null;
  return d;
}
const numberText = (bits: string) =>
  Object.is(value(bits), -0) ? "-0" : String(value(bits));
export function NativeDefaultWireLedgerView({ data }: { data: Data }) {
  return (
    <section aria-label="Recorded combined native edit">
      <h3>Recorded Real default and connection</h3>
      <dl>
        <dt>Real default</dt>
        <dd>
          {data.record_ref}: {numberText(data.before_bits)} to{" "}
          {numberText(data.after_bits)}
        </dd>
        <dt>Connection</dt>
        <dd>
          {data.diagram_ref} · connection {data.wire_index}
        </dd>
        <dt>Recorded source</dt>
        <dd>
          {data.old_source_ref} to {data.source_ref}
        </dd>
        <dt>Destination</dt>
        <dd>
          {data.target_ref} · pin {data.old[3]} · unchanged
        </dd>
      </dl>
      <p>
        Historical proposal only. Current source and controller state are not
        revalidated; opening this record grants no transfer authority.
      </p>
    </section>
  );
}
