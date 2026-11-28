export const OBSERVED_DRAFT = "native-schedule-null-default-weekly-day-draft/1";
export const OBSERVED_RULES =
  "cdee8d2b48534ed4d6e34b7a7e0f7dbf65bc8ddd20934205457ad588e2904a90";
export const OBSERVED_WRITE =
  "native-schedule-reviewed-null-default-weekly-day-write/1";
export const OBSERVED_WRITE_RULES =
  "6a65f2bd3c78df2fddcd3a96be1830041d2a9265dd7617b8e09baf1ea0d483ac";
export const observedTypes = [
  "Boolean",
  "Unsigned",
  "Integer",
  "Enumerated",
  "Real",
  "Double",
];

export function observedDefaultDraft(value: any) {
  return (
    value?.profile === OBSERVED_DRAFT &&
    value.rules_sha256 === OBSERVED_RULES &&
    value.request?.draft_profile === OBSERVED_DRAFT &&
    value.source?.schedule_default_type === "Null" &&
    observedTypes.includes(value.source?.observed_native_type)
  );
}

export function observedWriteCapability(value: any) {
  return (
    value?.profile === OBSERVED_WRITE &&
    value.rules_sha256 === OBSERVED_WRITE_RULES &&
    value.draft_profile === OBSERVED_DRAFT &&
    value.draft_rules_sha256 === OBSERVED_RULES &&
    value.rules?.profile === OBSERVED_WRITE &&
    value.rules.draft_rules_sha256 === OBSERVED_RULES
  );
}
