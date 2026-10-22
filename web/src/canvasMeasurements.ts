/** UI-only measured geometry. No entry is ever copied into a Program node. */
export type MeasurementOwner = Readonly<{
  id: string;
  shape: string;
  epoch: object;
}>;
type Geometry = {
  owner: MeasurementOwner;
  element: HTMLElement;
  width: number;
  height: number;
};
export class CanvasMeasurements {
  private scope = "";
  private owners = new Map<string, MeasurementOwner>();
  private values = new Map<string, Geometry>();
  constructor(readonly canvasId: string) {}
  prepare(
    scope: string,
    nodes: { id: string; shape: string }[],
  ): Map<string, MeasurementOwner> {
    if (scope !== this.scope) {
      this.scope = scope;
      this.owners.clear();
      this.values.clear();
    }
    const current = new Set(nodes.map((node) => node.id));
    for (const id of this.owners.keys())
      if (!current.has(id)) {
        this.owners.delete(id);
        this.values.delete(id);
      }
    for (const node of nodes) {
      if (this.owners.get(node.id)?.shape !== node.shape) {
        this.owners.set(node.id, Object.freeze({ ...node, epoch: {} }));
        this.values.delete(node.id);
      }
    }
    return new Map(this.owners);
  }
  private current(owner: MeasurementOwner, element: HTMLElement): boolean {
    return (
      this.owners.get(owner.id) === owner &&
      element.isConnected &&
      element.classList.contains("react-flow__node") &&
      element.getAttribute("data-id") === owner.id &&
      element
        .closest("[data-canvas-owner]")
        ?.getAttribute("data-canvas-owner") === this.canvasId
    );
  }
  /** Read the committed current DOM ourselves, rather than trusting a delayed dimension event. */
  measure(owner: MeasurementOwner, element: HTMLElement): boolean {
    if (!this.current(owner, element)) return false;
    const width = element.offsetWidth,
      height = element.offsetHeight;
    if (
      ![width, height].every(
        (value) => Number.isFinite(value) && value > 0 && value <= 1_000_000,
      )
    )
      return false;
    const old = this.values.get(owner.id);
    if (
      old?.owner === owner &&
      old.element !== element &&
      this.current(owner, old.element)
    )
      return false;
    if (
      old?.owner === owner &&
      old.element === element &&
      old.width === width &&
      old.height === height
    )
      return false;
    this.values.set(owner.id, { owner, element, width, height });
    return true;
  }
  get(owner: MeasurementOwner): { width: number; height: number } | undefined {
    const value = this.values.get(owner.id);
    return value?.owner === owner && this.current(owner, value.element)
      ? { width: value.width, height: value.height }
      : undefined;
  }
}
