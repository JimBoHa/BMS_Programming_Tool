import { useContext, useState } from "react";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { ChevronDown } from "lucide-react";
import {
  BooleanCopyEditor,
  type BooleanCopyDrafts,
} from "./NativeBooleanCopyEditor";
import { NativeEffectiveBooleanCopy } from "./NativeEffectiveBooleanCopy";
import type { NativeArchiveSource } from "./NativeRecords";
export type { BooleanCopyDrafts } from "./NativeBooleanCopyEditor";

export function NativeBooleanDefaultCopy(props: {
  source: NativeArchiveSource;
  field: {
    ref: string;
    class_id: number;
    encoded_sha256: string;
    value: boolean;
  };
  drafts: BooleanCopyDrafts;
}) {
  const [mode, setMode] = useState("archive");
  const fieldBusy =
    useContext(NativeBooleanTransferContext)?.fieldBusy ?? false;
  return (
    <div className="native-boolean-copy-source">
      <label>
        Boolean default source
        <span className="native-compiler-select">
          <select
            aria-label="Boolean default source"
            value={mode}
            disabled={fieldBusy}
            onChange={(event) => setMode(event.target.value)}
          >
            <option value="archive">Original archive value</option>
            <option value="effective">Merge retained saved settings</option>
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </span>
      </label>
      {mode === "archive" ? (
        <BooleanCopyEditor key="archive" {...props} />
      ) : (
        <NativeEffectiveBooleanCopy key="effective" {...props} />
      )}
    </div>
  );
}
