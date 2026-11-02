export type PointNameWork = {
  name: string;
  capture: any;
  field: any;
  receipt: any;
};

export const emptyPointNameWork = (): PointNameWork => ({
  name: "",
  capture: null,
  field: null,
  receipt: null,
});

export const hasPointNameWork = (work: PointNameWork) =>
  Boolean(work.name || work.capture || work.field || work.receipt);

export const canRememberPointNameWork = (
  drafts: Map<string, PointNameWork>,
  key: string,
) => drafts.has(key) || drafts.size < 32;

// A new source must never silently discard another point's unfinished work.
export function rememberPointNameWork(
  drafts: Map<string, PointNameWork>,
  key: string,
  work: PointNameWork,
) {
  if (!hasPointNameWork(work)) {
    drafts.delete(key);
    return true;
  }
  if (!canRememberPointNameWork(drafts, key)) return false;
  drafts.set(key, work);
  return true;
}
