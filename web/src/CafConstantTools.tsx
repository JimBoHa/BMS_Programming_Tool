import { useRef, useState, type ComponentProps } from "react";
import { ChevronDown } from "lucide-react";
import { CafConstantCopy } from "./CafConstantCopy";
import { constantKinds, type ConstantKind } from "./cafConstantContract";
import { creationHintFor } from "./cafCreatedCopy";
import { useCafReferenceLabels } from "./cafReferenceLabels";

/** Keep one active creation task; hidden type editors retain only local drafts. */
export function CafConstantTools(
  props: Omit<ComponentProps<typeof CafConstantCopy>, "kind">,
) {
  const checkpointEpoch = useRef(0);
  const available = (Object.keys(constantKinds) as ConstantKind[]).filter(
    (kind) =>
      props.diagram.blocks.some(
        (b: Record<string, any>) =>
          b.class_id === constantKinds[kind].classId &&
          b.class_version === "1.0",
      ),
  );
  const last = [...props.drafts.values()]
    .reverse()
    .find(
      (d) => d.archive === props.archive && d.diagram === props.diagram.ref,
    );
  const preferred = creationHintFor(props.creationHint, props.archive, {
    ref: props.diagram.ref,
    blocks: props.diagram.blocks,
  });
  const [chosen, setChosen] = useState<ConstantKind>(
    (preferred && available.includes(preferred.kind) ? preferred.kind : null) ||
      available.find((kind) =>
        props.diagram.blocks.some(
          (b: Record<string, any>) =>
            b.ref === last?.prototype &&
            b.class_id === constantKinds[kind].classId,
        ),
      ) ||
      available[0] ||
      "float",
  );
  const active = available.includes(chosen) ? chosen : available[0];
  const referenceLabels = useCafReferenceLabels(
    props.archive,
    props.diagram,
    props.reviewContext,
    available.length > 0 && !props.disabled,
  );
  const choiceLabel = available.some(
    (kind) =>
      kind === "comparison" ||
      kind === "math" ||
      kind === "timer" ||
      kind === "booleanLogic" ||
      kind === "reliability" ||
      kind === "multiplexer",
  )
    ? "Recorded block type"
    : "Constant type";
  if (!active) return null;
  return (
    <div>
      {available.length > 1 && (
        <label className="caf-constant-kind">
          {choiceLabel}
          <span className="caf-constant-select">
            <select
              aria-label={choiceLabel}
              value={active}
              disabled={props.disabled}
              onChange={(e) => {
                checkpointEpoch.current++;
                setChosen(e.target.value as ConstantKind);
              }}
            >
              {available.map((kind) => (
                <option value={kind} key={kind}>
                  {constantKinds[kind].label}
                </option>
              ))}
            </select>
            <ChevronDown size={16} aria-hidden="true" />
          </span>
        </label>
      )}
      {available.map((kind) => (
        <div key={kind} hidden={kind !== active}>
          <CafConstantCopy
            {...props}
            checkpointEpoch={checkpointEpoch}
            kind={kind}
            referenceLabels={referenceLabels}
            disabled={props.disabled || kind !== active}
          />
        </div>
      ))}
    </div>
  );
}
