import { useContext, useState } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeWireSourceCopy } from "./NativeWireSourceCopy";
import { NativeConnectionCopy } from "./NativeConnectionCopy";
import { NativeConnectionRemoval } from "./NativeConnectionRemoval";
import { connectionDraftKey } from "./nativeConnectionContract";
import { rememberWireDraft, type WireCopyDrafts } from "./nativeWireDrafts";
import type { NativeArchiveSource } from "./NativeRecords";
import type { ControllerContext } from "./workflow";

export function NativeGraphEdits(props: {
  source: NativeArchiveSource;
  record: Record<string, any>;
  controller?: ControllerContext | null;
  visible: boolean;
  drafts: WireCopyDrafts;
}) {
  const busy = useContext(NativeBooleanTransferContext)?.fieldBusy ?? false;
  const key = connectionDraftKey(props.source, props.record) + "/mode";
  const [mode, setMode] = useState(
    ["add", "remove"].includes(props.drafts.get(key) || "")
      ? props.drafts.get(key)!
      : "source",
  );
  const [error, setError] = useState("");
  return (
    <section aria-label="Native diagram edits" className="native-wire-copy">
      <label>
        Native diagram operation
        <select
          aria-label="Native diagram operation"
          value={mode}
          disabled={busy || !props.visible}
          onChange={(event) => {
            const value = event.target.value;
            if (value === "source") props.drafts.delete(key);
            else if (!rememberWireDraft(props.drafts, key, value)) {
              setError(
                "The 256 retained wire draft slots are full. Discard an older draft before changing this operation. No existing work was removed.",
              );
              return;
            }
            setError("");
            setMode(value);
          }}
        >
          <option value="source">Change existing source</option>
          <option value="add">Add matching connection</option>
          <option value="remove">Remove existing connection</option>
        </select>
      </label>
      {error && <p role="alert">{error}</p>}
      {/* Keep the existing transfer/recovery owner mounted when changing local tools. */}
      <div hidden={mode !== "source"}>
        <NativeWireSourceCopy
          {...props}
          visible={props.visible && mode === "source"}
        />
      </div>
      <div hidden={mode !== "add"}>
        <NativeConnectionCopy
          {...props}
          visible={props.visible && mode === "add"}
        />
      </div>
      <div hidden={mode !== "remove"}>
        <NativeConnectionRemoval
          {...props}
          visible={props.visible && mode === "remove"}
        />
      </div>
    </section>
  );
}
