import { useState } from "react";
import { matchesBlock } from "./activityContracts";
import { isSourceNumber, numericToken, sourceStringify } from "./programSource";
import type { Block, BmsNode, Program } from "./types";

type Editor = "number" | "numbers" | "json";
type Owner = { key: string; node: string; parameter: string; editor: Editor };
type Draft = { owner: Owner; baseline: string; text: string; error: string };

export function parameterEditor(
  parameter: string,
  value: unknown,
): Editor | null {
  if (Array.isArray(value)) {
    if (parameter === "exceptions") return "json";
    return value.every(
      (item) => typeof item === "number" || isSourceNumber(item),
    )
      ? "numbers"
      : "json";
  }
  if (typeof value === "number" || isSourceNumber(value)) return "number";
  return value === null || typeof value === "object" ? "json" : null;
}

export function parameterOwner(
  program: Program,
  node: BmsNode,
  parameter: string,
  editor: Editor,
): Owner {
  return {
    node: node.id,
    parameter,
    editor,
    key: sourceStringify([
      program.id,
      program.target,
      node.id,
      node.kind,
      node.params.definition ?? null,
      node.value_type,
      node.unit,
      parameter,
      editor,
    ]),
  };
}

export function parameterBaseline(editor: Editor, value: any): string {
  return editor === "json"
    ? sourceStringify(value)
    : editor === "numbers"
      ? value.map(numericToken).join(",")
      : numericToken(value);
}

/** Transient text only. Accepted Program data and persisted recovery stay separate. */
export class ParameterDrafts {
  private entries = new Map<string, Draft>();

  read(owner: Owner, baseline: string, canonical: string) {
    const draft = this.entries.get(owner.key);
    return draft?.baseline === baseline
      ? draft
      : { text: canonical, error: "" };
  }

  write(
    owner: Owner,
    baseline: string,
    canonical: string,
    text: string,
    error: string,
  ) {
    if (text === canonical && !error) this.entries.delete(owner.key);
    else this.entries.set(owner.key, { owner, baseline, text, error });
  }

  /** Retire edits when an accepted source changes, even while its inspector is closed. */
  reconcile(program: Program, blocks: Block[]) {
    if (!this.entries.size) return;
    const nodes = new Map(program.nodes.map((node) => [node.id, node]));
    for (const [key, draft] of this.entries) {
      const node = nodes.get(draft.owner.node);
      const block = node && blocks.find((block) => matchesBlock(block, node));
      const parameters = block &&
        node && { ...block.parameters, ...node.params };
      const value = parameters?.[draft.owner.parameter];
      const editor = parameterEditor(draft.owner.parameter, value);
      if (
        !node ||
        !block ||
        !parameters ||
        !Object.hasOwn(parameters, draft.owner.parameter) ||
        editor !== draft.owner.editor ||
        parameterOwner(program, node, draft.owner.parameter, editor).key !==
          key ||
        parameterBaseline(editor, value) !== draft.baseline
      )
        this.entries.delete(key);
    }
  }
}

/** Read through the current owner synchronously: a selection change cannot paint old text. */
export function useParameterDraft(
  drafts: ParameterDrafts,
  owner: Owner,
  baseline: string,
  canonical: string,
) {
  const [, refresh] = useState(0);
  const current = drafts.read(owner, baseline, canonical);
  function write(
    text: string,
    error = "",
    accepted = baseline,
    display = canonical,
  ) {
    drafts.write(owner, accepted, display, text, error);
    refresh((value) => value + 1);
  }
  return { ...current, write };
}
