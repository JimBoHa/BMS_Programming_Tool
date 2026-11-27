interface SavedSample {
  flow: number;
  damper_position_percent: number;
}

interface SavedResult {
  instance: number;
  property: number;
  value: SavedSample[] | number[];
}

export function BoxFlowHistory({ results }: { results?: SavedResult[] }) {
  if (!Array.isArray(results) || !results.length) return null;
  return (
    <details>
      <summary>Recorded box flow test results</summary>
      <p>
        These readings come from the controller backup. Flow uses the units
        recorded by the controller.
      </p>
      {results.map((record) => (
        <section key={record.instance + "/" + record.property}>
          {record.property === 3668 ? (
            <p>
              Module {record.instance}, result bits 0–7:{" "}
              {record.value.join(" ")}
            </p>
          ) : (
            <table>
              <caption>Flow test samples for module {record.instance}</caption>
              <thead>
                <tr>
                  <th scope="col">Sample</th>
                  <th scope="col">Recorded flow</th>
                  <th scope="col">Damper position (%)</th>
                </tr>
              </thead>
              <tbody>
                {(record.value as SavedSample[]).map((sample, index) => (
                  <tr key={index}>
                    <td>{index + 1}</td>
                    <td>{sample.flow}</td>
                    <td>{sample.damper_position_percent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ))}
    </details>
  );
}
