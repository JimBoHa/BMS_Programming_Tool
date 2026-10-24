# Canvas measurement ownership

A controlled wiresheet could leave an existing block permanently hidden after an ordinary parent render or Undo. The pinned React Flow implementation rebuilds internal dimensions from each supplied node's `measured` property. Canvas constructed fresh controlled nodes without that property. A batched update could clear dimensions without producing another native ResizeObserver callback for an unchanged DOM box.

Canvas now keeps measured pixel geometry in a component-owned UI cache. A committed control block layout reads the current wrapper's `offsetWidth` and `offsetHeight`. The cache returns dimensions only for the current Canvas instance, Program ID, node ID and rendered block/port shape. Removed IDs, replaced projects and changed port shapes retire their owner identity and measurement. Detached, foreign, wrong-node, zero/nonfinite/oversized and retired-owner observations are refused. A second connected DOM element cannot replace an already current element for the same owner.

Cache entries are pruned to the current wiresheet nodes and disappear with the Canvas component. Measured dimensions are supplied only on React Flow's temporary controlled nodes. They are never attached to a Program node, metadata, schema, archive, digest or revision. No engineering units or physical I/O values are inferred from pixel geometry.

A node/port-shape replacement also uses React Flow's existing targeted `useUpdateNodeInternals` hook to refresh current handle positions, including replacements whose box size is unchanged. This does not fit the viewport, repeat delayed measurements, alter simulation timing or change Program source. The normal native resize observation remains active.

`canvas-lifecycle.spec.ts` reproduces the original failure by delivering an actual native node measurement and holding all later native observer callbacks. On unchanged PR48 Canvas, a subsequent parent render leaves the node hidden and blocks a real click. The fixed test checks actual DOM visibility, interactions, parameter edits, Undo/Redo, removal/reinsertion and project replacement with reused node IDs and different ports. Independent Python checks compare raw downloaded Program hashes and verify that UI geometry fields never enter source. Unit cases exercise ownership retirement, pruning and invalid/stale DOM refusal. The existing exact-source WebKit test that previously failed after Undo is run unchanged.

This is a browser layout correction. It changes no BACnet services, native compilation, controller programs or field-network behavior.
