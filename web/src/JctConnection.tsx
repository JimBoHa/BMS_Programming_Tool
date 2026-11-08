import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, apiKeepalive } from "./api";

export type JctConnectionWork = {
  connection: string | null;
  status: any | null;
  archives: any[];
  archive: string;
  devices: any[];
  object: any | null;
};

export const jctConnectionWork = (): JctConnectionWork => ({
  connection: null,
  status: null,
  archives: [],
  archive: "",
  devices: [],
  object: null,
});

export function JctConnection({ work }: { work: JctConnectionWork }) {
  const [server, setServer] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [, render] = useState(0);
  const epoch = useRef(0);
  const profileDirty = useRef(false);
  const update = () => render((value) => value + 1);

  useEffect(() => {
    const current = ++epoch.current;
    api("/jct/profile")
      .then((result) => {
        if (epoch.current !== current || profileDirty.current) return;
        setServer(result.service_hint?.server_origin || "");
        setFingerprint(result.service_hint?.certificate_sha256 || "");
      })
      .catch((failure) => {
        if (epoch.current === current)
          setError(String(failure.message || failure));
      });
    if (work.connection)
      api("/jct/status", { connection_id: work.connection })
        .then((result) => {
          if (epoch.current !== current || result.connected) return;
          Object.assign(work, jctConnectionWork());
          update();
          setError("The configuration session expired. Sign in again.");
        })
        .catch(() => {});
    return () => {
      ++epoch.current;
    };
  }, []);

  async function connect(event: FormEvent) {
    event.preventDefault();
    const current = ++epoch.current;
    const secret = password;
    setPassword("");
    setError("");
    setBusy(true);
    try {
      const result = await api("/jct/connect", {
        server_origin: server,
        certificate_sha256: fingerprint.trim().toLowerCase(),
        username,
        password: secret,
      });
      if (epoch.current !== current) {
        await apiKeepalive("/jct/disconnect", {
          connection_id: result.connection_id,
        }).catch(() => {});
        return;
      }
      work.connection = result.connection_id;
      work.status = result;
      work.archives = [];
      work.devices = [];
      work.object = null;
      work.archive = "";
      update();
    } catch (failure: any) {
      if (epoch.current === current)
        setError(failure.message || String(failure));
    } finally {
      if (epoch.current === current) setBusy(false);
    }
  }

  async function read(
    path: string,
    extra: any,
    receive: (result: any) => void,
  ) {
    if (!work.connection || busy) return;
    const connection = work.connection;
    const current = ++epoch.current;
    setBusy(true);
    setError("");
    try {
      const result = await api(path, { connection_id: connection, ...extra });
      if (epoch.current !== current || work.connection !== connection) return;
      receive(result);
      update();
    } catch (failure: any) {
      if (epoch.current === current) {
        setError(failure.message || String(failure));
        const status = await api("/jct/status", {
          connection_id: connection,
        }).catch(() => null);
        if (epoch.current === current && status && !status.connected) {
          Object.assign(work, jctConnectionWork());
          update();
        }
      }
    } finally {
      if (epoch.current === current) setBusy(false);
    }
  }

  function disconnect() {
    const key = work.connection;
    const current = ++epoch.current;
    Object.assign(work, jctConnectionWork());
    setPassword("");
    setBusy(false);
    setError("");
    update();
    if (key)
      apiKeepalive("/jct/disconnect", { connection_id: key }).catch(
        (failure) => {
          if (epoch.current === current)
            setError(
              failure.message ||
                "The local connection closed; server cleanup could not be confirmed.",
            );
        },
      );
  }

  function flatten(items: any[]): any[] {
    const output: any[] = [],
      pending = [...items];
    while (pending.length && output.length < 1000) {
      const item = pending.shift();
      if (!item || typeof item !== "object") continue;
      output.push(item);
      if (Array.isArray(item.items)) pending.push(...item.items);
    }
    return output;
  }

  return (
    <section className="panel" aria-label="JCT configuration connection">
      <div className="panel-heading">
        <h2>JCT configuration connection</h2>
      </div>
      <p>
        Sign in to the configuration service, select an archive, then inspect
        its engineering data. Archive data is offline configuration.
      </p>
      {!work.connection ? (
        <form onSubmit={connect}>
          <div className="field-grid">
            <label>
              Configuration service URL
              <input
                type="url"
                required
                placeholder="https://configuration.example"
                value={server}
                onFocus={() => {
                  profileDirty.current = true;
                }}
                onChange={(event) => {
                  profileDirty.current = true;
                  setServer(event.target.value);
                }}
                disabled={busy}
              />
            </label>
            <label>
              Configuration username
              <input
                autoComplete="off"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                disabled={busy}
              />
            </label>
            <label>
              Configuration password
              <input
                type="password"
                autoComplete="off"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={busy}
              />
            </label>
          </div>
          <details open={!fingerprint}>
            <summary>Trusted service certificate</summary>
            <label>
              Certificate SHA-256 fingerprint
              <input
                required
                pattern="[a-fA-F0-9]{64}"
                value={fingerprint}
                onFocus={() => {
                  profileDirty.current = true;
                }}
                onChange={(event) => {
                  profileDirty.current = true;
                  setFingerprint(event.target.value);
                }}
                disabled={busy}
              />
            </label>
            <p className="help-text">
              The connection checks this certificate before sending credentials.
              A previously trusted local service profile can supply it.
            </p>
          </details>
          <p className="help-text">
            Use your JCT configuration account. Passwords are cleared from this
            form on submission and are not saved by BMS Studio.
          </p>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in to configuration service"}
          </button>
        </form>
      ) : (
        <>
          <p role="status">
            Configuration login established for {work.status?.account} at{" "}
            {work.status?.server_origin}.
          </p>
          <p className="help-text">
            Configuration tool {work.status?.tool_version?.major}.
            {work.status?.tool_version?.minor}. This session belongs to this
            browser workspace and expires after inactivity.
          </p>
          <div className="button-row">
            <button
              disabled={busy}
              onClick={() =>
                read("/jct/archives", {}, (result) => {
                  work.archives = result.items;
                  work.devices = [];
                  work.object = null;
                  work.archive = "";
                })
              }
            >
              Read archives
            </button>
            <button onClick={disconnect}>Close configuration connection</button>
          </div>
          {work.archives.length > 0 && (
            <div className="field-grid">
              <label>
                Configuration archive
                <select
                  value={work.archive}
                  disabled={busy}
                  onChange={(event) => {
                    ++epoch.current;
                    work.archive = event.target.value;
                    work.devices = [];
                    work.object = null;
                    setError("");
                    update();
                  }}
                >
                  <option value="">Select an archive</option>
                  {work.archives.map((entry) => (
                    <option key={entry.name} value={entry.name}>
                      {entry.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="primary"
                disabled={busy || !work.archive}
                onClick={() =>
                  read(
                    "/jct/archive/devices",
                    { archive: work.archive },
                    (result) => {
                      work.devices = flatten(result.items);
                      work.object = null;
                    },
                  )
                }
              >
                Read archive devices
              </button>
            </div>
          )}
          {work.devices.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption>Devices represented in {work.archive}</caption>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Archive reference</th>
                    <th>Configuration</th>
                  </tr>
                </thead>
                <tbody>
                  {work.devices.map((entry, index) => (
                    <tr key={entry.id || index}>
                      <td>{entry.name || "Unnamed archive entry"}</td>
                      <td>{entry.itemReference || "Reference unavailable"}</td>
                      <td>
                        <button
                          disabled={busy || !entry.id}
                          onClick={() =>
                            read(
                              "/jct/archive/object",
                              { archive: work.archive, object_id: entry.id },
                              (result) => {
                                work.object = result;
                              },
                            )
                          }
                        >
                          Inspect configuration
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {work.object && (
            <section aria-label="Selected archive object">
              <h3>
                {work.object.document?.item?.name || "Archive configuration"}
              </h3>
              <p>Source: {work.archive} · offline engineering configuration</p>
              <dl>
                <dt>Object type</dt>
                <dd>{work.object.document?.objectType}</dd>
                <dt>Firmware</dt>
                <dd>
                  {work.object.document?.item?.firmwareVersion ||
                    "Not represented in this view"}
                </dd>
                <dt>Local object identifier</dt>
                <dd>
                  {JSON.stringify(
                    work.object.document?.item?.objectIdentifier || null,
                  )}
                </dd>
              </dl>
              {work.object.redacted_fields?.length > 0 && (
                <p className="help-text">
                  Credential fields are withheld from this inspection.
                </p>
              )}
              <details>
                <summary>Archive identity and schema evidence</summary>
                <pre>{JSON.stringify(work.object, null, 2)}</pre>
              </details>
            </section>
          )}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <p className="help-text">
        This connection supports archive inspection. Archive editing and
        transfer to a controller remain unavailable in this profile.
      </p>
    </section>
  );
}
