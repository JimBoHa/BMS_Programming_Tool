export type WorkspaceArea =
  | "overview"
  | "points"
  | "program"
  | "schedules"
  | "monitor"
  | "changes";
export type WorkspaceSurface =
  | "start"
  | "workspace"
  | "library"
  | "history"
  | "settings"
  | "help";
export type ConnectionView =
  | "setup"
  | "overview"
  | "points"
  | "program"
  | "schedules"
  | "monitor"
  | "changes"
  | "settings";
export type ControllerTarget = {
  address: string;
  device: string;
  router?: string | null;
  dnet?: number | null;
};
export type ControllerContext = ControllerTarget & {
  name: string;
  model: string;
  firmware: string;
  verifiedAt: string;
  interfaceKey: string;
  interfaceOpen: boolean;
  ownedCommands: number;
};
export type FileRequest = { id: string; file: File };
export type CafDocument = {
  name: string;
  sha256: string;
  model: string;
  release: string;
  changes: number;
  dirty: boolean;
  structuralDirty: boolean;
  file: File | null;
};
export const workspaceAreas: { id: WorkspaceArea; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "points", label: "Points & I/O" },
  { id: "program", label: "Program" },
  { id: "schedules", label: "Schedules" },
  { id: "monitor", label: "Trends & Alarms" },
  { id: "changes", label: "Changes" },
];
export const controllerKey = (target: ControllerTarget) =>
  JSON.stringify([
    target.router || null,
    target.dnet ?? null,
    target.address,
    target.device,
  ]);

export const programTools = [
  { id: "editor", label: "Graph editor" },
  { id: "caf", label: "CAF file" },
  { id: "truth-tables", label: "Truth tables" },
  { id: "bog", label: "Niagara application" },
];
export const simulationTools = [
  { id: "editor", label: "Graph simulation" },
  { id: "caf-simulation", label: "CAF simulation inputs" },
  { id: "native", label: "Sedona" },
  { id: "temco", label: "Temco" },
  { id: "iec", label: "IEC verification" },
  { id: "system", label: "System simulation" },
];
