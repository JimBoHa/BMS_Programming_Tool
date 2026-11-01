import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { NativeRecords, type NativeArchiveSource } from "./NativeRecords";
import { NativeBackupCapabilities } from "./NativeBackupCapabilities";
import type { BooleanCopyDrafts } from "./NativeBooleanDefaultCopy";
import {
  controllerKey,
  type ControllerContext,
  type ControllerTarget,
} from "./workflow";
import "./controller-application.css";

type Data = Record<string, any>;
const profile = "native-backup-record-inspection/1";
export function NativeBackupInspection({
  selection,
  controller,
  visible,
  booleanDrafts,
}: {
  selection: {
    id: string;
    snapshot_sha256: string;
    target: ControllerTarget;
  } | null;
  controller?: ControllerContext | null;
  visible: boolean;
  booleanDrafts: BooleanCopyDrafts;
}) {
  const owner = JSON.stringify([
    visible,
    selection,
    controller && [
      controllerKey(controller),
      controller.interfaceKey,
      controller.interfaceOpen,
    ],
  ]);
  const epoch = useRef(0),
    ownerNow = useRef(owner),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const [loaded, setLoaded] = useState<{
    data: Data;
    owner: string;
    epoch: number;
  } | null>(null);
  const [failure, setFailure] = useState<{
    text: string;
    owner: string;
    epoch: number;
  } | null>(null);
  const [pending, setPending] = useState<{
    owner: string;
    epoch: number;
  } | null>(null);
  const source =
    loaded?.owner === owner && loaded.epoch === epoch.current
      ? loaded.data
      : null;
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  async function inspect() {
    if (!selection) return;
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setLoaded(null);
    setFailure(null);
    setPending({ owner: key, epoch: ticket });
    try {
      const data = await api(
        "/bacnet/controller/native-application/inspection/source",
        {
          capture_id: selection.id,
          snapshot_sha256: selection.snapshot_sha256,
        },
      );
      if (
        data.profile !== profile ||
        data.source_kind !== "native-backup-archive" ||
        data.capture_id !== selection.id ||
        data.snapshot_sha256 !== selection.snapshot_sha256 ||
        !/^[a-f0-9]{64}$/.test(data.sha256 || "") ||
        data.files?.["3"]?.sha256 !== data.sha256 ||
        typeof data.target?.address !== "string" ||
        typeof data.target?.device !== "string" ||
        controllerKey(data.target) !== controllerKey(selection.target) ||
        !Number.isInteger(data.application?.record_count) ||
        data.read_only !== true ||
        data.controller_queries !== false ||
        data.field_actions !== false
      )
        throw new Error(
          "Native backup inspection does not match the selected snapshot.",
        );
      if (current(key, ticket)) setLoaded({ data, owner: key, epoch: ticket });
    } catch (error) {
      if (current(key, ticket))
        setFailure({ text: String(error), owner: key, epoch: ticket });
    } finally {
      if (current(key, ticket)) setPending(null);
    }
  }
  return (
    <section
      className="native-compiler-source"
      aria-label="Retained native backup inspection"
    >
      <h2>Inspect original native archive</h2>
      <p>
        Read original File 3 records without a field connection. Inspection does
        not require a recognized saved-parameter schema and prepares no
        controller change.
      </p>
      <button
        disabled={
          !selection ||
          (pending?.owner === owner && pending.epoch === epoch.current)
        }
        onClick={() => void inspect()}
      >
        Inspect retained native backup
      </button>
      {pending?.owner === owner && pending.epoch === epoch.current && (
        <p role="status">Opening retained archive records…</p>
      )}
      {failure?.owner === owner && failure.epoch === epoch.current && (
        <p role="alert">{failure.text}</p>
      )}
      {source && (
        <>
          <p aria-label="Native archive inspection source">
            Archive {source.capture_id.slice(0, 8)} · {source.target.device} at{" "}
            {source.target.address}
            {source.target.router
              ? ` via ${source.target.router} / DNET ${source.target.dnet}`
              : ""}{" "}
            · captured {source.captured_at}.
          </p>
          <p>
            {source.application.record_count} indexed engineering records ·{" "}
            {source.application.metadata_records} metadata records. These are
            original archive properties, not merged saved settings or current
            live values.
          </p>
          {!source.source_identity_matches && (
            <p role="status">
              The retained acquisition did not verify this archive’s Device
              identity.{" "}
              {source.source_identity_error ||
                "Keep its original source evidence; no compilation or transfer is qualified by inspection."}
            </p>
          )}
          <NativeBackupCapabilities
            key={owner + source.snapshot_sha256}
            source={source as NativeArchiveSource}
          />
          <NativeRecords
            key={owner + source.sha256}
            kind="native-backup"
            source={source as NativeArchiveSource}
            controller={controller}
            visible={visible}
            booleanDrafts={booleanDrafts}
          />
          <details>
            <summary>Archive provenance</summary>
            <pre>
              {JSON.stringify(
                {
                  snapshot_sha256: source.snapshot_sha256,
                  archive_sha256: source.sha256,
                  files: source.files,
                  identity: source.identity,
                  scope: source.scope,
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
