import {
  Copy,
  Trash2,
  Layers,
  AlignLeft,
  AlignStartHorizontal,
} from "lucide-react";
import type { BmsNode } from "./types";

export function SelectionPanel({
  nodes,
  onSelect,
  onCopy,
  onDuplicate,
  onDelete,
  onAlign,
}: {
  nodes: BmsNode[];
  onSelect: (id: string) => void;
  onCopy: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onAlign: (axis: "x" | "y") => void;
}) {
  return (
    <aside className="inspector selection-panel">
      <div className="panel-heading">
        <Layers size={16} /> SELECTION
      </div>
      <div className="inspector-body">
        <h3>{nodes.length} blocks selected</h3>
        <p className="help-text">
          Shift-click blocks to add or remove them. Drag any selected block to
          move the group. Copy and duplicate preserve wires within the
          selection.
        </p>
        <div className="button-row">
          <button onClick={onCopy}>
            <Copy size={14} /> Copy
          </button>
          <button onClick={onDuplicate}>Duplicate selection</button>
        </div>
        <div className="button-row">
          <button onClick={() => onAlign("x")}>
            <AlignLeft size={14} /> Align left
          </button>
          <button onClick={() => onAlign("y")}>
            <AlignStartHorizontal size={14} /> Align top
          </button>
        </div>
        <button className="danger" onClick={onDelete}>
          <Trash2 size={14} /> Delete selection
        </button>
        <div className="small-heading">SELECTED BLOCKS</div>
        {nodes.map((n) => (
          <button
            className="selection-member"
            key={n.id}
            onClick={() => onSelect(n.id)}
          >
            {n.label || n.id}
            <small>{n.kind}</small>
          </button>
        ))}
        <p className="help-text">
          ⌘/Ctrl+A selects all. ⌘/Ctrl+C and V copy/paste within this editor.
          ⌘/Ctrl+D duplicates. Undo restores a whole group edit.
        </p>
      </div>
    </aside>
  );
}
