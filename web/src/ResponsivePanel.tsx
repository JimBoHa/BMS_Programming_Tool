import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Menu, PanelLeft, PanelRight, X } from "lucide-react";
import "./responsive-panel.css";

const COMPACT = "(max-width: 900px)";

/** Keep one mounted panel while changing only its desktop/mobile presentation. */
export function ResponsivePanel({
  name,
  panel,
  side = "left",
  triggerText,
  triggerLabel,
  closeLabel,
  retireKey,
  openSignal,
  closeOnSelector,
  disabled = false,
  error,
  context,
  children,
}: {
  name: string;
  panel:
    | "navigation"
    | "blocks"
    | "inspector"
    | "controllers"
    | "caf-properties";
  side?: "left" | "right";
  triggerText: string;
  triggerLabel: string;
  closeLabel: string;
  retireKey: string;
  openSignal?: string | null;
  closeOnSelector?: string;
  disabled?: boolean;
  error?: string;
  context?: string;
  children: ReactNode;
}) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [compact, setCompact] = useState(
    () => window.matchMedia(COMPACT).matches,
  );
  const [expanded, setExpanded] = useState(false);
  const source = useRef({ retireKey, openSignal });
  useEffect(() => {
    const query = window.matchMedia(COMPACT);
    const change = () => setCompact(query.matches);
    change();
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  useLayoutEffect(() => {
    const retired = source.current.retireKey !== retireKey;
    const selected = source.current.openSignal !== openSignal;
    source.current = { retireKey, openSignal };
    if (retired || !compact) setExpanded(false);
    else if (selected && openSignal !== undefined) setExpanded(!!openSignal);
  }, [retireKey, openSignal, compact]);
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element) return;
    const focused = element.contains(document.activeElement)
      ? (document.activeElement as HTMLElement)
      : null;
    if (!compact) {
      const modal = element.open && element.matches(":modal");
      if (modal) element.close();
      element.setAttribute("open", "");
      if (modal && focused) {
        const destination = focused.closest("[hidden]")
          ? element.querySelector<HTMLElement>(
              ".responsive-panel-content button:not([disabled]), .responsive-panel-content input:not([disabled]), .responsive-panel-content select:not([disabled])",
            )
          : focused;
        destination?.focus();
      }
    } else if (expanded) {
      // A desktop panel was nonmodal; explicitly close before entering top layer.
      if (element.open && !element.matches(":modal")) element.close();
      if (!element.open) element.showModal();
    } else if (element.open) {
      element.close();
      if (focused) trigger.current?.focus();
    }
  }, [compact, expanded]);
  useEffect(
    () => () => {
      if (dialog.current?.open) dialog.current.close();
    },
    [],
  );
  const Icon =
    panel === "navigation" ? Menu : side === "left" ? PanelLeft : PanelRight;
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="responsive-panel-trigger"
        data-panel={panel}
        hidden={!compact}
        disabled={disabled}
        aria-label={triggerLabel}
        aria-haspopup="dialog"
        aria-expanded={compact && expanded}
        aria-controls={id}
        onClick={() => setExpanded(true)}
      >
        <Icon size={18} />
        <span>{triggerText}</span>
      </button>
      <dialog
        id={id}
        ref={dialog}
        data-responsive-panel={panel}
        className={`responsive-panel ${compact ? "drawer" : "inline"} ${side}`}
        role={compact ? "dialog" : "presentation"}
        aria-label={compact ? name : undefined}
        aria-modal={compact && expanded ? true : undefined}
        onCancel={(event) => {
          event.preventDefault();
          setExpanded(false);
        }}
        onClose={(event) => {
          if (compact && !event.currentTarget.open) setExpanded(false);
        }}
        onKeyDown={(event) => {
          // Native modal focus containment does not stop application shortcuts
          // bubbling to window. Keep hidden graph save/delete/undo handlers inert.
          if (!compact) return;
          event.stopPropagation();
          if (event.key === "Tab") {
            const controls = Array.from(
              event.currentTarget.querySelectorAll<HTMLElement>(
                "button, a[href], input, select, textarea, summary, [tabindex], [contenteditable=true]",
              ),
            ).filter(
              (element) =>
                element.tabIndex >= 0 &&
                !element.matches(":disabled") &&
                element.getClientRects().length > 0 &&
                getComputedStyle(element).visibility !== "hidden" &&
                !element.closest('[hidden], [inert], [aria-hidden="true"]'),
            );
            if (!controls.length) {
              event.preventDefault();
              return;
            }
            // WebKit can skip button-only native tab stops on macOS. Use the
            // visible enabled controls consistently, including both boundaries.
            controls.sort(
              (a, b) =>
                (a.tabIndex > 0 ? a.tabIndex : Number.MAX_SAFE_INTEGER) -
                (b.tabIndex > 0 ? b.tabIndex : Number.MAX_SAFE_INTEGER),
            );
            const current = controls.indexOf(
              document.activeElement as HTMLElement,
            );
            const next =
              current < 0
                ? event.shiftKey
                  ? controls.length - 1
                  : 0
                : (current + (event.shiftKey ? -1 : 1) + controls.length) %
                  controls.length;
            event.preventDefault();
            controls[next].focus();
          }
        }}
        onClick={(event) => {
          if (!compact) return;
          if (event.target === event.currentTarget) {
            const box = event.currentTarget.getBoundingClientRect();
            if (
              event.clientX < box.left ||
              event.clientX > box.right ||
              event.clientY < box.top ||
              event.clientY > box.bottom
            )
              setExpanded(false);
          } else if (
            closeOnSelector &&
            event.target instanceof Element &&
            event.target.closest(closeOnSelector)
          )
            setExpanded(false);
        }}
      >
        <header className="responsive-panel-heading" hidden={!compact}>
          <h2>{name}</h2>
          <button
            type="button"
            aria-label={closeLabel}
            onClick={() => setExpanded(false)}
          >
            <X size={20} />
          </button>
        </header>
        {compact && context && (
          <p className="responsive-panel-context">{context}</p>
        )}
        {compact && error && (
          <p className="responsive-panel-error" role="alert">
            {error}
          </p>
        )}
        <div className="responsive-panel-content">{children}</div>
      </dialog>
    </>
  );
}
