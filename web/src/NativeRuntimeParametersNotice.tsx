export function NativeRuntimeParametersNotice({
  parameters,
}: {
  parameters: any;
}) {
  if (!parameters) return null;
  const rows = parameters?.retained_runtime_parameters;
  return (
    <>
      <p role="note" aria-label="Runtime effects of application transfer">
        Application transfers can restart control. Runtime counters and
        calculated values can reset or change. Original backups retain their
        pre-transfer values; verification reports observed runtime changes
        separately from application configuration.
      </p>
      {!!rows?.length && (
        <p role="note" aria-label="Read-only runtime timestamps">
          {rows.length} read-only binary event timestamp(s) stay in the original
          backup. They are not application defaults. Application transfers can
          change running event times; this change does not restore historical
          event timestamps.
        </p>
      )}
    </>
  );
}
