export type NativeIdentityWork = {
  capture: any;
  receipt: any;
  newName: string;
  number: string;
  recovery: any;
  rawImported?: {
    filename: string;
    file_sha256: string;
    receipt_id: string | null;
    recovery_origin_sha256: string | null;
  };
};
export const IDENTITY_DRAFT_LIMIT = 32;
export const emptyIdentityWork = (): NativeIdentityWork => ({
  capture: null,
  receipt: null,
  newName: "",
  number: "",
  recovery: null,
});
// A passive receipt is already durable in the local journal; viewing it is not a draft.
export const hasIdentityDraft = (work: NativeIdentityWork) =>
  Boolean(work.capture || work.newName || work.number || work.recovery);
export const canRememberIdentityWork = (
  drafts: Map<string, NativeIdentityWork>,
  key: string,
) => drafts.has(key) || drafts.size < IDENTITY_DRAFT_LIMIT;
export function rememberIdentityWork(
  drafts: Map<string, NativeIdentityWork>,
  key: string,
  work: NativeIdentityWork,
  pending = false,
) {
  if (!hasIdentityDraft(work) && !pending) {
    drafts.delete(key);
    return true;
  }
  if (!canRememberIdentityWork(drafts, key)) return false;
  drafts.set(key, {
    ...work,
    ...(work.rawImported ? { rawImported: { ...work.rawImported } } : {}),
  });
  return true;
}
export function releaseEmptyIdentityWork(
  drafts: Map<string, NativeIdentityWork>,
  key: string,
) {
  const work = drafts.get(key);
  if (work && !hasIdentityDraft(work)) drafts.delete(key);
}
export function identityDraftDocument(key: string, work: NativeIdentityWork) {
  const [connected, interfaceIdentity, address, device, router, dnet, kind] =
    JSON.parse(key);
  return {
    profile: "native-identity-local-draft/1",
    field_authority: false,
    selection: {
      connected_context: connected,
      interface_identity: interfaceIdentity,
      address,
      device,
      router: router || null,
      dnet: dnet ?? null,
      change_kind: kind || "instance",
    },
    new_name: work.newName,
    new_instance_text: work.number,
    capture_id: work.capture?.id ?? null,
    captured_target: work.capture?.target ?? null,
    snapshot_sha256: work.capture?.snapshot_evidence_sha256 ?? null,
    receipt_id:
      work.receipt?.intent?.id ?? work.rawImported?.receipt_id ?? null,
    recovery_origin_sha256:
      work.recovery?.data?.origin_sha256 ??
      work.rawImported?.recovery_origin_sha256 ??
      null,
    ...(work.rawImported
      ? {
          raw_imported: {
            filename: work.rawImported.filename,
            file_sha256: work.rawImported.file_sha256,
          },
        }
      : {}),
  };
}
