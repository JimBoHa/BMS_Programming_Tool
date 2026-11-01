import { createContext } from "react";
import type { ControllerContext } from "./workflow";
import type { NativeDefaultRecoveryDocument } from "./nativeDefaultRecoveryContract";

export const NativeBooleanTransferContext = createContext<{
  controller?: ControllerContext | null;
  visible: boolean;
  fieldBusy: boolean;
  parentBusy: boolean;
  otherOperationBusy: boolean;
  recoveryDrafts: Map<string, NativeDefaultRecoveryDocument>;
  wireRecoveryDrafts: Map<string, NativeDefaultRecoveryDocument>;
  onBusy: (owner: string, busy: boolean) => void;
  onCaptured: (id: string) => void;
} | null>(null);
