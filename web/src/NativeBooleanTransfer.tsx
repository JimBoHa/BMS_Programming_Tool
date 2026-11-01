import { useContext, useId } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeDefaultTransfer } from "./NativeDefaultTransfer";
import type { NativeDefaultRecoveryDocument } from "./nativeDefaultRecoveryContract";

type Data = Record<string, any>;
export function NativeBooleanTransfer({
  source,
  field,
  proposal,
  recoveryDraft,
  onRecoveryPrepared,
}: {
  source: Data;
  field: Data;
  proposal: Data;
  recoveryDraft?: NativeDefaultRecoveryDocument | null;
  onRecoveryPrepared?: (document: NativeDefaultRecoveryDocument) => void;
}) {
  const context = useContext(NativeBooleanTransferContext),
    owner = useId();
  if (!context) return null;
  return (
    <>
      {!context.controller && (
        <p>
          Open and verify the intended controller to review a Boolean transfer.
          This local compilation prepares no controller change.
        </p>
      )}
      <NativeDefaultTransfer
        booleanDefault
        controller={context.controller}
        source={source}
        field={field}
        proposal={proposal}
        visible={context.visible}
        parentBusy={context.parentBusy}
        otherOperationBusy={context.otherOperationBusy}
        recoveryDraft={recoveryDraft}
        onRecoveryPrepared={onRecoveryPrepared}
        onBusy={(busy) => context.onBusy(owner, busy)}
        onCaptured={context.onCaptured}
      />
    </>
  );
}
