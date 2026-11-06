import { recordedEncodedAnalogTerminal } from "./nativeEncodedAnalogLedger";
export function EncodedAnalogTerminalSummary({ value }: { value: unknown }) {
  const record = recordedEncodedAnalogTerminal(value);
  return record ? (
    <span>
      Move analog input · {record.old_terminal_label} to {record.terminal_label}
    </span>
  ) : null;
}
export function NativeEncodedAnalogLedgerView({ value }: { value: unknown }) {
  const record = recordedEncodedAnalogTerminal(value);
  return (
    <section aria-label="Recorded analog terminal movement">
      <h4>
        {record ? "Move analog input" : "Analog terminal metadata unavailable"}
      </h4>
      {record ? (
        <>
          <dl>
            <dt>Recorded object</dt>
            <dd>{record.object_id}</dd>
            <dt>Native reference</dt>
            <dd>{record.record_ref}</dd>
            <dt>Previous terminal</dt>
            <dd>{record.old_terminal_label}</dd>
            <dt>Destination terminal</dt>
            <dd>{record.terminal_label}</dd>
            <dt>Confirmations recorded</dt>
            <dd>Yes</dd>
          </dl>
          <p>{record.scope}</p>
          <table>
            <caption>
              Preserved recorded analog configuration and field presence
            </caption>
            <thead>
              <tr>
                <th>Field</th>
                <th>Recorded value</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["Setup code", record.stored_configuration.setup],
                ["Field unit code", record.stored_configuration.field_units],
                ["Input low", record.stored_configuration.input_low],
                ["Input high", record.stored_configuration.input_high],
                ["Output low", record.stored_configuration.output_low],
                ["Output high", record.stored_configuration.output_high],
                ["Unit code", record.stored_configuration.units],
                ["Minimum", record.stored_configuration.minimum],
                ["Maximum", record.stored_configuration.maximum],
              ].map(([label, value]) => (
                <tr key={label}>
                  <th>{label}</th>
                  <td>
                    {value === null
                      ? "Not stored"
                      : Object.is(value, -0)
                        ? "-0"
                        : String(value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <details>
            <summary>Recorded analog fingerprints</summary>
            <pre>
              {JSON.stringify(
                Object.fromEntries(
                  Object.entries(record).filter(
                    ([k]) =>
                      k.endsWith("sha256") ||
                      k === "device_type_character_encoding",
                  ),
                ),
                null,
                2,
              )}
            </pre>
          </details>
        </>
      ) : (
        <p>
          Inspect original evidence. Current source, wiring, controller values
          and new transfer authority are not established here.
        </p>
      )}
    </section>
  );
}
