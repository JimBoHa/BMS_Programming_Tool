import { sha256Digest } from "./browserCrypto";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { api, apiJsonDocument, apiBlobDocument, saveBlob } from "./api";
import { controllerKey, type ControllerContext } from "./workflow";
import { NativeDefaultTransfer } from "./NativeDefaultTransfer";
import { NativeBackupInspection } from "./NativeBackupInspection";
import { NativeBackupComparison } from "./NativeBackupComparison";
import { NativeBooleanTransferContext } from "./NativeBooleanTransferContext";
import { NativeDefaultWireCompiler } from "./NativeDefaultWireCompiler";
import type { NativeDefaultRecoveryDocument } from "./nativeDefaultRecoveryContract";
import "./native-signal-compiler.css";

const base = "/bacnet/controller/native-application/signal-default";
const profile = "native-effective-signal-default-compiler/1";
const prefix = "bms-effective-native-default/1/";
const numberText = (value: number) =>
  Object.is(value, -0) ? "-0" : String(value);
const digest = async (blob: Blob) =>
  Array.from(
    new Uint8Array(await sha256Digest(await blob.arrayBuffer())),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
type Data = Record<string, any>;

export function NativeSignalCompiler({
  controller,
  visible = true,
  parentBusy = false,
  onBusyChange,
}: {
  controller?: ControllerContext | null;
  visible?: boolean;
  parentBusy?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const context = JSON.stringify([
    visible,
    controller
      ? [
          controllerKey(controller),
          controller.interfaceKey,
          controller.interfaceOpen,
        ]
      : null,
  ]);
  const [sources, setSources] = useState<Data[]>([]),
    [choice, setChoice] = useState("");
  const booleanDrafts = useRef(new Map<string, boolean>());
  const enumRecoveries = useRef(
    new Map<string, NativeDefaultRecoveryDocument>(),
  );
  const booleanRecoveries = useRef(
    new Map<string, NativeDefaultRecoveryDocument>(),
  );
  const wireDrafts = useRef(new Map<string, string>());
  const combinedDrafts = useRef(new Map<string, string>());
  const wireRecoveries = useRef(
    new Map<string, NativeDefaultRecoveryDocument>(),
  );
  const [loaded, setLoaded] = useState<Data | null>(null),
    [fieldRef, setFieldRef] = useState("");
  const [search, setSearch] = useState(""),
    [drafts, setDrafts] = useState<Record<string, string>>({});
  const [review, setReview] = useState<{
    data: Data;
    blob: Blob;
    owner: string;
    ticket: number;
  } | null>(null);
  const [error, setError] = useState(""),
    [storageError, setStorageError] = useState(""),
    [localBusy, setBusy] = useState(false);
  const [transferBusy, setTransferBusy] = useState(false);
  const [booleanTransferBusy, setBooleanTransferBusy] = useState(false);
  const [combinedActive, setCombinedActive] = useState(false);
  const busyOwners = useRef(new Set<string>());
  function transferBusyChanged(owner: string, value: boolean) {
    if (value) busyOwners.current.add(owner);
    else busyOwners.current.delete(owner);
    setTransferBusy(busyOwners.current.has("real"));
    setBooleanTransferBusy(
      [...busyOwners.current].some((key) => key !== "real"),
    );
    onBusyChange?.(busyOwners.current.size > 0);
  }
  const [pendingSource, setPendingSource] = useState("");
  const [recovery, setRecovery] =
    useState<NativeDefaultRecoveryDocument | null>(null);
  const recoveryPanel = useRef<HTMLElement>(null),
    pendingRecoveryFocus = useRef<string | null>(null);
  const busy = localBusy || transferBusy || booleanTransferBusy || parentBusy;
  const alive = useRef(true),
    epoch = useRef(0),
    contextNow = useRef(context),
    choiceNow = useRef(choice);
  contextNow.current = context;
  choiceNow.current = choice;
  const sourceEpoch = useRef(0),
    sourceOwner = JSON.stringify([context, choice]),
    sourceOwnerNow = useRef(sourceOwner);
  if (sourceOwnerNow.current !== sourceOwner) {
    sourceOwnerNow.current = sourceOwner;
    sourceEpoch.current++;
  }
  const source = loaded?.capture_id === choice ? loaded : null;
  const field = source?.fields.find((row: Data) => row.ref === fieldRef);
  const shownRecovery =
    recovery &&
    source &&
    recovery.data.origin.current_capture_id === source.capture_id &&
    recovery.data.origin.current_snapshot_sha256 === source.snapshot_sha256 &&
    recovery.data.origin.record_ref === fieldRef
      ? recovery
      : null;
  const activeRecovery = shownRecovery?.data.proposal ? shownRecovery : null;
  useLayoutEffect(() => {
    const pending = pendingRecoveryFocus.current;
    pendingRecoveryFocus.current = null;
    if (pending && visible && shownRecovery?.data.origin_sha256 === pending) {
      recoveryPanel.current?.focus({ preventScroll: true });
      recoveryPanel.current?.scrollIntoView({
        block: "nearest",
        inline: "nearest",
      });
    }
  });
  const fieldTransferSourceActive =
    !!controller?.interfaceOpen &&
    !!source &&
    controllerKey(controller) ===
      controllerKey({ ...source.target, device: source.device });
  const draftKey =
    source && field
      ? prefix +
        JSON.stringify([
          source.snapshot_sha256,
          field.ref,
          field.encoded_sha256,
        ])
      : "";
  const value = activeRecovery
    ? activeRecovery.data.proposal.value_text
    : draftKey && drafts[draftKey] !== undefined
      ? drafts[draftKey]
      : field
        ? numberText(field.effective_value)
        : "";
  const owner = JSON.stringify([
    context,
    choice,
    source?.snapshot_sha256,
    fieldRef,
    field?.encoded_sha256,
    value,
    shownRecovery?.data.origin_sha256,
  ]);
  const ownerNow = useRef(owner);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const shown =
    review?.owner === owner && review.ticket === epoch.current ? review : null;
  const current = (ticket: number, key: string) =>
    alive.current && epoch.current === ticket && ownerNow.current === key;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
      sourceEpoch.current++;
    };
  }, []);
  async function refresh() {
    const key = contextNow.current;
    setError("");
    try {
      const result = await api(base + "/sources");
      if (
        result.profile !== profile ||
        !Array.isArray(result.sources) ||
        result.sources.length > 128
      )
        throw new Error("Unsupported retained native backup list.");
      if (alive.current && key === contextNow.current)
        setSources(result.sources);
    } catch (failure) {
      if (alive.current && key === contextNow.current)
        setError(String(failure));
    }
  }
  useEffect(() => {
    if (visible) void refresh();
  }, [context, visible]);
  useEffect(() => {
    if (visible && pendingSource && pendingSource === choice) {
      setPendingSource("");
      void open();
    }
  }, [visible, pendingSource, choice]);
  async function open() {
    const selected = choice,
      key = contextNow.current,
      ticket = ++sourceEpoch.current;
    epoch.current++;
    setLoaded(null);
    setFieldRef("");
    setReview(null);
    setError("");
    setBusy(true);
    try {
      const data = await api(base + "/source", { capture_id: selected });
      if (
        data.profile !== profile ||
        data.capture_id !== selected ||
        !/^[a-f0-9]{64}$/.test(data.snapshot_sha256 || "") ||
        !Array.isArray(data.fields) ||
        data.fields.length > 4096 ||
        typeof data.device !== "string" ||
        typeof data.target?.address !== "string" ||
        typeof data.identity?.["object-name"] !== "string" ||
        !Number.isInteger(data.parameter_merge?.matched_parameters) ||
        !Array.isArray(data.parameter_merge?.changed_parameters) ||
        data.fields.some(
          (row: Data) =>
            typeof row.ref !== "string" ||
            ![526, 527].includes(row.class_id) ||
            row.property !== 3113 ||
            !/^[a-f0-9]{64}$/.test(row.encoded_sha256 || "") ||
            !Number.isFinite(row.archive_value) ||
            !Number.isFinite(row.effective_value) ||
            !/^[a-f0-9]{8}$/.test(row.archive_bits || "") ||
            !/^[a-f0-9]{8}$/.test(row.effective_bits || ""),
        ) ||
        new Set(data.fields.map((row: Data) => row.ref)).size !==
          data.fields.length
      )
        throw new Error("Unsupported or mismatched native compiler source.");
      if (
        alive.current &&
        contextNow.current === key &&
        choiceNow.current === selected &&
        sourceEpoch.current === ticket
      ) {
        const restored: Record<string, string> = {};
        try {
          for (const row of data.fields) {
            const storageKey =
              prefix +
              JSON.stringify([
                data.snapshot_sha256,
                row.ref,
                row.encoded_sha256,
              ]);
            const saved = sessionStorage.getItem(storageKey);
            if (saved !== null && saved.length <= 128)
              restored[storageKey] = saved;
          }
          setStorageError("");
        } catch {
          setStorageError(
            "Browser draft storage is unavailable. Keep this view open to retain text.",
          );
        }
        if (
          new Set([...Object.keys(restored), ...Object.keys(drafts)]).size > 64
        )
          throw new Error(
            "Opening this source would exceed 64 retained native drafts. Discard older field drafts first; no text was removed.",
          );
        setDrafts((previous) => ({ ...restored, ...previous }));
        setLoaded(data);
        setSearch("");
      }
    } catch (failure) {
      if (
        alive.current &&
        contextNow.current === key &&
        choiceNow.current === selected &&
        sourceEpoch.current === ticket
      )
        setError(String(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  function edit(text: string) {
    if (!(draftKey in drafts) && Object.keys(drafts).length >= 64) {
      setStorageError(
        "64 native field drafts are retained. Discard a saved field draft before editing another field.",
      );
      return;
    }
    epoch.current++;
    setReview(null);
    setError("");
    setDrafts((previous) => ({ ...previous, [draftKey]: text }));
    try {
      const keys = Object.keys(sessionStorage).filter(
        (key) => key.startsWith(prefix) && key !== draftKey,
      );
      if (keys.length >= 64) {
        setStorageError(
          "Browser native draft storage is full. This text remains in this view; discard older drafts to free space.",
        );
        return;
      }
      sessionStorage.setItem(draftKey, text);
      setStorageError("");
    } catch {
      setStorageError(
        "Browser draft storage is unavailable. Keep this view open to retain text.",
      );
    }
  }
  function discard() {
    epoch.current++;
    setReview(null);
    setError("");
    if (shownRecovery) {
      setRecovery(null);
      return;
    }
    setDrafts((previous) => {
      const copy = { ...previous };
      delete copy[draftKey];
      return copy;
    });
    try {
      sessionStorage.removeItem(draftKey);
      setStorageError("");
    } catch {
      setStorageError(
        "Browser draft storage is unavailable; the in-memory field draft was discarded.",
      );
    }
  }
  const body =
    source && field
      ? {
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
          record_ref: field.ref,
          encoded_sha256: field.encoded_sha256,
          value_text: value,
        }
      : null;
  async function compile() {
    if (!body) return;
    const ticket = ++epoch.current,
      key = ownerNow.current;
    setReview(null);
    setError("");
    setBusy(true);
    try {
      const result = await apiJsonDocument(base + "/preview", body);
      const data = result.data;
      if (
        data.profile !== profile ||
        !/^[a-f0-9]{64}$/.test(data.review_sha256 || "") ||
        !Object.entries(body).every(
          ([name, input]) => data.request?.[name] === input,
        ) ||
        data.device !== source?.device ||
        !["address", "router", "dnet"].every(
          (name) => data.target?.[name] === source?.target[name],
        ) ||
        data.compilation?.profile !== profile ||
        data.compilation.controller_write !== false ||
        data.compilation.field_transfer_enabled !== false ||
        data.compilation.selected_edit?.record_ref !== field?.ref ||
        data.compilation.selected_edit?.encoded_sha256 !==
          field?.encoded_sha256 ||
        data.compilation.selected_edit?.before_bits !== field?.effective_bits ||
        !/^[a-f0-9]{8}$/.test(
          data.compilation.selected_edit?.after_bits || "",
        ) ||
        !Number.isFinite(data.compilation.selected_edit?.stored_value) ||
        !/^[a-f0-9]{64}$/.test(data.compilation.compiled_sha256 || "")
      )
        throw new Error(
          "Native compiler review does not match this source and proposal.",
        );
      if (current(ticket, key))
        setReview({ data, blob: result.blob, owner: key, ticket });
    } catch (failure) {
      if (current(ticket, key)) setError(String(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function save() {
    if (!shown || !body) return;
    const ticket = epoch.current,
      key = ownerNow.current;
    setError("");
    setBusy(true);
    try {
      const result = await apiBlobDocument(base + "/export", {
        ...body,
        review_sha256: shown.data.review_sha256,
      });
      if (
        result.headers.get("X-Studio-Snapshot-Sha256") !==
          source?.snapshot_sha256 ||
        result.headers.get("X-Studio-Review-Sha256") !==
          shown.data.review_sha256 ||
        result.headers.get("X-Studio-Artifact-Sha256") !==
          shown.data.compilation.compiled_sha256 ||
        (await digest(result.blob)) !== shown.data.compilation.compiled_sha256
      )
        throw new Error(
          "Compiled native bytes do not match the reviewed snapshot and digest.",
        );
      if (current(ticket, key))
        saveBlob(result.blob, "native-effective-default.moi");
    } catch (failure) {
      if (current(ticket, key)) setError(String(failure));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  const fields =
    source?.fields.filter((row: Data) =>
      row.ref.toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  if (field && !fields.some((row: Data) => row.ref === field.ref))
    fields.push(field);
  const combinedTicket = epoch.current,
    combinedSourceTicket = sourceEpoch.current;
  return (
    <section
      className="native-effective-compiler"
      aria-label="Native backup default compiler"
    >
      <h1>Native backup defaults</h1>
      <p>
        Compile one existing Real default from a retained native application
        backup, keeping its saved settings. These are snapshot values; current
        controller values are not queried.
      </p>
      <div className="native-compiler-source">
        <label>
          Retained native backup
          <span className="native-compiler-select">
            <select
              aria-label="Retained native backup"
              value={choice}
              disabled={busy}
              onChange={(event) => {
                epoch.current++;
                setChoice(event.target.value);
                setReview(null);
                setError("");
              }}
            >
              <option value="">Select a retained source</option>
              {sources.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.identity?.["object-name"] || row.device} ·{" "}
                  {row.target?.address} · {row.captured_at} ·{" "}
                  {row.id.slice(0, 8)}
                </option>
              ))}
            </select>
            <ChevronDown aria-hidden="true" size={16} />
          </span>
        </label>
        <div className="button-row">
          <button disabled={!choice || busy} onClick={() => void open()}>
            Open retained backup
          </button>
          <button disabled={busy} onClick={() => void refresh()}>
            Refresh native backups
          </button>
        </div>
        {!sources.length && (
          <p>
            No native backups retained. Capture the verified controller’s native
            application backup in its identity workflow first.
          </p>
        )}
      </div>
      {source && (
        <>
          <div
            className="native-compiler-source"
            aria-label="Native compiler snapshot source"
          >
            <strong>{source.identity["object-name"]}</strong>
            <p>
              {source.device} at {source.target.address}
              {source.target.router
                ? ` via ${source.target.router} / DNET ${source.target.dnet}`
                : ""}{" "}
              · captured {source.captured_at}
            </p>
            <p>
              {source.fields.length} supported defaults ·{" "}
              {source.parameter_merge.matched_parameters} saved application
              parameters · {source.parameter_merge.changed_parameters.length}{" "}
              saved values merged into the application. This source is
              independent of an open CAF or local graph.
            </p>
          </div>
          {!source.fields.length ? (
            <p>
              No existing supported Real defaults in this backup. Other field
              types and new blocks require another compiler profile.
            </p>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void compile();
              }}
            >
              <div className="native-compiler-fields">
                <label>
                  Find native default
                  <input
                    aria-label="Find native default"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </label>
                <label>
                  Native Real default
                  <span className="native-compiler-select">
                    <select
                      aria-label="Native Real default"
                      value={fieldRef}
                      disabled={busy}
                      onChange={(event) => {
                        epoch.current++;
                        setFieldRef(event.target.value);
                        setReview(null);
                        setError("");
                      }}
                    >
                      <option value="">Select an actual native signal</option>
                      {fields.map((row: Data) => (
                        <option key={row.ref} value={row.ref}>
                          {row.ref} · class {row.class_id} · property{" "}
                          {row.property}
                        </option>
                      ))}
                    </select>
                    <ChevronDown aria-hidden="true" size={16} />
                  </span>
                </label>
              </div>
              {field && (
                <>
                  <table aria-label="Native default source values">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Value</th>
                        <th>Float32 bits</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Application archive default</td>
                        <td>{numberText(field.archive_value)}</td>
                        <td>
                          <code>{field.archive_bits}</code>
                        </td>
                      </tr>
                      <tr>
                        <td>Effective default after saved-setting merge</td>
                        <td>{numberText(field.effective_value)}</td>
                        <td>
                          <code>{field.effective_bits}</code>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <label>
                    Proposed native Real default
                    <input
                      aria-label="Proposed native Real default"
                      value={value}
                      readOnly={!!activeRecovery}
                      maxLength={128}
                      disabled={
                        transferBusy || booleanTransferBusy || parentBusy
                      }
                      onChange={(event) => edit(event.target.value)}
                    />
                  </label>
                  {shownRecovery && (
                    <section
                      className="native-compiler-source"
                      aria-label="Prepared previous Real default"
                      ref={recoveryPanel}
                      tabIndex={-1}
                    >
                      <h3>
                        {shownRecovery.data.already_recorded
                          ? "Previous value already recorded in this backup"
                          : "Previous effective value prepared locally"}
                      </h3>
                      <p>
                        Receipt{" "}
                        <code>
                          {shownRecovery.data.origin.parent_receipt_id}
                        </code>{" "}
                        · {field.ref} ·{" "}
                        {numberText(shownRecovery.data.current_effective_value)}{" "}
                        to{" "}
                        {numberText(
                          shownRecovery.data.previous_effective_value,
                        )}
                        .
                      </p>
                      <p>
                        {shownRecovery.data.already_recorded
                          ? "No transfer proposal was created. This retained backup does not establish current live state."
                          : "A fresh controller review and both transfer confirmations are required. Other current saved settings remain current."}{" "}
                        Your ordinary field draft remains retained separately.
                      </p>
                      <button
                        type="button"
                        onClick={() =>
                          saveBlob(
                            shownRecovery.blob,
                            "native-previous-real-default-proposal.json",
                          )
                        }
                      >
                        Export exact previous-value proposal
                      </button>
                    </section>
                  )}
                  <button
                    className={
                      fieldTransferSourceActive || combinedActive
                        ? ""
                        : "primary"
                    }
                    type="submit"
                    disabled={busy}
                  >
                    Review native compilation
                  </button>
                  <button
                    type="button"
                    onClick={discard}
                    disabled={transferBusy || booleanTransferBusy || parentBusy}
                  >
                    {shownRecovery
                      ? "Discard previous-value proposal"
                      : "Discard selected field draft"}
                  </button>
                </>
              )}
            </form>
          )}
        </>
      )}
      <NativeBooleanTransferContext.Provider
        value={{
          controller,
          visible,
          fieldBusy: parentBusy || transferBusy || booleanTransferBusy,
          parentBusy: parentBusy || transferBusy,
          otherOperationBusy: transferBusy,
          recoveryDrafts: booleanRecoveries.current,
          wireRecoveryDrafts: wireRecoveries.current,
          enumRecoveryDrafts: enumRecoveries.current,
          onBusy: transferBusyChanged,
          onCaptured: (id) => {
            setChoice(id);
            setPendingSource(id);
            void refresh();
          },
        }}
      >
        <NativeBackupComparison
          selection={choice}
          sources={sources}
          controller={controller}
          visible={visible}
        />
        <NativeBackupInspection
          selection={
            sources.some((row) => row.id === choice)
              ? {
                  id: choice,
                  snapshot_sha256: sources.find((row) => row.id === choice)!
                    .evidence_sha256,
                  target: {
                    ...sources.find((row) => row.id === choice)!.target,
                    device: sources.find((row) => row.id === choice)!.device,
                  },
                }
              : null
          }
          controller={controller}
          visible={visible}
          booleanDrafts={booleanDrafts.current}
          wireDrafts={wireDrafts.current}
        />
        {source && field && (
          <NativeDefaultWireCompiler
            source={source}
            field={field}
            valueText={value}
            context={context}
            generation={combinedTicket}
            visible={visible}
            blocked={busy}
            parentCurrent={() =>
              current(combinedTicket, owner) &&
              sourceEpoch.current === combinedSourceTicket
            }
            drafts={combinedDrafts.current}
            onExpandedChange={setCombinedActive}
            localPrimary={!fieldTransferSourceActive}
            transferAllowed={!activeRecovery}
          />
        )}
      </NativeBooleanTransferContext.Provider>
      {storageError && <p role="status">{storageError}</p>}
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section
          className="native-compiler-source"
          aria-label="Reviewed native compilation"
        >
          <h2>Reviewed native compilation</h2>
          <p>
            {shown.data.compilation.selected_field_changed
              ? "Selected Real default changes."
              : "Selected Real default is unchanged."}{" "}
            Other saved settings remain in the compiled application.
          </p>
          <p>
            Stored value{" "}
            {numberText(shown.data.compilation.selected_edit.stored_value)} ·
            float32 bits{" "}
            <code>{shown.data.compilation.selected_edit.after_bits}</code>
            {shown.data.compilation.selected_edit.decimal_precision_changed
              ? " · proposed decimal is rounded"
              : ""}
          </p>
          <p>
            Only the selected four bytes change after the saved-setting merge.
            Saving this compiled copy does not transfer it or establish
            controller/firmware acceptance.
          </p>
          <div className="button-row">
            <button disabled={busy} onClick={() => void save()}>
              Save compiled native copy
            </button>
            <button
              onClick={() => {
                if (current(shown.ticket, shown.owner))
                  saveBlob(shown.blob, "native-effective-default-review.json");
              }}
            >
              Export exact compilation review
            </button>
          </div>
          <details>
            <summary>Compilation, preservation and source hashes</summary>
            <pre>{JSON.stringify(shown.data, null, 2)}</pre>
          </details>
        </section>
      )}
      <NativeDefaultTransfer
        controller={controller}
        source={source}
        proposal={body}
        field={field}
        visible={visible && !combinedActive}
        presentationHidden={combinedActive}
        parentBusy={parentBusy || booleanTransferBusy}
        otherOperationBusy={booleanTransferBusy}
        recoveryDraft={activeRecovery}
        onRecoveryPrepared={(document) => {
          pendingRecoveryFocus.current = document.data.origin_sha256;
          epoch.current++;
          setReview(null);
          setError("");
          setSearch("");
          setFieldRef(document.data.origin.record_ref);
          setRecovery(document);
        }}
        onBusy={(value) => transferBusyChanged("real", value)}
        onCaptured={(id) => {
          setChoice(id);
          setPendingSource(id);
          void refresh();
        }}
      />
    </section>
  );
}
