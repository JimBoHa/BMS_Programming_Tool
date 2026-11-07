import { defaultBatchTransferProfile } from "./nativeDefaultBatchTransferContract";
type Data = Record<string, any>;
const ref = (v: unknown) =>
  typeof v === "string" &&
  v.length > 0 &&
  v.length <= 512 &&
  !/[\u0000-\u001f\u007f]/.test(v);
function value(kind: string, text: string) {
  if (kind === "boolean") return text === "112f";
  if (kind === "enum") return Number.parseInt(text.slice(2, -2), 16);
  const view = new DataView(new ArrayBuffer(4));
  view.setUint32(0, Number.parseInt(text.slice(2, -2), 16), false);
  return view.getFloat32(0, false);
}
export function recordedDefaultBatch(v: any): Data | null {
  if (
    !v ||
    typeof v !== "object" ||
    Array.isArray(v) ||
    v.state !== "recorded" ||
    v.profile !== defaultBatchTransferProfile ||
    v.transfer_confirmation_recorded !== true ||
    v.field_authority !== false ||
    typeof v.scope !== "string" ||
    !/^[a-f0-9]{64}$/.test(v.compiled_native_sha256 || "") ||
    !Array.isArray(v.selected) ||
    !v.selected.length ||
    v.selected.length > 16 ||
    new Set(v.selected.map((r: Data) => r?.record_ref)).size !==
      v.selected.length
  )
    return null;
  for (const row of v.selected) {
    if (
      !row ||
      !ref(row.record_ref) ||
      !({ real: [526, 527], boolean: [530, 531], enum: [528, 529] } as Data)[
        row.kind
      ]?.includes(row.class_id)
    )
      return null;
    for (const hex of [row.before_encoding_hex, row.after_encoding_hex]) {
      if (typeof hex !== "string") return null;
      if (
        row.kind === "real"
          ? !/^44[a-f0-9]{8}2f$/.test(hex) ||
            !Number.isFinite(value("real", hex))
          : row.kind === "boolean"
            ? !/^(10|11)2f$/.test(hex)
            : !/^9[1-4](?:[a-f0-9]{2}){1,4}2f$/.test(hex) ||
              hex.length !== (Number(hex[1]) + 2) * 2 ||
              Number(value("enum", hex)) > 65535
      )
        return null;
    }
  }
  return v;
}
const text = (v: unknown) => (Object.is(v, -0) ? "-0" : String(v));
export function NativeDefaultBatchValues({
  selected,
  label,
}: {
  selected: Data[];
  label: string;
}) {
  return (
    <div
      className="application-operation-table"
      role="region"
      aria-label={label + " viewport"}
      tabIndex={0}
      onKeyDown={(event) => {
        if (
          event.target !== event.currentTarget ||
          event.altKey ||
          event.ctrlKey ||
          event.metaKey ||
          event.shiftKey ||
          !["ArrowLeft", "ArrowRight"].includes(event.key)
        )
          return;
        event.preventDefault();
        event.currentTarget.scrollBy({
          left: event.key === "ArrowRight" ? 80 : -80,
        });
      }}
    >
      <table aria-label={label}>
        <thead>
          <tr>
            <th>Default</th>
            <th>Type</th>
            <th>Before</th>
            <th>Proposed stored value</th>
          </tr>
        </thead>
        <tbody>
          {selected.map((row: Data) => (
            <tr key={row.record_ref}>
              <th scope="row">{row.record_ref}</th>
              <td>{row.kind}</td>
              <td>{text(value(row.kind, row.before_encoding_hex))}</td>
              <td>{text(value(row.kind, row.after_encoding_hex))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function NativeDefaultBatchLedgerView({ data }: { data: Data }) {
  return (
    <section aria-label="Recorded typed default batch">
      <h3>Recorded typed defaults</h3>
      <NativeDefaultBatchValues
        selected={data.selected}
        label="Recorded typed default values"
      />
      <p>
        Historical proposal only. Current source and controller state are not
        revalidated; opening this record grants no transfer authority. Enum
        meanings remain unverified.
      </p>
    </section>
  );
}
