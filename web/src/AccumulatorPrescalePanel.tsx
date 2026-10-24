import { useEffect, useRef, useState } from "react";
import { api, apiJsonDocument, download, saveBlob } from "./api";

type Configuration = {
  multiplier: string;
  modulo_divide: string;
  initial_pv: string;
  initial_remainder: string;
  max_pv: string;
  batches: { pulses: string }[];
};
const initial = {
  multiplier: "1",
  modulo_divide: "2",
  initial_pv: "0",
  initial_remainder: "0",
  max_pv: "4294967295",
};
const hash = /^[0-9a-f]{64}$/;
function configuration(values: typeof initial, batches: string): Configuration {
  return {
    ...values,
    batches: batches
      .split(/\r?\n/)
      .map((pulses) => ({ pulses: pulses.trim() })),
  };
}
function validConfiguration(value: any): value is Configuration {
  return (
    value &&
    Object.keys(initial).every(
      (key) =>
        typeof value[key] === "string" &&
        /^(0|[1-9][0-9]{0,9})$/.test(value[key]),
    ) &&
    Array.isArray(value.batches) &&
    value.batches.length > 0 &&
    value.batches.length <= 256 &&
    value.batches.every(
      (row: any) =>
        row &&
        typeof row.pulses === "string" &&
        /^(0|[1-9][0-9]{0,9})$/.test(row.pulses),
    )
  );
}
export function AccumulatorPrescalePanel({
  nativeReport,
}: {
  nativeReport: any;
}) {
  const [values, setValues] = useState(initial),
    [batches, setBatches] = useState("1\n1\n1"),
    [profile, setProfile] = useState<any>(null),
    [review, setReview] = useState<any>(null),
    [source, setSource] = useState<any>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const alive = useRef(true),
    ticket = useRef(0),
    currentForm = useRef("");
  const config = configuration(values, batches),
    form = JSON.stringify([config, source]);
  currentForm.current = form;
  const nativeId = nativeReport?.id || "";
  const currentNative = useRef(nativeId);
  currentNative.current = nativeId;
  useEffect(() => {
    alive.current = true;
    void api("/accumulator-prescale/profile")
      .then((p) => {
        if (!alive.current) return;
        if (p.id !== "accumulator-prescale-review/1" || !hash.test(p.sha256))
          throw Error("Unsupported pulse-review profile.");
        setProfile(p);
      })
      .catch((e) => {
        if (alive.current) setError(String(e));
      });
    return () => {
      alive.current = false;
      ticket.current++;
    };
  }, []);
  useEffect(() => {
    ticket.current++;
    setReview(null);
    setBusy(false);
  }, [form]);
  useEffect(() => {
    ticket.current++;
    setReview(null);
    setSource(null);
    setBusy(false);
  }, [nativeId]);
  const current = (operation: number, key: string, native: string) =>
    alive.current &&
    ticket.current === operation &&
    currentForm.current === key &&
    currentNative.current === native;
  function change(name: keyof typeof initial, value: string) {
    ticket.current++;
    setReview(null);
    setBusy(false);
    setValues({ ...values, [name]: value });
  }
  async function run() {
    if (!profile) return;
    const operation = ++ticket.current,
      key = form,
      native = nativeId;
    setBusy(true);
    setReview(null);
    setError("");
    setNotice("");
    try {
      const result = await api("/accumulator-prescale/review", {
        profile_sha256: profile.sha256,
        configuration: config,
        source,
      });
      if (!current(operation, key, native)) return;
      if (
        result.format !== "bms.accumulator-prescale-review/1" ||
        !/^[a-f0-9]{32}$/.test(result.id) ||
        !hash.test(result.content_sha256) ||
        result.profile?.sha256 !== profile.sha256 ||
        !Array.isArray(result.simulation?.rows) ||
        result.simulation.rows.length !== config.batches.length ||
        JSON.stringify(result.configuration) !== JSON.stringify(config) ||
        (source
          ? result.native_source?.report_id !== source.report_id ||
            result.native_source?.object_id !== source.object_id
          : result.native_source !== null)
      )
        throw Error(
          "Pulse review response source does not match this configuration.",
        );
      setReview(result);
    } catch (e) {
      if (current(operation, key, native)) setError(String(e));
    } finally {
      if (alive.current && ticket.current === operation) setBusy(false);
    }
  }
  async function exportReview(kind: "json" | "csv") {
    if (!review) return;
    const operation = ticket.current,
      key = form,
      native = nativeId,
      selected = review;
    setError("");
    try {
      const body = { id: selected.id, content_sha256: selected.content_sha256 };
      if (kind === "json") {
        const response = await apiJsonDocument(
          "/accumulator-prescale/export/json",
          body,
        );
        if (!current(operation, key, native)) return;
        if (
          response.data.id !== selected.id ||
          response.data.content_sha256 !== selected.content_sha256
        )
          throw Error("Exported pulse review identity changed.");
        saveBlob(response.blob, `pulse-review-${selected.id}.json`);
      } else
        await download(
          "/accumulator-prescale/export/csv",
          body,
          `pulse-review-${selected.id}.csv`,
          () => current(operation, key, native),
        );
    } catch (e) {
      if (current(operation, key, native)) setError(String(e));
    }
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    const operation = ++ticket.current,
      key = form,
      native = nativeId;
    setError("");
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const result = await api("/accumulator-prescale/import", body);
      if (!current(operation, key, native)) return;
      if (
        !validConfiguration(result.configuration) ||
        !hash.test(result.file_sha256) ||
        result.native_source_reused !== false
      )
        throw Error("Invalid imported pulse configuration.");
      const { batches: imported, ...fields } = result.configuration;
      setValues(fields);
      setBatches(
        imported.map((row: { pulses: string }) => row.pulses).join("\n"),
      );
      setSource(null);
      setReview(null);
      setNotice(
        `Imported configuration only · file SHA256 ${result.file_sha256}. Original native observations remain in the source file; new review is offline.`,
      );
    } catch (e) {
      if (current(operation, key, native)) setError(String(e));
    } finally {
      if (alive.current && ticket.current === operation) setBusy(false);
    }
  }
  function useNative(item: any) {
    const prescale = item.properties.prescale?.value,
      maximum = item.properties["max-pres-value"];
    if (
      !item.accumulator_metering?.prescale_usable_for_offline_review ||
      !prescale ||
      maximum?.status !== "ok" ||
      !Number.isInteger(maximum.value) ||
      maximum.value < 0 ||
      maximum.value > 4294967295
    ) {
      setError(
        "Native prescale or maximum PV is unresolved; use explicit offline declarations.",
      );
      return;
    }
    ticket.current++;
    setReview(null);
    setBusy(false);
    setError("");
    setValues({
      ...values,
      multiplier: String(prescale.multiplier),
      modulo_divide: String(prescale.moduloDivide),
      max_pv: String(maximum.value),
      initial_pv: "0",
      initial_remainder: "0",
    });
    setSource({ report_id: nativeReport.id, object_id: item.object });
    setNotice(
      "Observed coefficients and maximum copied. Initial PV/remainder are explicitly reset to synthetic zero; native PV does not reveal the raw count or remainder.",
    );
  }
  return (
    <section className="card" aria-label="Offline Accumulator pulse review">
      <h3>Offline Accumulator pulse review</h3>
      <p>
        Integer batch arithmetic carries the numerator remainder forward.
        Initial PV, remainder and pulses are explicit simulation declarations.
        Native Scale, status, timing and physical rollover remain separate; no
        controller writes.
      </p>
      <p>
        Unexported configuration/review stays in panel memory. Import restores
        only the sealed configuration; it does not reopen a live source.
      </p>
      {nativeReport?.objects
        ?.filter(
          (item: any) =>
            item.object.startsWith("accumulator,") &&
            item.identity_verified &&
            item.accumulator_metering,
        )
        .map((item: any) => (
          <button key={item.object} onClick={() => useNative(item)}>
            Use observed prescale {item.object}
          </button>
        ))}
      {source && (
        <p>
          Baseline observation: {source.object_id} · point report{" "}
          {source.report_id}. Chosen settings may differ from this snapshot.
        </p>
      )}
      <div className="form-grid">
        {Object.entries({
          multiplier: "Prescale multiplier",
          modulo_divide: "Prescale modulo divide",
          initial_pv: "Synthetic initial PV",
          initial_remainder: "Synthetic initial numerator remainder",
          max_pv: "Declared maximum PV",
        }).map(([name, label]) => (
          <label key={name}>
            {label}
            <input
              aria-label={label}
              inputMode="numeric"
              value={values[name as keyof typeof initial]}
              onChange={(e) => {
                change(name as keyof typeof initial, e.target.value);
              }}
            />
          </label>
        ))}
        <label>
          Pulse batches, one count per line
          <textarea
            aria-label="Pulse batches, one count per line"
            value={batches}
            onChange={(e) => {
              ticket.current++;
              setReview(null);
              setBatches(e.target.value);
              setBusy(false);
            }}
          />
        </label>
      </div>
      <div className="toolbar">
        <button disabled={!profile || busy} onClick={() => void run()}>
          Review pulse batches
        </button>
        <button disabled={!review} onClick={() => void exportReview("json")}>
          Export sealed pulse review
        </button>
        <button disabled={!review} onClick={() => void exportReview("csv")}>
          Export pulse CSV
        </button>
        <label>
          Import pulse review configuration
          <input
            aria-label="Import pulse review configuration"
            type="file"
            accept=".json"
            onChange={(e) => {
              void importFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Reviewing declared pulse batches…</p>}
      {review && (
        <div aria-label="Pulse review result">
          <p>
            <strong>{review.simulation.status}</strong> · retained PV{" "}
            {review.simulation.final_pv} · numerator remainder{" "}
            {review.simulation.final_remainder}
          </p>
          <p>{review.scope}</p>
          <p>
            Configuration SHA256 {review.configuration_sha256} · content SHA256{" "}
            {review.content_sha256}
          </p>
          <table>
            <thead>
              <tr>
                {[
                  "Batch",
                  "Pulses",
                  "Prior PV / remainder",
                  "Numerator",
                  "Increment",
                  "Candidate PV / remainder",
                  "Disposition",
                  "Retained PV / remainder",
                ].map((s) => (
                  <th key={s}>{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {review.simulation.rows.map((row: any) => (
                <tr key={row.batch}>
                  <td>{row.batch}</td>
                  <td>{row.pulses}</td>
                  <td>
                    {row.prior_pv} / {row.prior_remainder}
                  </td>
                  <td>{row.numerator ?? "—"}</td>
                  <td>{row.increment ?? "—"}</td>
                  <td>
                    {row.candidate_pv ?? "—"} / {row.candidate_remainder ?? "—"}
                  </td>
                  <td>{row.status}</td>
                  <td>
                    {row.retained_pv} / {row.retained_remainder}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {profile && (
        <details>
          <summary>Pulse arithmetic source and limits</summary>
          <pre>{JSON.stringify(profile, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}
