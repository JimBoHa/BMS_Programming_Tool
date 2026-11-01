import { useContext, useId } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeDefaultTransfer } from "./NativeDefaultTransfer";

type Data = Record<string, any>;
export function NativeBooleanTransfer({
  source,
  field,
  proposal,
}: {
  source: Data;
  field: Data;
  proposal: Data;
}) {
  const context = useContext(NativeBooleanTransferContext),
    owner = useId();
  if (!context) return null;
  if (!context.controller)
    return (
      <p>
        Open and verify the intended controller to review a Boolean transfer.
        This local compilation prepares no controller change.
      </p>
    );
  return (
    <NativeDefaultTransfer
      booleanDefault
      controller={context.controller}
      source={source}
      field={field}
      proposal={proposal}
      visible={context.visible}
      parentBusy={context.parentBusy}
      otherOperationBusy={context.otherOperationBusy}
      onBusy={(busy) => context.onBusy(owner, busy)}
      onCaptured={context.onCaptured}
    />
  );
}
