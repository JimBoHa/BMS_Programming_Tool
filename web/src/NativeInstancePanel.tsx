import { useEffect, useId, useRef, useState } from "react";
import { NativeRuntimeCalibration } from "./NativeRuntimeCalibration";
import { NativeRuntimeParametersNotice } from "./NativeRuntimeParametersNotice";
import {
  api,
  apiBlobDocument,
  apiJsonDocument,
  apiKeepalive,
  saveBlob,
} from "./api";
import type { DeviceInstanceProps } from "./DeviceInstancePanel";
import {
  nameRecoveryProfile,
  nameRecoveryReceiptMatches,
  nameRecoveryReviewMatches,
  previousNameMatches,
  sameNameTarget,
} from "./nativeNameRecoveryContract";
import {
  instanceRecoveryProfile,
  instanceRecoverySourceProfile,
  instanceRecoveryReceiptMatches,
  instanceRecoveryReviewMatches,
  previousInstanceMatches,
} from "./nativeInstanceRecoveryContract";
import {
  type NativeIdentityWork,
  emptyIdentityWork,
  hasIdentityDraft,
  canRememberIdentityWork,
  rememberIdentityWork,
  releaseEmptyIdentityWork,
  identityDraftDocument,
  IDENTITY_DRAFT_LIMIT,
} from "./nativeIdentityWork";
import {
  IDENTITY_TEXT_BYTES,
  IDENTITY_TEXT_RESPONSE_BYTES,
  identityDraftBlob,
  identityTextSha,
  parseIdentityText,
  importedIdentityText,
} from "./unfinishedIdentity";

const base = "/bacnet/controller/native-application";
const localIdentityWork = new Map<string, NativeIdentityWork>();
const capacityMessage =
  "All 32 native identity draft slots are in use. Save and explicitly discard retained work below before opening another draft. Existing work was kept.";

export function NativeInstancePanel(
  props: DeviceInstanceProps & { changeKind?: "name" | "instance" },
) {
  const renaming = props.changeKind === "name";
  const family = renaming ? "name" : "instance";
  const recoveryLabel = renaming ? "Name" : "Instance";
  const recoveryProfile = renaming
    ? nameRecoveryProfile
    : instanceRecoveryProfile;
  const previousMatches = renaming
    ? previousNameMatches
    : previousInstanceMatches;
  const reviewMatches = renaming
    ? nameRecoveryReviewMatches
    : instanceRecoveryReviewMatches;
  function receiptMatches(result: any, expected: any) {
    return expected.recovery_origin?.profile === nameRecoveryProfile
      ? nameRecoveryReceiptMatches(result, expected)
      : expected.recovery_origin?.profile === instanceRecoveryProfile
        ? instanceRecoveryReceiptMatches(result, expected)
        : false;
  }
  const backupEffectsId = useId();
  const [capture, setCapture] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [receipt, setReceipt] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [number, setNumber] = useState("");
  const [newName, setNewName] = useState("");
  const [recovery, setRecovery] = useState<any>(null);
  const [rawImported, setRawImported] =
    useState<NativeIdentityWork["rawImported"]>();
  const rawInput = useRef<HTMLInputElement>(null);
  const [identitySources, setIdentitySources] = useState<any[]>([]);
  const [localBusy, setLocalBusy] = useState(false);
  const recoveryFocus = useRef<HTMLElement | null>(null);
  const [allocated, setAllocated] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [backup, setBackup] = useState("");
  const [restore, setRestore] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [draftChoice, setDraftChoice] = useState("");
  const [, changeDraftList] = useState(0);
  const mounted = useRef(false),
    generation = useRef(0),
    receiptEpoch = useRef(0);
  const operation = useRef<string | null>(null),
    review = useRef<string | null>(null);
  const selection = JSON.stringify([
    props.connected,
    props.interfaceIdentity,
    props.defaultAddress,
    props.defaultDevice,
    props.defaultRouter,
    props.defaultDnet,
    props.changeKind,
  ]);
  const selectionNow = useRef(selection);
  selectionNow.current = selection;
  const workNow = useRef(emptyIdentityWork());
  workNow.current = {
    capture,
    receipt,
    newName,
    number,
    recovery,
    rawImported,
  };
  const draftAvailable = canRememberIdentityWork(localIdentityWork, selection);
  const retainedDraft = localIdentityWork.get(draftChoice);
  function keep(changes: Partial<NativeIdentityWork> = {}, pending = false) {
    if (selectionNow.current !== selection) return false;
    if (
      !rememberIdentityWork(
        localIdentityWork,
        selection,
        { ...workNow.current, ...changes },
        pending,
      )
    ) {
      setError(capacityMessage);
      return false;
    }
    return true;
  }
  const [hydrated, setHydrated] = useState("");
  const localReady = hydrated === selection;
  const recoveryActive =
    localReady &&
    recovery &&
    capture &&
    receipt &&
    previousMatches(recovery.data, capture, receipt);
  const proposedName =
    renaming && recoveryActive && recovery.data.proposal
      ? recovery.data.proposal.new_name
      : newName;
  const proposedNumber =
    !renaming && recoveryActive && recovery.data.proposal
      ? String(recovery.data.proposal.new_instance)
      : number;
  const captureMatchesTarget =
    capture &&
    sameNameTarget(capture.target ?? {}, {
      address: props.defaultAddress,
      router: props.defaultRouter || null,
      dnet: props.defaultDnet,
    }) &&
    capture.identity?.device === props.defaultDevice;
  const ready =
    props.connected &&
    hydrated === selection &&
    !!props.defaultAddress &&
    !!props.defaultDevice;
  const locked = busy || props.parentBusy;

  function cancel() {
    for (const id of new Set([operation.current, review.current]))
      if (id)
        void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
          () => {},
        );
    review.current = null;
  }
  async function refresh() {
    const result = await api(base + "/status");
    if (mounted.current) setStatus(result);
  }
  useEffect(() => {
    mounted.current = true;
    void refresh().catch((failure) => {
      if (mounted.current) setError(String(failure));
    });
    return () => {
      mounted.current = false;
      generation.current++;
      receiptEpoch.current++;
      cancel();
    };
  }, []);
  useEffect(() => {
    generation.current++;
    receiptEpoch.current++;
    cancel();
    setCapture(null);
    setPlan(null);
    const saved = localIdentityWork.get(selection);
    setNumber(saved?.number ?? "");
    setNewName(saved?.newName ?? "");
    setCapture(saved?.capture ?? null);
    setReceipt((previous: any) =>
      renaming ? (saved?.receipt ?? null) : (saved?.receipt ?? previous),
    );
    setRecovery(saved?.recovery ?? null);
    setRawImported(saved?.rawImported);
    setIdentitySources([]);
    setLocalBusy(false);
    setAllocated(false);
    setConfirmed(false);
    setError("");
    setHydrated(selection);
    return () => releaseEmptyIdentityWork(localIdentityWork, selection);
  }, [selection]);
  useEffect(() => {
    if (!localReady) return;
    if (
      !rememberIdentityWork(
        localIdentityWork,
        selection,
        {
          capture,
          receipt,
          newName,
          number,
          recovery,
          rawImported,
        },
        (busy || localBusy) && localIdentityWork.has(selection),
      )
    )
      setError(capacityMessage);
  }, [
    selection,
    renaming,
    localReady,
    capture,
    receipt,
    newName,
    number,
    recovery,
    rawImported,
    busy,
    localBusy,
  ]);
  useEffect(() => {
    if (!renaming && !localBusy) return;
    const retire = () => {
      generation.current++;
      setLocalBusy(false);
    };
    document.addEventListener("visibilitychange", retire);
    window.addEventListener("pagehide", retire);
    return () => {
      document.removeEventListener("visibilitychange", retire);
      window.removeEventListener("pagehide", retire);
    };
  }, [renaming, localBusy]);
  useEffect(() => {
    if (!plan && !busy) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      if (operation.current) void refresh().catch(() => {});
    }, 1000);
    return () => window.clearInterval(timer);
  }, [plan, busy]);
  function editNumber(value: string) {
    if (!keep({ number: value })) return;
    cancel();
    generation.current++;
    setLocalBusy(false);
    setPlan(null);
    setAllocated(false);
    setConfirmed(false);
    setNumber(value);
  }
  function editName(value: string) {
    if (!keep({ newName: value })) return;
    cancel();
    generation.current++;
    setLocalBusy(false);
    setPlan(null);
    setAllocated(false);
    setConfirmed(false);
    setNewName(value);
  }

  function discardRecovery() {
    cancel();
    generation.current++;
    setPlan(null);
    setRecovery(null);
    setAllocated(false);
    setConfirmed(false);
    setLocalBusy(false);
  }
  function discardDraft(key: string) {
    if (locked || localBusy) return;
    if (key === selection) {
      cancel();
      generation.current++;
      receiptEpoch.current++;
      setCapture(null);
      setRecovery(null);
      setRawImported(undefined);
      setNumber("");
      setNewName("");
      setPlan(null);
      setAllocated(false);
      setConfirmed(false);
    }
    localIdentityWork.delete(key);
    setDraftChoice("");
    changeDraftList((n) => n + 1);
    setError("");
  }
  function saveDraft(key: string, work: NativeIdentityWork) {
    try {
      saveBlob(
        identityDraftBlob(key, work),
        `native-local-identity-draft-${Date.now()}.json`,
      );
      setError("");
    } catch (failure) {
      setError(String(failure));
    }
  }
  async function importDraft(file: File) {
    if (locked || localBusy || !localReady) return;
    cancel();
    const epoch = ++generation.current,
      wanted = selection;
    receiptEpoch.current++;
    const current = () =>
      mounted.current &&
      generation.current === epoch &&
      selectionNow.current === wanted;
    setPlan(null);
    setAllocated(false);
    setConfirmed(false);
    setLocalBusy(true);
    setError("");
    try {
      if (!canRememberIdentityWork(localIdentityWork, wanted))
        throw new Error(capacityMessage);
      if (
        !file.name ||
        file.name.length > 1024 ||
        file.size > IDENTITY_TEXT_BYTES
      )
        throw new Error(
          "Local identity file exceeds its 128 KiB or filename limit. Existing work was kept.",
        );
      const original = parseIdentityText(
        new TextDecoder("utf-8", { fatal: true }).decode(
          await file.arrayBuffer(),
        ),
        wanted,
      );
      const sha = await identityTextSha(file);
      if (!current()) return;
      const form = new FormData();
      form.append("file", file);
      const response = await apiJsonDocument(
        base + "/local-drafts/import",
        form,
      );
      if (response.blob.size > IDENTITY_TEXT_RESPONSE_BYTES)
        throw new Error("Local identity response exceeds its byte limit.");
      const restored = await importedIdentityText(
        response.data,
        original,
        wanted,
        sha,
      );
      if (!current()) return;
      const existing = localIdentityWork.get(wanted);
      if (existing && hasIdentityDraft(existing))
        throw new Error(
          "Discard this retained identity draft before importing replacement text. Existing work was kept.",
        );
      restored.rawImported = {
        filename: file.name,
        file_sha256: sha,
        receipt_id: original.receipt_id,
        recovery_origin_sha256: original.recovery_origin_sha256,
      };
      if (!keep(restored)) return;
      generation.current++;
      setCapture(restored.capture);
      setNewName(restored.newName);
      setNumber(restored.number);
      setReceipt(null);
      setRecovery(null);
      setRawImported(restored.rawImported);
      setDraftChoice(wanted);
      setLocalBusy(false);
      changeDraftList((n) => n + 1);
    } catch (failure) {
      if (current()) setError(String(failure));
    } finally {
      if (current()) setLocalBusy(false);
    }
  }
  async function identityLocal(
    kind: "sources" | "source" | "prepare",
    sourceId = "",
  ) {
    if (locked || !localReady) return;
    if (kind !== "sources" && !keep({}, true)) return;
    cancel();
    setPlan(null);
    setAllocated(false);
    setConfirmed(false);
    const epoch = ++generation.current,
      receiptGeneration = receiptEpoch.current;
    setLocalBusy(true);
    setError("");
    if (kind !== "sources") setRecovery(null);
    try {
      if (kind === "sources") {
        const data = await api(base + "/signal-default/sources");
        if (mounted.current && epoch === generation.current)
          setIdentitySources(data.sources ?? []);
      } else if (kind === "source") {
        const row = identitySources.find((item) => item.id === sourceId);
        if (!row) throw new Error(`Choose a retained ${family} source again.`);
        setCapture(null);
        const data = await api(base + `/${family}/recovery/source`, {
          capture_id: row.id,
          snapshot_sha256: row.evidence_sha256,
        });
        if (
          data.profile !==
            (renaming
              ? "native-controller-name-recovery-source/1"
              : instanceRecoverySourceProfile) ||
          data.read_only !== true ||
          data.controller_queries !== false ||
          data.field_actions !== false ||
          data.files?.["3"]?.sha256 !== data.sha256 ||
          data.capture_id !== row.id ||
          data.snapshot_sha256 !== row.evidence_sha256 ||
          !sameNameTarget(data.target ?? {}, row.target ?? {}) ||
          data.target?.device !== row.device ||
          data.identity?.["object-name"] !== row.identity?.["object-name"]
        )
          throw new Error(
            `The retained ${family} source changed; select it again.`,
          );
        if (mounted.current && epoch === generation.current) {
          setRawImported(undefined);
          setCapture({
            ...data,
            id: data.capture_id,
            snapshot_evidence_sha256: data.snapshot_sha256,
            identity: { ...data.identity, device: data.target.device },
          });
        }
      } else {
        if (
          !capture ||
          !receipt ||
          status?.[`controller_${family}_recovery_profile`] !== recoveryProfile
        )
          throw new Error(
            `Select a retained ${family} transfer and complete backup.`,
          );
        const document = await apiJsonDocument(
          base + `/${family}/recovery/prepare`,
          {
            receipt_id: receipt.intent.id,
            capture_id: capture.id,
            snapshot_sha256: capture.snapshot_evidence_sha256,
          },
        );
        if (!previousMatches(document.data, capture, receipt))
          throw new Error(
            `The previous-${family} evidence does not match this backup and receipt.`,
          );
        if (
          mounted.current &&
          epoch === generation.current &&
          receiptGeneration === receiptEpoch.current
        ) {
          setRawImported(undefined);
          setRecovery(document);
          requestAnimationFrame(() => {
            if (mounted.current && epoch === generation.current)
              recoveryFocus.current?.focus();
          });
        }
      }
    } catch (failure) {
      if (mounted.current && epoch === generation.current)
        setError(String(failure));
    } finally {
      if (mounted.current && epoch === generation.current) setLocalBusy(false);
    }
  }

  async function run(
    kind: "capture" | "preview" | "apply" | "readback" | "credentials",
  ) {
    if (
      operation.current ||
      props.parentBusy ||
      (kind !== "credentials" && !props.connected)
    )
      return;
    if (["capture", "preview", "apply"].includes(kind) && !ready) return;
    if (["capture", "preview", "apply"].includes(kind) && !keep({}, true))
      return;
    if (["capture", "preview"].includes(kind)) {
      generation.current++;
      setLocalBusy(false);
    }
    const id = "native-" + crypto.randomUUID(),
      epoch = generation.current,
      receiptGeneration = ++receiptEpoch.current;
    operation.current = id;
    setBusy(true);
    props.onBusy(true);
    setError("");
    const target = {
      address: props.defaultAddress,
      device: props.defaultDevice,
      router: props.defaultRouter || null,
      dnet: props.defaultDnet,
    };
    try {
      if (kind === "credentials") {
        await api(base + "/credentials", { backup, restore });
        setBackup("");
        setRestore("");
        setPlan(null);
      } else if (kind === "capture") {
        setRecovery(null);
        setPlan(null);
        setCapture(null);
        setAllocated(false);
        setConfirmed(false);
        const result = await api(base + "/capture", {
          ...target,
          operation_id: id,
        });
        if (mounted.current && epoch === generation.current) {
          setRawImported(undefined);
          setCapture(result);
        }
      } else if (kind === "preview") {
        if (
          !renaming &&
          (!/^(0|[1-9][0-9]*)$/.test(proposedNumber) ||
            Number(proposedNumber) > 4194302)
        )
          throw new Error("Enter a Device instance from 0 through 4194302.");
        if (renaming && (!proposedName || proposedName.trim() !== proposedName))
          throw new Error(
            "Enter the controller name without surrounding whitespace.",
          );
        setPlan(null);
        setAllocated(false);
        setConfirmed(false);
        review.current = id;
        const result = await api(
          base +
            (recoveryActive && recovery.data.proposal
              ? `/${family}/recovery/preview`
              : "/preview"),
          {
            ...target,
            operation_id: id,
            capture_id: capture.id,
            new_instance: renaming
              ? Number(capture.identity.device.split(",")[1])
              : Number(proposedNumber),
            ...(renaming ? { new_name: proposedName } : {}),
            ...(recoveryActive && recovery.data.proposal
              ? {
                  snapshot_sha256: capture.snapshot_evidence_sha256,
                  recovery_parent_receipt:
                    recovery.data.origin.parent_receipt_id,
                  recovery_origin_sha256: recovery.data.origin_sha256,
                }
              : {}),
          },
        );
        if (recoveryActive && !reviewMatches(result, recovery.data, capture)) {
          void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
            () => {},
          );
          throw new Error(
            `The ${family}-recovery review differs from its prepared source.`,
          );
        }
        if (mounted.current && epoch === generation.current) {
          setPlan(result);
          setNow(Date.now());
        } else
          void apiKeepalive(base + "/cancel", { operation_id: id }).catch(
            () => {},
          );
      } else {
        let result;
        if (kind === "apply") {
          const p = plan;
          setPlan(null);
          setAllocated(false);
          setConfirmed(false);
          review.current = null;
          result = await api(base + "/apply", {
            operation_id: id,
            token: p.token,
            review_sha256: p.review_sha256,
            allocation_confirmed: !renaming && allocated,
            name_change_confirmed: renaming && allocated,
            application_transfer_confirmed: confirmed,
          });
          if (p.recovery_origin && !receiptMatches(result, p))
            throw new Error(
              `The ${family}-recovery receipt differs from the reviewed transfer. Open its retained evidence before readback.`,
            );
        } else
          result = await api(base + "/readback", {
            operation_id: id,
            receipt_id: receipt.intent.id,
          });
        if (
          mounted.current &&
          selectionNow.current === selection &&
          receiptGeneration === receiptEpoch.current
        ) {
          if (
            kind === "readback" &&
            receipt.intent.recovery_origin &&
            !receiptMatches(result, receipt.intent)
          )
            throw new Error(
              `The ${family}-recovery readback differs from its retained receipt.`,
            );
          setReceipt(result);
          const observed =
            result.events?.filter((e: any) => e.stage === "readback").at(-1)
              ?.detail || result.result;
          const retained = { ...workNow.current, receipt: result };
          if (
            epoch === generation.current &&
            ["verified", "recovered_original"].includes(observed?.status)
          ) {
            // A retained receipt must not retire a newer capture or proposal.
            // Original recovery did not apply the proposed identity change.
            if (capture?.id === result.intent?.review_capture_id) {
              delete retained.rawImported;
              setRawImported(undefined);
              retained.recovery = null;
              retained.capture = null;
              setRecovery(null);
              setCapture(null);
              if (observed.status === "verified") {
                if (renaming && newName === result.intent.new_name) {
                  retained.newName = "";
                  setNewName("");
                }
                if (
                  !renaming &&
                  number.trim() &&
                  Number(number) === result.intent.new_instance
                ) {
                  retained.number = "";
                  setNumber("");
                }
              }
            }
            // Save matching cleanup before a verified identity changes the selected key.
            rememberIdentityWork(localIdentityWork, selection, retained);
            props.onVerified?.({
              ...result.intent,
              ...observed,
              ...(observed.status === "recovered_original"
                ? {
                    old_instance: Number(props.defaultDevice.split(",")[1]),
                    new_instance: result.intent.old_instance,
                    new_name: result.intent.old_name,
                  }
                : {}),
            });
          } else rememberIdentityWork(localIdentityWork, selection, retained);
        }
      }
      await refresh();
    } catch (failure) {
      if (mounted.current) {
        setError(String(failure));
        void refresh().catch(() => {});
      }
    } finally {
      operation.current = null;
      if (mounted.current) setBusy(false);
      props.onBusy(false);
    }
  }
  async function loadReceipt(id: string) {
    discardRecovery();
    const epoch = ++receiptEpoch.current;
    try {
      const result = await api(base + "/receipts/" + id);
      if (mounted.current && epoch === receiptEpoch.current) setReceipt(result);
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    }
  }
  async function download(kind: "backup" | "receipt") {
    try {
      const id = kind === "backup" ? capture.id : receipt.intent.id;
      const result =
        kind === "backup"
          ? await apiBlobDocument(base + "/backups/" + id)
          : await apiJsonDocument(base + "/receipts/" + id);
      saveBlob(
        result.blob,
        `native-${kind}-${id}.${kind === "backup" ? "zip" : "json"}`,
      );
    } catch (failure) {
      if (mounted.current) setError(String(failure));
    }
  }
  const fresh = plan?.can_apply && now < Date.parse(plan.expires_at);
  const receipts =
    status?.receipts?.filter((row: any) =>
      ["instance", "name"].includes(row.change_kind || "instance"),
    ) ?? [];
  const observed =
    receipt?.latest_readback ||
    receipt?.events?.filter((e: any) => e.stage === "readback").at(-1)
      ?.detail ||
    receipt?.result;
  return (
    <section
      id={
        renaming
          ? "controller-name-commissioning"
          : "controller-instance-commissioning"
      }
      className="card"
      aria-label={
        renaming
          ? "Native application name commissioning"
          : "Native application instance commissioning"
      }
    >
      <div className="card-header">
        <h2>
          {renaming
            ? "Edit controller name"
            : "Edit connected application instance"}
        </h2>
      </div>
      <div className="card-body">
        <p>
          The app reads the controller’s application and saved parameters, edits
          its Device identity, transfers the reviewed application, then reads it
          back at the same physical station.
        </p>
        <p className="help-text">
          {props.defaultAddress}
          {props.defaultRouter ? ` via ${props.defaultRouter}` : ""} ·{" "}
          {props.defaultDevice}. Support is determined from the actual protocol
          and application format.
        </p>
        <p
          id={backupEffectsId}
          role="note"
          aria-label="Backup and readback effects"
          className="help-text"
        >
          Backup and readback enter and end the controller’s backup mode. They
          read the application and saved parameters without applying an
          application. Apply sends the reviewed application separately.
        </p>
        <details>
          <summary>
            Transfer credentials{" "}
            {status?.credentials_configured
              ? "— configured on this machine"
              : "— required"}
          </summary>
          <p className="help-text">
            Controller family credentials are stored privately on this machine.
          </p>
          <div className="form-grid">
            <label>
              Backup credential
              <input
                type="password"
                autoComplete="off"
                disabled={locked}
                value={backup}
                onChange={(e) => setBackup(e.target.value)}
              />
            </label>
            <label>
              Application transfer credential
              <input
                type="password"
                autoComplete="off"
                disabled={locked}
                value={restore}
                onChange={(e) => setRestore(e.target.value)}
              />
            </label>
            <button
              disabled={locked || !backup || !restore}
              onClick={() => void run("credentials")}
            >
              Save private transfer credentials
            </button>
          </div>
        </details>
        <div className="button-row" style={{ marginTop: 16 }}>
          <button
            className={!capture ? "primary" : ""}
            aria-describedby={backupEffectsId}
            disabled={
              !ready ||
              locked ||
              !draftAvailable ||
              !status?.credentials_configured
            }
            onClick={() => void run("capture")}
          >
            Read application backup
          </button>
          {capture && (
            <button disabled={locked} onClick={() => void download("backup")}>
              Save original backup
            </button>
          )}
          <button
            disabled={
              locked ||
              localBusy ||
              !localReady ||
              !hasIdentityDraft(workNow.current)
            }
            onClick={() => discardDraft(selection)}
          >
            Discard local identity draft
          </button>
        </div>
        {!draftAvailable && <p role="status">{capacityMessage}</p>}
        <details>
          <summary>Retained identity drafts</summary>
          <p>
            {localIdentityWork.size} of {IDENTITY_DRAFT_LIMIT} slots used. Empty
            views and passive receipt viewing use no slot. Existing work is
            never evicted. Drafts stay in memory; save local text before
            reloading.
          </p>
          <p>
            Import restores raw proposal text for this same interface
            configuration, route, Device and edit kind. Referenced original
            backups must still be available locally. Discard retained work
            explicitly before replacement.
          </p>
          <button
            disabled={locked || localBusy || !localReady}
            onClick={() => rawInput.current?.click()}
          >
            Import local identity draft
          </button>
          <input
            type="file"
            accept=".json"
            hidden
            ref={rawInput}
            aria-label="Import local identity draft file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void importDraft(file);
            }}
          />
          {rawImported && (
            <p role="status">
              Unfinished identity text restored from a local file. Earlier
              receipt and recovery IDs are unverified references. Review and
              confirm any controller change separately.
            </p>
          )}
          <label>
            Retained local identity draft
            <select
              aria-label="Retained local identity draft"
              value={
                retainedDraft && hasIdentityDraft(retainedDraft)
                  ? draftChoice
                  : ""
              }
              disabled={locked || localBusy}
              onChange={(event) => setDraftChoice(event.target.value)}
            >
              <option value="" disabled>
                Choose retained work
              </option>
              {[...localIdentityWork]
                .filter(([, work]) => hasIdentityDraft(work))
                .map(([key]) => {
                  const source = JSON.parse(key);
                  return (
                    <option key={key} value={key}>
                      {source[6] === "name" ? "Name" : "Instance"} ·{" "}
                      {source[3] || "No Device"} at {source[2] || "no address"}
                      {source[4]
                        ? ` via ${source[4]} / ${source[5]}`
                        : ""} ·{" "}
                      {source[0] ? "connected context" : "offline context"}
                    </option>
                  );
                })}
            </select>
          </label>
          {retainedDraft && hasIdentityDraft(retainedDraft) && (
            <section aria-label="Retained native identity draft">
              <p>
                This is local work for the source below. Viewing it does not
                change the selected controller. Original backups and receipts
                remain in local History; this export saves raw proposal text and
                source references.
              </p>
              <pre className="result">
                {JSON.stringify(
                  identityDraftDocument(draftChoice, retainedDraft),
                  null,
                  2,
                )}
              </pre>
              <div className="button-row">
                <button
                  disabled={locked || localBusy}
                  onClick={() => saveDraft(draftChoice, retainedDraft)}
                >
                  Save local identity draft
                </button>
                <button
                  disabled={locked || localBusy}
                  onClick={() => discardDraft(draftChoice)}
                >
                  Discard selected retained draft
                </button>
              </div>
            </section>
          )}
        </details>
        {localReady && (
          <details>
            <summary>Previous controller {family}</summary>
            <p className="help-text">
              Compare a resolved {family}-transfer receipt with an explicitly
              selected retained backup. Preparation works offline and creates a
              local proposal. Applying it requires another confirmed review and
              transfer.
            </p>
            <div className="button-row">
              <button
                disabled={locked || localBusy}
                onClick={() => void identityLocal("sources")}
              >
                Load retained {family} backups
              </button>
              <button
                disabled={
                  locked ||
                  localBusy ||
                  !draftAvailable ||
                  !capture ||
                  !receipt ||
                  receipt.pending ||
                  receipt.intent?.change_kind !== family ||
                  status?.[`controller_${family}_recovery_profile`] !==
                    recoveryProfile
                }
                onClick={() => void identityLocal("prepare")}
              >
                Prepare previous controller {family}
              </button>
            </div>
            {!!identitySources.length && (
              <label>
                {recoveryLabel} recovery backup
                <select
                  aria-label={`${recoveryLabel} recovery backup`}
                  value={
                    identitySources.some((row) => row.id === capture?.id)
                      ? capture?.id
                      : ""
                  }
                  disabled={locked || localBusy || !draftAvailable}
                  onChange={(event) =>
                    void identityLocal("source", event.target.value)
                  }
                >
                  <option value="" disabled>
                    Choose a retained backup
                  </option>
                  {identitySources.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.captured_at} · {row.identity?.["object-name"]} ·{" "}
                      {row.target.address}
                      {row.target.router
                        ? ` via ${row.target.router}`
                        : ""} · {row.device}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {localBusy && (
              <p role="status">Reading retained {family} evidence…</p>
            )}
          </details>
        )}
        {recoveryActive && (
          <section
            aria-label={`Previous controller ${family} proposal`}
            tabIndex={-1}
            ref={recoveryFocus}
          >
            <h3>Previous controller {family}</h3>
            <p>
              {renaming ? (
                <>
                  {recovery.data.current_name} → {recovery.data.previous_name} ·
                  Device {recovery.data.origin.instance}
                </>
              ) : (
                <>
                  Device {recovery.data.current_instance} →{" "}
                  {recovery.data.previous_instance} ·{" "}
                  {recovery.data.unchanged_name}
                </>
              )}
            </p>
            <p>
              {recovery.data.already_recorded
                ? `This retained backup already records the previous ${family}. It does not verify the current controller.`
                : `Local proposal only. Other current saved settings remain current. Review and confirm a new transfer to apply this ${family}.`}
            </p>
            {!renaming && !recovery.data.already_recorded && (
              <p>
                Reserve the previous number across the BACnet internetwork
                before review. This local proposal does not allocate a number.
              </p>
            )}
            <p className="help-text">
              Source: {capture.target.address}
              {capture.target.router ? ` via ${capture.target.router}` : ""} ·
              captured {capture.captured_at}
            </p>
            <div className="button-row">
              <button disabled={locked} onClick={discardRecovery}>
                Return to ordinary {family} draft
              </button>
              <button
                disabled={locked}
                onClick={() =>
                  saveBlob(
                    recovery.blob,
                    `native-${family}-recovery-${receipt.intent.id}.json`,
                  )
                }
              >
                Save exact {family} recovery evidence
              </button>
            </div>
            <details>
              <summary>{recoveryLabel} recovery details</summary>
              <p>
                Parent receipt {recovery.data.origin.parent_receipt_id}. Current
                backup {capture.id}. Original backup{" "}
                {recovery.data.origin.original_backup_id}.
              </p>
              {!renaming && (
                <p>
                  Verified-after backup{" "}
                  {recovery.data.origin.verified_after_capture_id}.
                </p>
              )}
              <p>{recovery.data.scope}</p>
            </details>
          </section>
        )}
        {capture && localReady && (
          <div aria-label="Captured native application">
            <p>
              <strong>{capture.identity["object-name"]}</strong> ·{" "}
              {capture.identity["model-name"]} · captured {capture.captured_at}
            </p>
            <p>
              {capture.application.record_count ?? "Unrecognized"} application
              records. Original application and both parameter files retained.
            </p>
            {capture.instance_edit_supported === false ? (
              <p role="alert">
                This format cannot yet be compiled: {capture.compiler_error}
              </p>
            ) : (
              <div className="form-grid">
                {renaming ? (
                  <label>
                    New controller name
                    <input
                      disabled={!localReady || locked || !draftAvailable}
                      value={proposedName}
                      readOnly={!!recoveryActive && !!recovery.data.proposal}
                      maxLength={128}
                      onChange={(event) => editName(event.target.value)}
                    />
                  </label>
                ) : (
                  <label>
                    New application Device instance (0–4194302)
                    <input
                      inputMode="numeric"
                      disabled={!localReady || locked || !draftAvailable}
                      value={proposedNumber}
                      readOnly={!!recoveryActive && !!recovery.data.proposal}
                      onChange={(e) => editNumber(e.target.value)}
                    />
                  </label>
                )}
                <button
                  className={!plan ? "primary" : ""}
                  disabled={
                    !ready ||
                    locked ||
                    localBusy ||
                    !captureMatchesTarget ||
                    !(renaming ? proposedName : proposedNumber)
                  }
                  onClick={() => void run("preview")}
                >
                  {renaming
                    ? "Review name change"
                    : "Review application instance change"}
                </button>
              </div>
            )}
          </div>
        )}
        {plan && localReady && (
          <div aria-label="Reviewed native application transfer">
            <p>
              <strong>
                {renaming
                  ? `${plan.old_name} → ${plan.new_name}`
                  : `${plan.identity["object-name"]}: ${plan.old_instance} → ${plan.new_instance}`}
              </strong>{" "}
              at {plan.target.address}
              {plan.target.router ? ` via ${plan.target.router}` : ""}
            </p>
            <p>{plan.parameter_policy}</p>
            <NativeRuntimeParametersNotice
              parameters={plan.compilation.parameters}
            />
            {renaming && (
              <p>
                Device instance remains {plan.old_instance}. The physical
                address and route are unchanged.
              </p>
            )}
            <p className="help-text">
              Collision check: {plan.collision_check.scope}.{" "}
              {plan.collision_check.limitation}
            </p>
            {!!plan.collision_check.devices.length && (
              <p role="alert">
                The proposed instance is already responding. Select another
                reserved number.
              </p>
            )}
            <details>
              <summary>Application change details</summary>
              <p>
                {renaming
                  ? "Only the typed controller-name value changes."
                  : "Two typed identity fields change."}{" "}
                Other application records are preserved, with saved parameters
                merged from a fresh backup.
              </p>
              <pre>
                {JSON.stringify(plan.compilation.identity_edit.edits, null, 2)}
              </pre>
            </details>
            <p className="help-text">Review expires at {plan.expires_at}.</p>
            <label>
              <input
                type="checkbox"
                disabled={!ready || locked || !fresh}
                checked={allocated}
                onChange={(e) => setAllocated(e.target.checked)}
              />{" "}
              {renaming
                ? "I confirm this controller name change."
                : "I reserved this instance across the BACnet internetwork, including offline devices."}
            </label>
            <label>
              <input
                type="checkbox"
                disabled={!ready || locked || !fresh}
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />{" "}
              I reviewed this application transfer and its possible brief
              interruption of controller operation.
            </label>
            <button
              className="primary"
              disabled={!ready || locked || !fresh || !allocated || !confirmed}
              onClick={() => void run("apply")}
            >
              {renaming
                ? "Apply controller name"
                : "Apply application instance change"}
            </button>
            {!fresh && plan.can_apply && (
              <p role="status">
                Review expired. Review the identity change again.
              </p>
            )}
          </div>
        )}
        {busy && (
          <p role="status">
            {status?.active?.phase || "Working with selected controller…"}{" "}
            <button onClick={cancel}>Cancel native operation</button>
          </p>
        )}
        {error && <p role="alert">{error}</p>}
        {receipt && (
          <div aria-label="Native application transfer receipt">
            <p>
              <strong>Result: {observed?.status || "unknown"}</strong>
              {receipt.intent &&
                ` · ${receipt.intent.target.address} · ${receipt.intent.change_kind === "name" ? `${receipt.intent.old_name} → ${receipt.intent.new_name}` : `${receipt.intent.old_instance} → ${receipt.intent.new_instance}`}`}
            </p>
            {observed?.status === "recovered_original" && (
              <p role="status">
                Original identity, application and saved settings recovered. The
                proposed change was not verified. Readback did not replay a
                transfer.
              </p>
            )}
            <p>
              Device readback: {observed?.readback?.status || "not read"}.
              Application readback:{" "}
              {observed?.native_sha256 &&
              observed.native_sha256 === observed.expected_native_sha256
                ? "matches transferred application"
                : "not verified"}
              .
            </p>
            {typeof observed?.system_status === "number" && (
              <p>
                Controller status:{" "}
                {observed.system_status === 0
                  ? "operational"
                  : observed.system_status === 2
                    ? "download required"
                    : observed.system_status === 5
                      ? "backup in progress; wait before reading back again"
                      : `not operational (state ${observed.system_status})`}
                .
              </p>
            )}
            {observed?.error && <p role="alert">{observed.error}</p>}
            <NativeRuntimeCalibration
              report={observed?.runtime_calibration}
              preservation={observed?.preservation}
            />
            {!!observed?.preservation?.device_calculated_changes?.length && (
              <p role="status">
                The controller refreshed its automatic flow calibration offset.
                The transferred program and other saved settings match the
                review. The before and after values are retained in the transfer
                receipt.
              </p>
            )}
            {receipt.pending && (
              <p role="alert">
                This transfer is unresolved. Read back its receipt before
                another change. Do not resend it.
              </p>
            )}
            {!!observed?.errors?.length && (
              <pre>{observed.errors.join("\n")}</pre>
            )}
            {observed?.error && <p role="alert">{observed.error}</p>}
            {receipt.intent && (
              <div className="button-row">
                <button
                  disabled={!props.connected || locked}
                  aria-describedby={backupEffectsId}
                  onClick={() => void run("readback")}
                >
                  {renaming
                    ? "Read back application and name"
                    : "Read back application and instance"}
                </button>
                <button
                  disabled={locked}
                  onClick={() => void download("receipt")}
                >
                  Save transfer receipt
                </button>
              </div>
            )}
          </div>
        )}
        {!!receipts.length && (
          <label>
            Retained native transfer receipts
            <select
              aria-label="Retained native transfer receipts"
              value=""
              disabled={locked}
              onChange={(e) => void loadReceipt(e.target.value)}
            >
              <option value="" disabled>
                Choose a transfer
              </option>
              {receipts.map((r: any) => (
                <option key={r.id} value={r.id}>
                  {r.created_at} · {r.target.address} →{" "}
                  {r.change_kind === "name" ? r.new_name : r.new_instance} ·{" "}
                  {r.pending ? "readback required" : r.status}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </section>
  );
}
