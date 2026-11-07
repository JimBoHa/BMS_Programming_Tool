import { useContext, useEffect, useRef, useState } from "react";
import { randomUUID } from "./browserCrypto";
import { apiJsonDocument, apiKeepalive, saveBlob } from "./api";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import type { NativeArchiveSource } from "./NativeRecords";
import { controllerKey, type ControllerContext } from "./workflow";
import { matchingConnectionTarget } from "./nativeMatchingConnectionContract";
import {
  capacityBase,
  capacityObservation,
  capacitySource,
} from "./nativeCapacityContract";

type Data = Record<string, any>;
type Document = { data: Data; blob: Blob };
export function NativeCapacityEvidence({
  source,
  controller,
  visible,
}: {
  source: NativeArchiveSource;
  controller?: ControllerContext | null;
  visible: boolean;
}) {
  const context = useContext(NativeBooleanTransferContext),
    contextNow = useRef(context);
  contextNow.current = context;
  const [opened, setOpened] = useState(false),
    [life, setLife] = useState(0),
    [owned, setOwned] = useState(false);
  const otherBusy = !!context?.fieldBusy && !owned;
  const sourceKey = JSON.stringify(source);
  const owner = JSON.stringify([
    sourceKey,
    visible,
    opened,
    life,
    otherBusy,
    context?.workspaceGeneration,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
      controller.ownedCommands,
      controller.name,
      controller.model,
    ],
  ]);
  const ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true),
    present = useRef(true),
    surface = useRef(false);
  const active = useRef<{
      id: string;
      kind: "source" | "read";
      owner: string;
      epoch: number;
    } | null>(null),
    busyOwner = useRef("capacity-" + randomUUID());
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const [local, setLocal] = useState<{
      key: string;
      data: Data;
    } | null>(null),
    [observed, setObserved] = useState<{
      owner: string;
      epoch: number;
      document: Document;
    } | null>(null);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const ticket = epoch.current;
  const current = (key: string, generation: number) =>
    alive.current &&
    present.current &&
    surface.current &&
    visible &&
    document.visibilityState === "visible" &&
    contextNow.current?.visible !== false &&
    contextNow.current?.workspaceCurrent?.() !== false &&
    ownerNow.current === key &&
    epoch.current === generation;
  const shown =
    observed && current(observed.owner, observed.epoch) ? observed : null;
  const historical = local?.key === sourceKey ? local.data : null;
  const busy = pending && active.current !== null;
  const matching =
    !!controller && matchingConnectionTarget(source.target, controller);
  let config: Data | null = null;
  try {
    config = JSON.parse(controller?.interfaceKey || "null");
  } catch {}
  const connected =
    !!controller?.interfaceOpen &&
    controller.ownedCommands === 0 &&
    !!config?.local_address &&
    !config.transport &&
    !config.bbmd_address;
  const usable = current(owner, ticket) && !otherBusy && !busy;
  const cancel = () => {
    const run = active.current;
    if (run?.kind === "read")
      void apiKeepalive("/bacnet/controller/native-application/cancel", {
        operation_id: run.id,
      }).catch(() => {});
  };
  function retire() {
    epoch.current++;
    setObserved(null);
    setError("");
    cancel();
  }
  useEffect(() => {
    setObserved(null);
    setError("");
    cancel();
  }, [owner]);
  useEffect(() => {
    alive.current = true;
    const changed = (value: boolean) => {
      present.current = value;
      retire();
      setLife((v) => v + 1);
    };
    const hide = () => changed(false),
      show = () => changed(true),
      visibility = () => changed(document.visibilityState === "visible");
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      alive.current = false;
      epoch.current++;
      cancel();
      if (active.current?.kind === "read")
        contextNow.current?.onBusy(busyOwner.current, false);
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  async function run(kind: "source" | "read") {
    if (
      !usable ||
      active.current ||
      !current(owner, ticket) ||
      (kind === "read" && (!controller || !connected || !matching))
    )
      return;
    const work = {
      id: "capacity-" + randomUUID(),
      kind,
      owner: ownerNow.current,
      epoch: ++epoch.current,
    };
    active.current = work;
    setPending(true);
    setObserved(null);
    setError("");
    if (kind === "read") {
      setOwned(true);
      contextNow.current?.onBusy(busyOwner.current, true);
    }
    try {
      const query = {
        capture_id: source.capture_id,
        snapshot_sha256: source.snapshot_sha256,
      };
      const response = await apiJsonDocument(
        capacityBase + (kind === "source" ? "/source" : "/read"),
        kind === "source"
          ? query
          : {
              ...query,
              address: controller!.address,
              device: controller!.device,
              router: controller!.router || null,
              dnet: controller!.dnet ?? null,
              operation_id: work.id,
            },
      );
      if (!current(work.owner, work.epoch)) return;
      if (kind === "source") {
        if (!(await capacitySource(response.data, source)))
          throw Error("The retained size evidence differs from this source.");
        if (current(work.owner, work.epoch))
          setLocal({ key: sourceKey, data: response.data });
      } else {
        if (
          !(await capacityObservation(
            response.data,
            source,
            controller!,
            work.id,
          ))
        )
          throw Error(
            "The capacity evidence does not match the selected source, route, interface and native reply.",
          );
        if (current(work.owner, work.epoch)) {
          setLocal({
            key: sourceKey,
            data: response.data.source,
          });
          setObserved({
            owner: work.owner,
            epoch: work.epoch,
            document: response,
          });
        }
      }
    } catch (failure) {
      if (current(work.owner, work.epoch)) setError(String(failure));
    } finally {
      if (active.current === work) {
        active.current = null;
        if (alive.current) {
          setPending(false);
          setOwned(false);
        }
        if (kind === "read")
          contextNow.current?.onBusy(busyOwner.current, false);
      }
    }
  }
  return (
    <details
      className="native-wire-copy"
      aria-label="Native application size and capacity"
      open={opened}
      onToggle={(e) => {
        if (e.currentTarget.open !== opened) {
          surface.current = e.currentTarget.open;
          retire();
          setOpened(e.currentTarget.open);
        }
      }}
    >
      <summary
        onClick={(e) => {
          if (otherBusy || !visible) {
            e.preventDefault();
            return;
          }
          surface.current =
            !e.currentTarget.parentElement!.hasAttribute("open");
          retire();
          setLife((v) => v + 1);
        }}
      >
        Application size and capacity
      </summary>
      <p>
        Inspect the original retained File3 size. A separate read-only query
        observes the selected controller's reported application capacity.
      </p>
      <div className="button-row">
        <button
          className={!connected || !matching ? "primary" : ""}
          disabled={!usable}
          onClick={() => void run("source")}
        >
          Inspect retained application size
        </button>
        <button
          className={connected && matching && !shown ? "primary" : ""}
          disabled={!usable || !matching || !connected}
          onClick={() => void run("read")}
        >
          Read controller application capacity
        </button>
        {busy && <button onClick={retire}>Cancel capacity query</button>}
      </div>
      {!controller && (
        <p>
          Open a controller to request capacity. Retained file measurements
          remain available offline.
        </p>
      )}
      {controller && !matching && (
        <p>
          This retained backup belongs to another route or controller. Select
          its original controller before reading capacity.
        </p>
      )}
      {controller && !connected && (
        <p>
          Capacity queries require an open plain BACnet/IPv4 interface with no
          owned override.
        </p>
      )}
      {busy && (
        <p role="status">
          {active.current?.kind === "read"
            ? "Reading controller identity and File3 capacity…"
            : "Inspecting retained application bytes…"}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {historical && (
        <section aria-label="Retained application sizes">
          <p>
            Historical source: {source.target.device} · {source.target.address}
            {source.target.router
              ? ` via ${source.target.router} / DNET ${source.target.dnet}`
              : ""}
            .
          </p>
          <dl>
            <dt>Original retained File3</dt>
            <dd>
              {historical.archive_bytes} bytes ({historical.compression})
            </dd>
            <dt>Expanded native image</dt>
            <dd>{historical.expanded_bytes} bytes</dd>
            <dt>Native records / diagrams</dt>
            <dd>
              {historical.native_record_count} / {historical.diagram_count}
            </dd>
          </dl>
        </section>
      )}
      {shown && (
        <section aria-label="Observed controller application capacity">
          <p role="status">
            Controller capacity observed: {shown.document.data.capacity.bytes}{" "}
            bytes.
          </p>
          <p>
            Observed at {shown.document.data.observed_at}.{" "}
            {shown.document.data.comparison.archive_fits
              ? "This retained archive fits that reported capacity."
              : "This retained archive exceeds that reported capacity."}{" "}
            Headroom for this retained archive:{" "}
            {shown.document.data.comparison.headroom_for_retained_archive_bytes}{" "}
            bytes.
          </p>
          <p>
            The current program was not read. Saved settings are not merged; a
            fresh transfer can have a different size and must recheck capacity.
            These measurements do not estimate free memory, RAM, flash or scan
            time.
          </p>
          <button
            className="primary"
            disabled={!usable}
            onClick={() => {
              if (current(shown.owner, shown.epoch))
                saveBlob(
                  shown.document.blob,
                  "native-application-capacity.json",
                );
            }}
          >
            Save exact capacity evidence
          </button>
        </section>
      )}
    </details>
  );
}
