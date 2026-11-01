import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import { api } from "./api";
import { NativeSignalDefaultCopy } from "./NativeSignalDefaultCopy";
import { controllerKey, type ControllerContext } from "./workflow";
import "./controller-application.css";
import { NativeRecords } from "./NativeRecords";

type RecordValue = Record<string, any>;
const base = "/bacnet/controller/application/";
const target = (controller: ControllerContext) => ({
  address: controller.address,
  device: controller.device,
  router: controller.router || null,
  dnet: controller.dnet ?? null,
});
const text = (value: any): string =>
  value == null
    ? "—"
    : typeof value === "object"
      ? (value.name ??
        (value.native_datatype && "value" in value
          ? text(value.value)
          : JSON.stringify(value)))
      : String(value);
function check(report: RecordValue, controller: ControllerContext) {
  if (controllerKey(report.target) !== controllerKey(controller))
    throw new Error("Application source differs from the selected controller.");
  const capabilities = report.operation_capabilities;
  if (
    capabilities &&
    (capabilities.source?.capture_id !== report.receipt?.id ||
      capabilities.source?.sha256 !== report.receipt?.sha256)
  )
    throw new Error("Operation support differs from the application capture.");
}

export function ControllerApplicationPanel({
  controller,
  connected,
  onVerified,
}: {
  controller: ControllerContext;
  connected: boolean;
  onVerified?: (when: string) => void;
}) {
  const [storedReport, setReport] = useState<{
    owner: string;
    value: RecordValue;
  } | null>(null);
  const [diagram, setDiagram] = useState<RecordValue | null>(null);
  const [ref, setRef] = useState(""),
    [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [values, setValues] = useState<RecordValue | null>(null),
    [liveError, setLiveError] = useState("");
  const generation = useRef(0),
    graphGeneration = useRef(0),
    valueGeneration = useRef(0);
  const verified = useRef(onVerified);
  verified.current = onVerified;
  const source = controllerKey(controller) + controller.interfaceKey;
  const report =
    connected && storedReport?.owner === source ? storedReport.value : null;
  const accept = (result: RecordValue) => {
    check(result, controller);
    setReport({ owner: source, value: result });
    setRef(result.application?.diagrams[0]?.ref ?? "");
    setDiagram(null);
    setSelected("");
  };
  useEffect(() => {
    const epoch = ++generation.current;
    setBusy(false);
    setReport(null);
    setDiagram(null);
    setRef("");
    setSelected("");
    setError("");
    if (!connected) return;
    void (async () => {
      try {
        const captures = await api(base + "captures", target(controller));
        if (epoch !== generation.current || !captures.length) return;
        const result = await api(base + "capture", {
          ...target(controller),
          capture_id: captures[0].id,
        });
        if (epoch === generation.current) accept(result);
      } catch (failure) {
        if (epoch === generation.current) setError(String(failure));
      }
    })();
    return () => {
      generation.current++;
    };
  }, [source, connected]);
  const read = async (file_object?: string) => {
    const epoch = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await api(base + "read", {
        ...target(controller),
        file_object: file_object ?? null,
      });
      if (epoch !== generation.current) return;
      accept(result);
      if (result.identity_verified)
        verified.current?.(result.receipt.received_at);
    } catch (failure) {
      if (epoch === generation.current) setError(String(failure));
    } finally {
      if (epoch === generation.current) setBusy(false);
    }
  };
  const capture = report?.receipt?.id;
  useEffect(() => {
    const epoch = ++graphGeneration.current;
    setDiagram(null);
    setSelected("");
    if (!capture || !ref) return;
    void api(base + "diagram", {
      ...target(controller),
      capture_id: capture,
      ref,
    })
      .then((result) => {
        if (epoch !== graphGeneration.current) return;
        check(result, controller);
        setDiagram(result.diagram);
      })
      .catch((failure) => {
        if (epoch === graphGeneration.current) setError(String(failure));
      });
    return () => {
      graphGeneration.current++;
    };
  }, [source, capture, ref]);
  const block = diagram?.blocks.find(
    (entry: RecordValue) => entry.ref === selected,
  );
  const defaultProperty = block?.properties.find(
    (prop: RecordValue) => prop.id === 3113 && prop.scalar?.datatype === "Real",
  );
  useEffect(() => {
    const epoch = ++valueGeneration.current;
    let timer: number | undefined;
    setValues(null);
    setLiveError("");
    if (!connected || !block?.object) return;
    const read = async () => {
      try {
        const result = await api("/bacnet/controller/properties", {
          ...target(controller),
          object_ids: [block.object],
          properties: [
            "present-value",
            "units",
            "status-flags",
            "reliability",
            "out-of-service",
          ],
        });
        if (epoch !== valueGeneration.current) return;
        check(result, controller);
        if (!result.identity_verified || !result.objects[0]?.identity_verified)
          throw new Error(
            result.errors.join(" ") ||
              "This native block does not expose a verified BACnet object at its recorded identifier.",
          );
        setValues(result);
        setLiveError("");
        verified.current?.(result.finished_at);
      } catch (failure) {
        if (epoch === valueGeneration.current) setLiveError(String(failure));
      } finally {
        if (epoch === valueGeneration.current)
          timer = window.setTimeout(() => void read(), 10000);
      }
    };
    void read();
    return () => {
      valueGeneration.current++;
      window.clearTimeout(timer);
    };
  }, [source, connected, selected, capture]);
  const nodes = useMemo(
    () =>
      (diagram?.blocks ?? []).map((block: RecordValue, index: number) => ({
        id: block.ref,
        position: block.layout
          ? { x: block.layout.x * 4, y: block.layout.y * 2 }
          : { x: (index % 6) * 360, y: Math.floor(index / 6) * 150 },
        data: { label: `${block.name}\n${block.object ?? block.class_name}` },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        selected: block.ref === selected,
        style: {
          width: 200,
          whiteSpace: "pre-line" as const,
          borderColor: "#247e82",
          background: block.ref === selected ? "#d4efec" : "#fff",
        },
      })),
    [diagram, selected],
  );
  const edges = useMemo(
    () =>
      (diagram?.connections ?? []).map((wire: RecordValue) => ({
        id: String(wire.index),
        source: wire.source_ref,
        target: wire.target_ref,
        label: `${wire.source_port} → ${wire.target_port}`,
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#39888a" },
      })),
    [diagram],
  );
  return (
    <section
      className="controller-application"
      aria-label="Native controller application"
    >
      <div className="native-application-heading">
        <div>
          <h3>Controller application</h3>
          <p>
            Read the controller’s published application file. Installed format
            readers supply actual blocks, connections and configured properties
            across models.
          </p>
        </div>
        <button disabled={!connected || busy} onClick={() => void read()}>
          {busy
            ? "Reading controller application…"
            : "Read controller application"}
        </button>
      </div>
      {busy && (
        <p role="status">
          Reading an existing application File through the selected controller
          route. A routed transfer may take one to two minutes.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {report?.message && <p role="status">{report.message}</p>}
      {report?.status === "select_application" && (
        <ul>
          {report.files.map((file: RecordValue) => (
            <li key={file.object_id}>
              <button disabled={busy} onClick={() => void read(file.object_id)}>
                {file.object_name} · {file.object_id}
              </button>
            </li>
          ))}
        </ul>
      )}
      {report?.application && (
        <>
          <p className="native-application-source">
            Controller file snapshot · {report.receipt.metadata.object_name} ·{" "}
            {report.receipt.target.object_id} · captured{" "}
            {report.receipt.received_at}. Refresh to read subsequent application
            changes.
          </p>
          <p>
            {report.application.record_count} native records ·{" "}
            {report.application.diagrams.length} readable diagrams. General
            native logic generation remains unavailable. Supported local edits
            appear beside the captured property.
          </p>
          {report.operation_capabilities && (
            <details
              className="application-operation-support"
              aria-label="Controller application operation support"
            >
              <summary>Operation support for this capture</summary>
              <p>
                Source-qualified means installed software recognizes this file.
                Connected changes require their separate commissioning review.
                This inspection prepares no controller write.
              </p>
              <p>
                Captured firmware:{" "}
                {text(report.receipt.device_identity["firmware-revision"])}.
                {report.operation_capabilities.native_identity && (
                  <>
                    {" "}
                    Native ACS code:{" "}
                    {text(
                      report.operation_capabilities.native_identity
                        .format_versions.acs,
                    )}
                    . Native DMCS code:{" "}
                    {text(
                      report.operation_capabilities.native_identity
                        .format_versions.dmcs,
                    )}
                    .
                  </>
                )}{" "}
                These version namespaces are separate.
              </p>
              <div className="application-operation-table">
                <table>
                  <thead>
                    <tr>
                      <th>Operation</th>
                      <th>Support</th>
                      <th>Evidence and next step</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.operation_capabilities.operations.map(
                      (row: RecordValue) => (
                        <tr key={row.id} data-operation={row.id}>
                          <th scope="row">{row.operation}</th>
                          <td>{row.status.replaceAll("-", " ")}</td>
                          <td>
                            <p>{row.basis}</p>
                            <p>{row.next_step}</p>
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </details>
          )}

          {connected &&
            controllerKey(report.target) === controllerKey(controller) &&
            report.application.capabilities?.record_inspection && (
              <NativeRecords
                key={source + report.receipt.id}
                controller={controller}
                capture={report.receipt}
              />
            )}
          <label>
            Application diagram
            <select
              aria-label="Controller application diagram"
              disabled={busy}
              value={ref}
              onChange={(event) => setRef(event.target.value)}
            >
              {report.application.diagrams.map((row: RecordValue) => (
                <option key={row.ref} value={row.ref}>
                  {row.name} · {row.ref.split(".").at(-1)} · {row.blocks} blocks
                  / {row.connections} connections
                </option>
              ))}
            </select>
          </label>
          {diagram && (
            <>
              <p>
                {diagram.native_layout
                  ? "Native block positions, scaled for readability."
                  : "This diagram has no stored positions; blocks are arranged for readability."}{" "}
                Wires use the recorded source and destination property numbers.
                Select a block to inspect its configuration and exposed live
                value.
              </p>
              <div
                className="native-controller-diagram"
                aria-label="Actual native program diagram"
              >
                <ReactFlowProvider key={capture + ref}>
                  <ReactFlow
                    key={capture + ref}
                    nodes={nodes}
                    edges={edges}
                    fitView
                    nodesDraggable={false}
                    nodesConnectable={false}
                    deleteKeyCode={null}
                    onNodeClick={(_, node) => setSelected(node.id)}
                    minZoom={0.1}
                    maxZoom={3}
                  >
                    <Background />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </ReactFlowProvider>
              </div>
              <label>
                Select a program block
                <select
                  aria-label="Controller program block"
                  value={selected}
                  onChange={(event) => setSelected(event.target.value)}
                >
                  <option value="">Select a block…</option>
                  {diagram.blocks.map((row: RecordValue) => (
                    <option key={row.ref} value={row.ref}>
                      {row.index + 1}. {row.name} · {row.object ?? row.ref}
                    </option>
                  ))}
                </select>
              </label>
              {block && (
                <section aria-label="Actual native block configuration">
                  <h4>
                    {block.name} · {block.object}
                  </h4>
                  <p>
                    {block.ref} · {block.class_name}
                  </p>
                  <table>
                    <thead>
                      <tr>
                        <th>Configured property</th>
                        <th>Native value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {block.properties.map((prop: RecordValue) => (
                        <tr key={prop.id}>
                          <td>
                            {prop.name} ({prop.id})
                          </td>
                          <td>
                            {prop.scalar
                              ? text(prop.scalar.value)
                              : "Structured native value · evidence retained"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {report.signal_default_copy?.candidate_refs?.includes(
                    block.ref,
                  ) &&
                    defaultProperty && (
                      <NativeSignalDefaultCopy
                        key={JSON.stringify([
                          source,
                          capture,
                          block.ref,
                          defaultProperty.encoded_sha256,
                        ])}
                        controller={controller}
                        capture={capture}
                        sha256={report.receipt.sha256}
                        block={block}
                        property={defaultProperty}
                      />
                    )}
                  <h4>Live BACnet value</h4>
                  <p>
                    Read from the selected controller when this block exposes a
                    readable BACnet object. Archive defaults above are
                    configuration.
                  </p>
                  {liveError && (
                    <p role="alert">
                      {liveError} Previously read values remain last known.
                    </p>
                  )}
                  {values && (
                    <>
                      <p>Read at {values.finished_at}</p>
                      <dl>
                        {Object.entries(values.objects[0].properties)
                          .filter(([name]) => name !== "object-identifier")
                          .map(([name, row]: [string, any]) => (
                            <div key={name}>
                              <dt>{name}</dt>
                              <dd>
                                {row.status === "ok"
                                  ? text(row.value)
                                  : `Unavailable (${row.error || row.status})`}
                              </dd>
                            </div>
                          ))}
                      </dl>
                    </>
                  )}
                </section>
              )}
            </>
          )}
          {!!report.application.errors.length && (
            <details>
              <summary>
                {report.application.errors.length} unrecognized native record or
                diagram detail(s)
              </summary>
              <pre>{JSON.stringify(report.application.errors, null, 2)}</pre>
            </details>
          )}
          <details>
            <summary>Application source evidence</summary>
            <p>SHA-256 {report.receipt.sha256}</p>
            <pre>
              {JSON.stringify(
                {
                  target: report.target,
                  file: report.receipt.metadata,
                  consistency: report.receipt.consistency,
                },
                null,
                2,
              )}
            </pre>
          </details>
        </>
      )}
    </section>
  );
}
