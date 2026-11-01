import { createContext } from "react";
import type { ControllerContext } from "./workflow";

export const NativeBooleanTransferContext = createContext<{
  controller?: ControllerContext | null;
  visible: boolean;
  fieldBusy: boolean;
  parentBusy: boolean;
  otherOperationBusy: boolean;
  onBusy: (owner: string, busy: boolean) => void;
  onCaptured: (id: string) => void;
} | null>(null);
