export function NativeRuntimeCalibration({ report }: { report: any }) {
  if (!report || report.not_applicable) return null;
  return (
    <section aria-label="Live flow calibration readback">
      {report.changed?.length > 0 && (
        <p role="status">
          The controller’s calculated airflow calibration differs from the
          transferred application value. The live values below are separate from
          stored application/settings verification.
        </p>
      )}
      {!report.complete && (
        <p role="status">
          Live airflow calibration was not completely read. Open the details for
          unavailable values; stored-image verification does not verify these
          current runtime outputs.
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
  );
}
