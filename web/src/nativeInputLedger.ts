export const INPUT_LEDGER_PROFILE = "native-local-universal-input-transfer/1";
export const INPUT_LEDGER_SCOPE =
  "Recorded input edit and compilation bindings only. No backup/parent revalidation, " +
  "controller query, live value, wiring/accuracy verification or transfer authority.";
export type RecordedInput = {
  state: "recorded";
  profile: string;
  action: "allocate" | "mode" | "remove-allocated";
  object_id: string;
  record_ref: string;
  slot: number;
  terminal_label: string;
  requested_name: string | null;
  requested_configuration:
    | ({ mode: "voltage" | "resistance" | "current" } & Record<string, any>)
    | null;
  stored_configuration: Record<string, number> | null;
  allocation_receipt_id: string | null;
  wiring_confirmation_recorded: boolean;
  scope: string;
};
const exact = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const numberFields = [
  "input_low",
  "input_high",
  "output_low",
  "output_high",
  "units",
  "minimum",
  "maximum",
];
export function recordedInput(v: any): RecordedInput | null {
  if (
    !exact(v, [
      "state",
      "profile",
      "action",
      "object_id",
      "record_ref",
      "slot",
      "terminal_label",
      "requested_name",
      "requested_configuration",
      "stored_configuration",
      "allocation_receipt_id",
      "wiring_confirmation_recorded",
      "scope",
    ]) ||
    v.state !== "recorded" ||
    v.profile !== INPUT_LEDGER_PROFILE ||
    v.scope !== INPUT_LEDGER_SCOPE ||
    !["allocate", "mode", "remove-allocated"].includes(v.action) ||
    typeof v.object_id !== "string" ||
    !/^analog-input,(0|[1-9][0-9]*)$/.test(v.object_id) ||
    Number(v.object_id.split(",")[1]) > 4194302 ||
    typeof v.record_ref !== "string" ||
    !v.record_ref.includes("/") ||
    [...v.record_ref].length > 512 ||
    /[\u0000-\u001f\uD800-\uDFFF]/u.test(v.record_ref) ||
    !Number.isInteger(v.slot) ||
    v.slot < 1 ||
    v.slot > 255 ||
    v.terminal_label !== `UI IN${v.slot}` ||
    typeof v.wiring_confirmation_recorded !== "boolean"
  )
    return null;
  if (
    v.action === "allocate"
      ? typeof v.requested_name !== "string" ||
        !v.requested_name ||
        [...v.requested_name].length > 128 ||
        /[\u0000-\u001f\uD800-\uDFFF]/u.test(v.requested_name)
      : v.requested_name !== null
  )
    return null;
  if (v.action === "remove-allocated") {
    if (
      v.requested_configuration !== null ||
      v.stored_configuration !== null ||
      typeof v.allocation_receipt_id !== "string" ||
      !/^[a-f0-9]{32}$/.test(v.allocation_receipt_id)
    )
      return null;
  } else {
    const wanted = v.requested_configuration,
      stored = v.stored_configuration;
    if (
      v.allocation_receipt_id !== null ||
      !exact(wanted, ["mode", ...numberFields]) ||
      !["voltage", "resistance", "current"].includes(wanted.mode) ||
      !exact(stored, ["setup", "field_units", ...numberFields]) ||
      !numberFields.every(
        (k) =>
          typeof wanted[k] === "number" &&
          Number.isFinite(wanted[k]) &&
          typeof stored[k] === "number" &&
          Number.isFinite(stored[k]),
      ) ||
      !Number.isInteger(wanted.units) ||
      wanted.units < 0 ||
      wanted.units > 65535 ||
      stored.units !== wanted.units ||
      stored.setup !==
        ({ voltage: 1, resistance: 0, current: 2 } as Record<string, number>)[
          wanted.mode
        ] ||
      stored.field_units !==
        ({ voltage: 5, resistance: 4, current: 2 } as Record<string, number>)[
          wanted.mode
        ] ||
      !numberFields
        .filter((k) => k !== "units")
        .every((k) => Object.is(stored[k], Math.fround(wanted[k])))
    )
      return null;
  }
  return v;
}
export const inputAction = (v: RecordedInput) =>
  ({
    allocate: "Allocate input",
    mode: "Edit input mode/scaling",
    "remove-allocated": "Remove allocated input",
  })[v.action];
