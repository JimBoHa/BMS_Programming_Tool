import { recordedBinaryTerminal } from "./nativeBinaryTerminalLedger";
export function BinaryTerminalSummary({ value }: { value: unknown }) {
  const record = recordedBinaryTerminal(value);
  return record ? (
    <span>
      Move binary input · {record.old_terminal_label} to {record.terminal_label}
    </span>
  ) : null;
}
export function NativeBinaryTerminalLedgerView({ value }: { value: unknown }) {
  const record = recordedBinaryTerminal(value);
  return (
    <section aria-label="Recorded binary terminal movement">
      <h4>
        {record ? "Move binary input" : "Binary terminal metadata unavailable"}
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
            <caption>Preserved recorded binary configuration</caption>
            <thead>
              <tr>
                <th>Field</th>
                <th>Recorded value</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["Active text", record.stored_configuration.active_text],
                ["Inactive text", record.stored_configuration.inactive_text],
                [
                  "States Text index",
                  record.stored_configuration.states_text_index,
                ],
                [
                  "Polarity",
                  record.stored_configuration.polarity === null
                    ? "Not recorded"
                    : record.stored_configuration.polarity === 0
                      ? "Normal"
                      : "Reverse",
                ],
              ].map(([label, value]) => (
                <tr key={label}>
                  <th>{label}</th>
                  <td>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {Object.keys(record.captured_counter_values).length > 0 && (
            <details>
              <summary>Historical binary counters</summary>
              <p>These recorded values are not current live readings.</p>
              <dl>
                {Object.entries(record.captured_counter_values).map(
                  ([key, value]) => (
                    <div key={key}>
                      <dt>
                        {key === "15" ? "COS Count" : "Elapsed Active Time"}
                      </dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ),
                )}
              </dl>
            </details>
          )}
          <details>
            <summary>Recorded binary fingerprints</summary>
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
