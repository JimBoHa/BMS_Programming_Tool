export type StepDurationDraft = { enabled: boolean; text: string | null };

export function inspectStepDuration(draft: StepDurationDraft, nominal: number) {
  if (!draft.enabled) return { seconds: nominal, error: "" };
  const text = (draft.text ?? "").trim();
  const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
  const value = decimal.test(text) ? Number(text) : NaN;
  if (!Number.isFinite(value) || value <= 0 || value > 60)
    return {
      seconds: null,
      error:
        "Enter a single-step duration greater than 0 and at most 60 seconds.",
    };
  return { seconds: value, error: "" };
}
