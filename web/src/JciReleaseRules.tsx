import type { ReactNode } from "react";
type Data = Record<string, any>;
const labels: Record<string, string> = {
  open: "Open existing CAF",
  commission: "Commission existing application",
  "edit-defaults": "Edit default values",
  "edit-logic": "Edit logic",
  simulate: "Simulate CAF",
  "upgrade-caf": "Review automatic CAF upgrade",
  "define-hardware": "Define hardware",
  "transfer-to-device": "Review CAF transfer to device",
  "mstp-coexistence": "Review mixed firmware on engine MS/TP integration",
};
function Source({ source }: { source: Data }) {
  return (
    <p>
      <a href={source.url} target="_blank" rel="noreferrer">
        {source.title} {source.release}
      </a>{" "}
      · {source.document} · PDF pages {source.pdf_pages.join(", ")} · SHA256{" "}
      <code>{source.sha256}</code>
    </p>
  );
}
export function JciReleaseRulesForm({
  value,
  catalog,
  disabled,
  onChange,
}: {
  value: Data | null;
  catalog: Data | null;
  disabled: boolean;
  onChange: (value: Data | null) => void;
}) {
  const patch = (key: string, next: unknown) =>
    onChange({ ...value, [key]: next });
  const text = (key: string, label: string, help?: string) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value?.[key] ?? ""}
        maxLength={80}
        onChange={(event) => patch(key, event.target.value)}
      />
      {help && <small>{help}</small>}
    </label>
  );
  const choice = (key: string, label: string, options: [string, string][]) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value?.[key] ?? "unknown"}
        onChange={(event) => patch(key, event.target.value)}
      >
        {options.map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <fieldset
      disabled={disabled || !catalog}
      aria-label="Documented tool release rules"
    >
      <legend>Documented tool/release compatibility</legend>
      <p>
        Review a specific planned operation against cited manuals. Tool release,
        source-tool release, CAF release mode, Appl SW Version and controller
        firmware are separate identifiers. Nothing is installed, upgraded,
        simulated or transferred by this review.
      </p>
      <label>
        <input
          type="checkbox"
          aria-label="Include documented release-rule review"
          checked={!!value}
          onChange={(event) =>
            onChange(
              event.target.checked ? structuredClone(catalog!.template) : null,
            )
          }
        />
        Include documented operation rules
      </label>
      {value && (
        <>
          <div className="jci-preflight-fields">
            <label>
              Planned native operation
              <select
                aria-label="Planned native operation"
                value={value.operation}
                onChange={(event) => patch("operation", event.target.value)}
              >
                {catalog?.operations.map((op: string) => (
                  <option key={op} value={op}>
                    {labels[op] || op}
                  </option>
                ))}
              </select>
            </label>
            {choice("source_tool_product", "Source application tool product", [
              ["unknown", "Unknown"],
              ["CCT", "CCT"],
              ["PCT", "FX-PCT"],
            ])}
            {text(
              "source_tool_release",
              "Source application tool release",
              "Release number such as10.2; not CAF mode or Metasys server release.",
            )}
            {choice("source_channel", "Source application release channel", [
              ["unknown", "Unknown"],
              ["production", "Production"],
              ["alpha", "Alpha"],
              ["beta", "Beta"],
            ])}
            {text(
              "caf_release_mode",
              "CAF release mode",
              "Declare independently. Appl SW Version is not automatically used.",
            )}
            {text(
              "active_release_mode",
              "Active tool release mode",
              "Declare the selected mode, not the software tool release.",
            )}
            {text(
              "caf_device_family",
              "CAF device-family identifier",
              "Exact declared family key; no family is inferred from the model prefix.",
            )}
            {text(
              "active_device_family",
              "Active mode device-family identifier",
              "Use the same exact identifier only for the same documented device family.",
            )}
            {choice(
              "package_generation",
              "Controller package security generation",
              [
                ["unknown", "Unknown"],
                ["pre-16-only", "Compatible only before CCT 16"],
                ["updated-16-plus", "Updated for CCT 16 and later"],
              ],
            )}
            <label>
              Package generation evidence
              <textarea
                aria-label="Package generation evidence"
                maxLength={2000}
                value={value.package_generation_evidence}
                onChange={(event) =>
                  patch("package_generation_evidence", event.target.value)
                }
              />
            </label>
            <label>
              Mixed controller firmware on engine MS/TP integration
              <select
                aria-label="Mixed controller firmware on engine MS/TP integration"
                value={
                  value.mixed_firmware_on_mstp === null
                    ? "unknown"
                    : String(value.mixed_firmware_on_mstp)
                }
                onChange={(event) =>
                  patch(
                    "mixed_firmware_on_mstp",
                    event.target.value === "unknown"
                      ? null
                      : event.target.value === "true",
                  )
                }
              >
                <option value="unknown">Unknown</option>
                <option value="true">
                  Declared mixed revisions on this integration
                </option>
                <option value="false">Not declared mixed</option>
              </select>
            </label>
            {text("source_sql_version", "Source computer SQL version")}
            {text(
              "destination_sql_version",
              "Destination computer SQL version",
            )}
          </div>
          <p>
            Destination CCT/PCT product and release, required packages and
            licenses come from the inventory JSON above. Bare major.minor
            release identifiers are evaluated; build/prerelease suffixes and
            future versions stay unknown. These declarations do not prove an
            installed or licensed toolchain.
          </p>
        </>
      )}
      {catalog && (
        <details>
          <summary>
            Reviewed operation-rule catalog ({catalog.ruleset.rules.length})
          </summary>
          <p>
            Ruleset SHA256 <code>{catalog.ruleset_sha256}</code>
          </p>
          {catalog.ruleset.rules.map((rule: Data) => (
            <section key={rule.id}>
              <h4>{rule.id}</h4>
              <p>{rule.criterion}</p>
              <p>
                Operations:{" "}
                {rule.operations
                  .map((op: string) => labels[op] || op)
                  .join(", ")}
              </p>
              {rule.sources.map((source: Data, index: number) => (
                <Source key={index} source={source} />
              ))}
            </section>
          ))}
        </details>
      )}
    </fieldset>
  );
}
export function JciReleaseRuleResults({ report }: { report: Data }) {
  const row = (label: string, content: ReactNode) => (
    <p>
      <b>{label}: </b>
      {content}
    </p>
  );
  return (
    <section aria-label="Documented release-rule results">
      <h3>Documented operation rules: {report.status}</h3>
      {row("Operation", labels[report.source.declarations.operation])}
      <p>{report.scope}</p>
      <p>
        Native execution: unavailable. Deployment approval: unavailable.
        Manufacturer tool executed: no.
      </p>
      {row(
        "Observed CAF Appl SW Version",
        report.source.observed_appl_sw_version ||
          "Unknown (not substituted for release mode)",
      )}
      {report.findings.map((finding: Data) => (
        <article key={finding.rule_id}>
          <h4>
            {finding.rule_id} · {finding.status}
          </h4>
          <p>{finding.detail}</p>
          <details>
            <summary>Rule source evidence</summary>
            {finding.sources.map((source: Data, index: number) => (
              <Source key={index} source={source} />
            ))}
          </details>
        </article>
      ))}
      <details>
        <summary>Unverified acceptance and source bindings</summary>
        <ul>
          {report.unverified.map((item: string) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        {row("CAF SHA256", <code>{report.source.caf_sha256}</code>)}
        {row("Ruleset SHA256", <code>{report.ruleset_sha256}</code>)}
        {row(
          "Release review content SHA256",
          <code>{report.content_sha256}</code>,
        )}
        <pre>{JSON.stringify(report.source, null, 2)}</pre>
      </details>
    </section>
  );
}
