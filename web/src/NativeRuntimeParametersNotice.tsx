export function NativeRuntimeParametersNotice({
  parameters,
}: {
  parameters: any;
}) {
  const rows = parameters?.retained_runtime_parameters;
  if (!rows?.length) return null;
  return (
    <p role="note" aria-label="Read-only runtime timestamps">
      {rows.length} read-only binary event timestamp(s) stay in the original
      backup. They are not application defaults. Application transfers can
      change running event times; this change does not restore historical event
      timestamps.
    </p>
  );
}
