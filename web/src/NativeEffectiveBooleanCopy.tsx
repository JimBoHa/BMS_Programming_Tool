import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { controllerKey } from "./workflow";
import {
  BooleanCopyEditor,
  type BooleanCopyDrafts,
} from "./NativeBooleanCopyEditor";
import type { NativeArchiveSource } from "./NativeRecords";

type Data = Record<string, any>;
export function NativeEffectiveBooleanCopy({
  source,
  field,
  drafts,
}: {
  source: NativeArchiveSource;
  field: {
    ref: string;
    class_id: number;
    encoded_sha256: string;
    value: boolean;
  };
  drafts: BooleanCopyDrafts;
}) {
  const owner = JSON.stringify([source, field]),
    ownerNow = useRef(owner),
    epoch = useRef(0),
    alive = useRef(true);
  if (ownerNow.current !== owner) {
    ownerNow.current = owner;
    epoch.current++;
  }
  const [loaded, setLoaded] = useState<{ data: Data; ticket: number } | null>(
      null,
    ),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const current = (key: string, ticket: number) =>
    alive.current && ownerNow.current === key && epoch.current === ticket;
  const data = loaded && current(owner, loaded.ticket) ? loaded.data : null;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current++;
    };
  }, []);
  async function load() {
    const key = ownerNow.current,
      ticket = ++epoch.current;
    setLoaded(null);
    setError("");
    setBusy(true);
    try {
      const result = await api(
        "/bacnet/controller/native-application/boolean-default-compiler/source",
        {
          capture_id: source.capture_id,
          snapshot_sha256: source.snapshot_sha256,
        },
      );
      const matches = Array.isArray(result.fields)
        ? result.fields.filter((row: Data) => row.ref === field.ref)
        : [];
      const selected = matches[0];
      if (
        result.profile !== "native-effective-boolean-default-compiler/1" ||
        result.capture_id !== source.capture_id ||
        result.snapshot_sha256 !== source.snapshot_sha256 ||
        result.source_sha256 !== source.sha256 ||
        !/^[a-f0-9]{64}$/.test(result.effective_sha256 || "") ||
        result.files?.["3"]?.sha256 !== source.sha256 ||
        typeof result.target?.address !== "string" ||
        typeof result.target?.device !== "string" ||
        controllerKey(result.target) !== controllerKey(source.target) ||
        result.source_immutable !== true ||
        result.saved_settings_merged !== true ||
        result.current_identity_verified !== false ||
        result.controller_queries !== false ||
        result.controller_write !== false ||
        result.field_transfer_enabled !== false ||
        !Array.isArray(result.fields) ||
        result.fields.length > 4096 ||
        matches.length !== 1 ||
        selected.class_id !== field.class_id ||
        selected.property !== 3113 ||
        selected.datatype !== "Boolean" ||
        selected.archive_value !== field.value ||
        typeof selected.effective_value !== "boolean" ||
        !/^[a-f0-9]{64}$/.test(selected.encoded_sha256 || "")
      )
        throw new Error(
          "Effective Boolean source differs from the selected retained archive field.",
        );
      if (current(key, ticket))
        setLoaded({ data: { ...result, selected }, ticket });
    } catch (error) {
      if (current(key, ticket)) setError(String(error));
    } finally {
      if (current(key, ticket)) setBusy(false);
    }
  }
  return (
    <section aria-label="Effective native Boolean source">
      <p>
        Merge retained saved settings before editing this existing Boolean
        default. The source must have verified retained identity and a
        recognized complete saved format. This prepares no controller transfer.
      </p>
      {!data && (
        <button className="primary" disabled={busy} onClick={() => void load()}>
          Open saved Boolean defaults
        </button>
      )}
      {busy && <p role="status">Opening retained effective Boolean values…</p>}
      {error && <p role="alert">{error}</p>}
      {data && (
        <BooleanCopyEditor
          key={owner + data.effective_sha256}
          source={source}
          field={{
            ref: field.ref,
            class_id: field.class_id,
            encoded_sha256: data.selected.encoded_sha256,
            value: data.selected.effective_value,
          }}
          drafts={drafts}
          effective={{
            source_sha256: data.effective_sha256,
            archive_value: data.selected.archive_value,
          }}
        />
      )}
    </section>
  );
}
