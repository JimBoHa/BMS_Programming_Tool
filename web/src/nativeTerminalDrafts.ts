import type { TerminalBasis } from "./nativeTerminalCopyContract";

export type TerminalDraft = {
  capture: string;
  basis: TerminalBasis;
  ref: string;
  destination: string;
};
export const blankTerminalDraft = (): TerminalDraft => ({
  capture: "",
  basis: "archive",
  ref: "",
  destination: "",
});
const drafts = new Map<string, TerminalDraft>();
export const terminalDraft = (owner: string) => ({
  ...(drafts.get(owner) ?? blankTerminalDraft()),
});
export function rememberTerminalDraft(owner: string, value: TerminalDraft) {
  if (!drafts.has(owner) && drafts.size >= 32) return false;
  if (
    !value.capture &&
    !value.ref &&
    !value.destination &&
    value.basis === "archive"
  )
    drafts.delete(owner);
  else drafts.set(owner, { ...value });
  return true;
}
export const discardTerminalDraft = (owner: string) => drafts.delete(owner);
