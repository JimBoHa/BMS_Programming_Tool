function RuntimeCounterChanges({ preservation }: { preservation: any }) {
  const counters = preservation?.runtime_counter_changes || [];
  if (!counters.length) return null;
  return (
    <section aria-label="Runtime counter readback">
      <p role="status">
        Runtime counter changes were observed after transfer. These values can
        change while the controller operates; they are reported separately from
        application settings.
      </p>
      <details>
        <summary>Runtime counter values</summary>
        <table>
          <thead>
            <tr>
              <th>Counter</th>
              <th>Application value</th>
              <th>Current saved value</th>
            </tr>
          </thead>
          <tbody>
            {counters.map((row: any) => (
              <tr key={`${row.class}:${row.instance}:${row.property}`}>
                <td>
                  {row.property_name} · {row.class}:{row.instance}
                </td>
                <td>
                  {row.application_value ?? "Not retained in this receipt"}
                </td>
                <td>
                  {row.current_saved_value ?? "Not retained in this receipt"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

export function NativeRuntimeCalibration({
  report,
  preservation,
}: {
  report: any;
  preservation?: any;
}) {
  if (!report || report.not_applicable)
    return <RuntimeCounterChanges preservation={preservation} />;
  return (
    <>
      <RuntimeCounterChanges preservation={preservation} />
      <section aria-label="Live flow calibration readback">
        {report.changed?.length > 0 && (
          <p role="status">
            The controller’s calculated airflow calibration differs from the
            transferred application value. The live values below are separate
            from stored application/settings verification.
          </p>
        )}
        {!report.complete && (
          <p role="status">
            Live airflow calibration was not completely read. Open the details
            for unavailable values; stored-image verification does not verify
            these current runtime outputs.
          </p>
        )}
        <details>
          <summary>Live airflow calibration values</summary>
          <p>{report.scope}</p>
          <table>
            <thead>
              <tr>
                <th>Flow module</th>
                <th>Application value</th>
                <th>Live value</th>
                <th>Read outcome</th>
              </tr>
            </thead>
            <tbody>
              {report.fields.map((row: any) => (
                <tr key={row.object}>
                  <td>{row.object}</td>
                  <td>{row.application_value ?? "Not captured"}</td>
                  <td>{row.live_value ?? "Unavailable"}</td>
                  <td>{row.error || row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>
    </>
  );
}
