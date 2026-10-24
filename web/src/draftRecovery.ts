import { sourceStringify } from "./programSource";
import type { Program } from "./types";

/** Per-key browser recovery; failed primary writes never clear the prior macro copy. */
export function persistDraftRecovery(
  storage: Pick<Storage, "setItem" | "removeItem">,
  program: Program,
  macroEdit: { parent: Program; definition: string } | null,
): void {
  if (macroEdit) {
    const value = sourceStringify({
      parent: macroEdit.parent,
      definition: macroEdit.definition,
      draft: program,
    });
    storage.setItem("bms-studio-macro-edit-v1", value);
  } else {
    const value = sourceStringify(program);
    storage.setItem("bms-studio-draft-v1", value);
    storage.removeItem("bms-studio-macro-edit-v1");
  }
}
