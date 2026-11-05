import {
  terminalBase as legacyBase,
  terminalSource as legacySource,
  terminalReview as legacyReview,
  type TerminalBasis,
} from "./nativeTerminalCopyContract";
import type { NativeArchiveSource } from "./NativeRecords";
export {
  terminalArchive,
  terminalProposal,
  type TerminalBasis,
} from "./nativeTerminalCopyContract";

type Data = Record<string, any>;
export const terminalBase = (basis: TerminalBasis) => legacyBase(basis, true);
export const terminalSource = (
  v: Data,
  source: NativeArchiveSource,
  basis: TerminalBasis,
) => legacySource(v, source, basis, true);
export const terminalReview = async (
  document: { data: Data; blob: Blob },
  source: NativeArchiveSource,
  request: Data,
  loaded: Data,
  basis: TerminalBasis,
) => {
  try {
    return await legacyReview(
      document.data,
      source,
      request,
      loaded,
      basis,
      true,
      document.blob,
    );
  } catch {
    return false;
  }
};
