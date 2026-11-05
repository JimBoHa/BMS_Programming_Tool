import { recordedTerminal } from "./nativeTerminalLedger";

const text = (v: number) => (Object.is(v, -0) ? "-0" : String(v));
export function TerminalSummary({ value }: { value: unknown }) {
  const terminal = recordedTerminal(value);
  return terminal ? (
    <span>
      Move analog input · {terminal.old_terminal_label} to{" "}
      {terminal.terminal_label}
    </span>
  ) : null;
}
export function NativeTerminalLedgerView({ value }: { value: unknown }) {
  const terminal = recordedTerminal(value);
  return (
    <section aria-label="Recorded terminal movement">
      <h4>
        {terminal ? "Move analog input" : "Terminal metadata unavailable"}
      </h4>
      {terminal ? (
        <>
          <dl>
            <dt>Recorded object</dt>
            <dd>{terminal.object_id}</dd>
            <dt>Native reference</dt>
            <dd>{terminal.record_ref}</dd>
            <dt>Previous terminal</dt>
            <dd>{terminal.old_terminal_label}</dd>
            <dt>Destination terminal</dt>
            <dd>{terminal.terminal_label}</dd>
            <dt>Wiring confirmation recorded</dt>
            <dd>{terminal.wiring_confirmation_recorded ? "Yes" : "No"}</dd>
          </dl>
          <p>{terminal.scope}</p>
          <div>
            <table>
              <caption>Preserved recorded input configuration</caption>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Recorded native value</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["setup", "Electrical setup code"],
                  ["field_units", "Electrical unit code"],
                  ["input_low", "Electrical range low"],
                  ["input_high", "Electrical range high"],
                  ["output_low", "Engineering range low"],
                  ["output_high", "Engineering range high"],
                  ["units", "Engineering unit code"],
                  ["minimum", "Minimum present value"],
                  ["maximum", "Maximum present value"],
                ].map(([key, label]) => (
                  <tr key={key}>
                    <th>{label}</th>
                    <td>{text(terminal.stored_configuration[key])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Recorded terminal fingerprints</summary>
            <pre>
              {JSON.stringify(
                {
                  configuration_sha256: terminal.configuration_sha256,
                  source_sha256: terminal.source_sha256,
                  source_native_sha256: terminal.source_native_sha256,
                  output_sha256: terminal.output_sha256,
                  output_native_sha256: terminal.output_native_sha256,
                  compilation_sha256: terminal.compilation_sha256,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </>
      ) : (
        <p>
          Recorded terminal metadata is incomplete or inconsistent. Inspect the
          original evidence; it grants no tool or transfer authority.
        </p>
      )}
    </section>
  );
}
