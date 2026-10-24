import { useEffect, useRef, useState } from "react";
import { api, saveBlob, sourceJsonDocument } from "./api";
import { sourceEqual, sourceStringify } from "./programSource";
import { MacroLibrary } from "./MacroLibrary";
import { ActivityLibrary } from "./ActivityLibrary";
import {
  ACTIVITY_BASE,
  activityMigration,
  activityProfile,
  libraryVersion,
  type Data,
} from "./activityContracts";
import type { Program } from "./types";
import "./activity-library.css";

export type ReusableLibraryProps = {
  program: Program;
  selectedIds: string[];
  onChange: (program: Program) => void;
  onSelect?: (id: string) => void;
  onEditDefinition?: (id: string, owned?: () => boolean) => void;
  onBeforeMigration: () => void;
  sourceEpoch: number;
  onActivityCatalog?: (data: Data | null, error?: string) => void;
};

/** Separate views keep the complete legacy component/hook implementation intact. */
export function ReusableLibrary(props: ReusableLibraryProps) {
  const key = props.sourceEpoch + ":" + sourceStringify(props.program),
    version = libraryVersion(props.program);
  const lifetime = useRef({ key, generation: 0 }),
    mounted = useRef(false);
  if (lifetime.current.key !== key)
    lifetime.current = { key, generation: lifetime.current.generation + 1 };
  const generation = lifetime.current.generation;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      lifetime.current.generation++;
    };
  }, []);
  const owned = () =>
    mounted.current &&
    lifetime.current.key === key &&
    lifetime.current.generation === generation;
  function adopt(next: Program, expected: 1 | 2) {
    if (!owned())
      throw new Error(
        "The reusable-library view or source changed. Reopen the current source.",
      );
    if (libraryVersion(next) !== expected)
      throw new Error(
        "Reusable-library response changed the source format unexpectedly.",
      );
    props.onChange(next);
    return true;
  }
  const edit = (id: string) => props.onEditDefinition?.(id, owned);
  return (
    <div className="reusable-library-shell">
      {version === 1 ? (
        <>
          <MigrationCard
            program={props.program}
            sourceEpoch={props.sourceEpoch}
            onApply={(next) => {
              if (!owned()) return false;
              props.onBeforeMigration();
              return adopt(next, 2);
            }}
          />
          <MacroLibrary
            {...props}
            onChange={(next) => {
              adopt(next, 1);
            }}
            onEditDefinition={edit}
          />
        </>
      ) : version === 2 ? (
        <ActivityLibrary
          {...props}
          onAdopt={(next) => adopt(next, 2)}
          onEditDefinition={edit}
        />
      ) : (
        <section
          className="activity-library"
          aria-label="Unsupported reusable library"
        >
          <h1>Unsupported reusable-library version</h1>
          <p role="alert">
            This source has an unsupported version declaration. Its original
            Program remains in the editor; export it before choosing an explicit
            supported migration.
          </p>
        </section>
      )}
    </div>
  );
}

function MigrationCard({
  program,
  sourceEpoch,
  onApply,
}: {
  program: Program;
  sourceEpoch: number;
  onApply: (program: Program) => boolean;
}) {
  const [profile, setProfile] = useState<Data | null>(null),
    [review, setReview] = useState<{
      data: Data;
      blob: Blob;
      key: string;
    } | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const mounted = useRef(false),
    epoch = useRef(0),
    sourceKey = sourceEpoch + ":" + sourceStringify(program),
    live = useRef(sourceKey);
  live.current = sourceKey;
  const current = (mine: number, key: string) =>
    mounted.current && epoch.current === mine && live.current === key;
  useEffect(() => {
    mounted.current = true;
    const mine = ++epoch.current;
    api(ACTIVITY_BASE + "/profile")
      .then(activityProfile)
      .then((data) => {
        if (mounted.current && epoch.current === mine) setProfile(data);
      })
      .catch((e) => {
        if (mounted.current && epoch.current === mine) setError(String(e));
      });
    return () => {
      mounted.current = false;
      epoch.current++;
    };
  }, []);
  const previous = useRef(sourceKey);
  useEffect(() => {
    if (previous.current === sourceKey) return;
    previous.current = sourceKey;
    epoch.current++;
    setReview(null);
    setBusy(false);
    setError("");
  }, [sourceKey]);
  async function preview() {
    if (!profile || busy) return;
    const mine = ++epoch.current,
      key = sourceKey,
      source = program;
    setBusy(true);
    setError("");
    setReview(null);
    try {
      const doc = await sourceJsonDocument(
        ACTIVITY_BASE + "/migration/preview",
        { program: source },
      );
      const data = await activityMigration(doc.data, source),
        envelope = JSON.parse(await doc.blob.text());
      if (
        envelope.programs?.length !== 1 ||
        JSON.stringify(envelope.programs[0].path) !== '["program"]' ||
        envelope.programs[0].canonical_sha256 !== data.program_sha256
      )
        throw new Error(
          "Migration Program descriptor differs from the reviewed source.",
        );
      if (current(mine, key)) setReview({ data, blob: doc.blob, key });
    } catch (e) {
      if (current(mine, key)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  async function apply() {
    if (!review || review.key !== sourceKey || busy || !profile) return;
    const accepted = review;
    if (
      !window.confirm(
        "Migrate this editor to named multi-output activities? Existing definitions and wires are explicitly promoted. The local simulation will restart fresh: time, state, history and forces are not transferred. No revision is saved and no controller is changed.",
      )
    )
      return;
    const mine = ++epoch.current,
      key = sourceKey,
      source = program;
    setBusy(true);
    setError("");
    try {
      const doc = await sourceJsonDocument(ACTIVITY_BASE + "/migration/apply", {
        program: source,
        profile_sha256: accepted.data.profile_sha256,
        review_sha256: accepted.data.review_sha256,
      });
      const next = doc.data,
        envelope = JSON.parse(await doc.blob.text());
      if (
        !sourceEqual(next, accepted.data.program) ||
        envelope.programs?.length !== 1 ||
        JSON.stringify(envelope.programs[0].path) !== "[]" ||
        envelope.programs[0].canonical_sha256 !== accepted.data.program_sha256
      )
        throw new Error(
          "Applied activity migration differs from the original reviewed Program.",
        );
      if (current(mine, key)) onApply(next);
    } catch (e) {
      if (current(mine, key)) setError(String(e));
    } finally {
      if (mounted.current && epoch.current === mine) setBusy(false);
    }
  }
  const shown = review?.key === sourceKey ? review : null;
  return (
    <section
      className="activity-migration-strip"
      aria-label="Multi-output activity migration"
    >
      <div>
        <b>Need several outputs from one reusable block?</b>
        <p>
          Review an explicit migration to version-two activities. The current
          single-output library stays in its existing format until you apply the
          review.
        </p>
      </div>
      <div className="button-row">
        <button disabled={!profile || busy} onClick={() => void preview()}>
          Review migration to activities
        </button>
        {busy && (
          <button
            onClick={() => {
              epoch.current++;
              setBusy(false);
              setReview(null);
              setError("Pending migration response discarded.");
            }}
          >
            Discard pending migration response
          </button>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      {shown && (
        <section aria-label="Activity migration review">
          <p>
            {shown.data.rewrites.length} explicit container/port rewrites.
            Review SHA-256 <code>{shown.data.review_sha256}</code>.
          </p>
          <details>
            <summary>Source rewrites and remaining diagnostics</summary>
            <pre>
              {sourceStringify(
                {
                  rewrites: shown.data.rewrites,
                  before: shown.data.before_diagnostics,
                  after: shown.data.after_diagnostics,
                },
                2,
              )}
            </pre>
          </details>
          <p>
            Unfinished wires remain unfinished. Applying migration resets local
            simulation state and forces; it does not prove native JCI or
            physical controller compatibility.
          </p>
          <div className="button-row">
            <button
              onClick={() => {
                if (mounted.current && live.current === shown.key)
                  saveBlob(
                    shown.blob,
                    program.id + ".activity-migration-response.json",
                  );
              }}
            >
              Download original migration response
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void apply()}
            >
              Apply reviewed activity migration
            </button>
            <button disabled={busy} onClick={() => setReview(null)}>
              Dismiss migration review
            </button>
          </div>
        </section>
      )}
    </section>
  );
}
