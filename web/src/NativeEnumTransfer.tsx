import { useContext, useId } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeDefaultTransfer } from "./NativeDefaultTransfer";

type Data = Record<string, any>;
export function NativeEnumTransfer({
  source,
  field,
  proposal,
}: {
  source: Data;
  field: Data;
  proposal: Data | null;
}) {
  const context = useContext(NativeBooleanTransferContext),
    owner = useId();
  if (!context) return null;
  if (!field.saved_storage)
    return (
      <p>
        No selected fixed Enum slot is recorded. Local file copies remain
        available; this source cannot prepare an Enum controller transfer.
      </p>
    );
  return (
    <>
      <p>
        Enum code membership and state meanings remain unverified. Check the
        intended numeric code against the controller sequence before reviewing a
        transfer.
      </p>
      <NativeDefaultTransfer
        enumDefault
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
    </>
  );
}
