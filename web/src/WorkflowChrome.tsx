import { useEffect, useState } from "react";
import {
  CircuitBoard,
  FolderOpen,
  Network,
  Home,
  Library,
  History,
  Settings2,
  BookOpen,
  ChevronRight,
  Save,
  FlaskConical,
} from "lucide-react";
import {
  type CafDocument,
  type ControllerContext,
  type WorkspaceArea,
  type WorkspaceSurface,
  workspaceAreas,
} from "./workflow";

export function WorkflowNavigation({
  surface,
  onNavigate,
  disabled,
}: {
  surface: WorkspaceSurface;
  onNavigate: (surface: WorkspaceSurface) => void;
  disabled: boolean;
}) {
  const entries = [
    { id: "start", label: "Start", icon: Home },
    { id: "workspace", label: "Workspace", icon: CircuitBoard },
    { id: "library", label: "Library", icon: Library },
    { id: "history", label: "History", icon: History },
    { id: "settings", label: "Settings", icon: Settings2 },
    { id: "help", label: "Help", icon: BookOpen },
  ] as const;
  return (
    <nav className="workflow-nav" aria-label="Main navigation">
      {entries.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          aria-label={label}
          title={label}
          className={surface === id ? "active" : ""}
          aria-current={surface === id ? "page" : undefined}
          disabled={disabled}
          onClick={() => onNavigate(id)}
        >
          <Icon size={19} />
          <span>{label}</span>
        </button>
      ))}
      <div className="workflow-local">
        <span className="status-dot on" />
        Local workspace
      </div>
    </nav>
  );
}

export function WorkflowContext({
  controller,
  document,
  mode,
  onMode,
  onConnect,
  onOpen,
  onSave,
  saveLabel,
  saveDisabled,
  programName,
  onProgramName,
  contextSource,
  busy = false,
}: {
  controller: ControllerContext | null;
  document: CafDocument | null;
  mode: "edit" | "simulate" | "commission";
  onMode: (mode: "edit" | "simulate" | "commission") => void;
  onConnect: () => void;
  onOpen: () => void;
  onSave: () => void;
  saveLabel: string;
  saveDisabled: boolean;
  programName: string;
  onProgramName: (name: string) => void;
  contextSource: "caf" | "graph" | "none";
  busy?: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10000);
    return () => window.clearInterval(timer);
  }, []);
  const age = controller
    ? Math.max(0, Math.floor((now - Date.parse(controller.verifiedAt)) / 1000))
    : 0;
  return (
    <div className="workflow-context" aria-label="Working context">
      <div className="workflow-context-main">
        <div
          className="workflow-breadcrumb"
          aria-label="Selected controller path"
        >
          {controller ? (
            <>
              <Network size={17} />
              <span>{controller.router || "Direct connection"}</span>
              <ChevronRight size={13} />
              {controller.dnet != null && (
                <>
                  <span>Network {controller.dnet}</span>
                  <ChevronRight size={13} />
                </>
              )}
              <strong>{controller.name}</strong>
              <span className="workflow-address">
                {controller.address} · {controller.device}
              </span>
            </>
          ) : (
            <>
              <CircuitBoard size={18} />
              <strong>
                {contextSource === "caf" && document
                  ? document.name
                  : "Controller & application workspace"}
              </strong>
            </>
          )}
        </div>
        <div className="workflow-context-status">
          {controller ? (
            <>
              <span
                className={`workflow-state ${controller.interfaceOpen ? (age <= 30 ? "verified" : "stale") : "offline"}`}
              >
                {!controller.interfaceOpen
                  ? "Interface closed"
                  : age <= 30
                    ? "Device verified"
                    : "Last-known device"}
              </span>
              <span>
                Last verified{" "}
                {age < 60 ? `${age}s` : `${Math.floor(age / 60)}m`} ago
              </span>
              <span>{controller.ownedCommands} owned command(s)</span>
            </>
          ) : (
            <span>No controller open · local work is available</span>
          )}
          {contextSource === "caf" && document && (
            <span>
              Local CAF · {document.name}
              {document.dirty
                ? ` · Local changes: ${document.changes || "unsaved"}`
                : document.changes
                  ? " · draft saved as a copy"
                  : " · original archive"}
              {controller ? " · controller match unverified" : ""}
            </span>
          )}
          {contextSource === "graph" && (
            <span>Local graph · {programName}</span>
          )}
        </div>
      </div>
      <div className="workflow-context-actions">
        <div className="workflow-modes" aria-label="Working mode">
          {(
            [
              ["edit", "Edit"],
              ["simulate", "Simulate"],
              ["commission", "Commission"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              aria-pressed={mode === value}
              disabled={busy}
              onClick={() => onMode(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button onClick={onConnect} disabled={busy}>
          <Network size={15} />
          {controller ? "Change controller" : "Connect"}
        </button>
        <button onClick={onOpen} disabled={busy}>
          <FolderOpen size={15} />
          Open CAF
        </button>
        {contextSource === "graph" && (
          <input
            className="workflow-program-name"
            aria-label="Program name"
            value={programName}
            onChange={(event) => onProgramName(event.target.value)}
          />
        )}
        <button onClick={onSave} disabled={saveDisabled || busy}>
          <Save size={15} />
          {saveLabel}
        </button>
      </div>
    </div>
  );
}

export function WorkspaceTabs({
  area,
  onChange,
  disabled,
}: {
  area: WorkspaceArea;
  onChange: (area: WorkspaceArea) => void;
  disabled: boolean;
}) {
  return (
    <nav className="workspace-task-tabs" aria-label="Workspace tasks">
      {workspaceAreas.map((item) => (
        <button
          key={item.id}
          disabled={disabled}
          aria-current={area === item.id ? "page" : undefined}
          className={area === item.id ? "active" : ""}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}

export function StartWorkspace({
  onConnect,
  onOpen,
  onProgram,
  projects,
  onProject,
  onNew,
}: {
  onConnect: () => void;
  onOpen: () => void;
  onProgram: () => void;
  projects: { id: string; name: string; revision: number }[];
  onProject: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="workflow-start workspace-page">
      <span className="eyebrow">BMS STUDIO</span>
      <h1>What are you working on?</h1>
      <p className="workflow-lead">
        Open a controller or an application. Your tools follow the work.
      </p>
      <div className="workflow-entry-paths">
        <button className="workflow-entry" onClick={onConnect}>
          <Network size={30} />
          <strong>Connect to a controller</strong>
          <span>
            Choose a connection, discover a router and trunk, then open the
            controller you want to commission.
          </span>
          <b>
            Connect and discover <ChevronRight size={16} />
          </b>
        </button>
        <button className="workflow-entry" onClick={onOpen}>
          <FolderOpen size={30} />
          <strong>Open a CAF file</strong>
          <span>
            Inspect and edit a local application. Connect to a controller later
            when you need to.
          </span>
          <b>
            Choose a local file <ChevronRight size={16} />
          </b>
        </button>
      </div>
      <section className="workflow-recent" aria-label="Continue local work">
        <div>
          <h2>Continue local work</h2>
          <p>Local projects and drafts do not require a field connection.</p>
        </div>
        <div className="button-row">
          <button onClick={onProgram}>Program</button>
          <button onClick={onNew}>New application</button>
        </div>
        {projects.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Revision</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {projects.slice(0, 8).map((project) => (
                <tr key={project.id}>
                  <td>{project.name}</td>
                  <td>{project.revision}</td>
                  <td>
                    <button onClick={() => onProject(project.id)}>
                      Open project
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="workflow-empty">
            <FlaskConical size={20} />
            <span>
              Your graph editor draft is available under Program. Saved projects
              appear here.
            </span>
          </div>
        )}
      </section>
    </div>
  );
}

export function WorkflowToolTabs({
  label,
  items,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  items: { id: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <nav className="workflow-tool-tabs" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.id}
          disabled={disabled}
          className={item.id === value ? "active" : ""}
          aria-pressed={item.id === value}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}
