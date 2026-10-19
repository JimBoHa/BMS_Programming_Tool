# Native CAF graph inspection and guarded rewiring

`backend/bms_tool/caf_graph.py` reads the existing graph records in observed native JCI CAF archives. It supports changing the source block of an existing connection and adding a connection between existing blocks from a matching observed prototype. These edits preserve existing identities and execution order. They do not create a new CAF from a universal graph, compile firmware, add controller objects, or transfer an application to a controller.

The records were inspected across seven authorized local CAFs for FX and Metasys controllers. The originals remain outside the repository and are never rewritten. In aggregate, the files contain 123 graph objects and 3,717 connection records. Related applications share substantial structure, so those counts do not imply independent coverage of 123 different graph schemas. All observed graph objects use class version `1.0`.

## Observed record structure

The XML namespace is `http://johnsoncontrols.com/MetasysIII/2002/3/Core`.

| Record | Observed encoding | Validation |
|---|---|---|
| Diagram object | Class `536` (Control Activity) or `575` (Control Sequence) | Other classes are not treated as diagrams. |
| Property `3375`, Block List | `array` of `BACoid` elements, each with type in its `id` attribute and instance in its text | Each resolves to the exact child reference `diagramRef.type_instance`. The child's property `75` and `objectid` must agree. A class ID is not interchangeable with a BACnet object type; signal classes demonstrate this distinction. |
| Property `3118`, Connection List | `array` of four-field `struct` records | Four `unsignedShort` fields represent source block-list index, source property ID, destination block-list index, destination property ID. Both indices must resolve. |
| Property `3117`, Seq Order | `array` of `unsignedShort` values | Every observed list is a permutation of block-list indices. The editor preserves it. |
| Property `3383` | `listof` three-field structs: `float`, `float`, `unsignedShort` | The list aligns with the block list. Coordinates retain their original text. The third field remains explicitly opaque. |
| Property `3384`, Continuation List | `listof` two-field structs: `boolean`, `string` | The list aligns with connections. Both `0`/`1` and `false`/`true` occur in the observed XML and retain their original spelling. |
| Property `3184`, Exposed Ports List | `array` of enum-set `509` values | Reported as property IDs. The inspector does not infer direction, native value type, or firmware semantics from a number alone. |

The open-source OCT repository's attributed property dictionaries identify `3118` as Connection List. Its publicly checked reflection metadata also describes a `ControlConnection` constructor with source block ID, source port ID, destination block ID, destination port ID, continuation flag, and continuation text. These are supporting observations, not a supported manufacturer SDK or an independent native acceptance test. See [the earlier investigation](jci-native-research-2026-10-19.md) for pinned source links and dependency limits.

## Source substitution guards

`CafGraph.rewire_sources(changes)` requires each change to contain exactly:

```json
{
  "diagram_ref": "8-1/575_1",
  "wire_index": 0,
  "old": [0, 663, 2, 513],
  "source_ref": "8-1/575_1.2_11"
}
```

This is an authored example, not a controller application. The method enforces these conditions:

- The original four values match exactly, the connection exists, and it is changed at most once per batch.
- The diagram has the observed class version `1.0` and internally consistent parallel records.
- The replacement source already belongs to this diagram and already uses the same outgoing property ID in an existing connection.
- Source class/version and all opaque source configuration compare equal. Only identity and descriptive properties may differ freely. An existing default-value property's text may differ, but its native type and attributes must match. Simulation properties and unknown leaf text, including meaningful whitespace, remain part of the comparison.
- The replacement source precedes the destination in the existing sequence. The change cannot create or join a feedback cycle.
- The exact observed XML spelling can be patched without serializing the whole document. An unrecognized spelling is rejected even when the read-only inspector can parse it.
- A new archive is reopened and its full inspected graph is compared with the staged result. Archive filename, timestamp, entry attributes, comments, compression setting, and all unrelated XML bytes are preserved. A no-op returns the exact original archive bytes.

These conservative guards can reject valid CCT edits. They do not establish native execution semantics or prove that every manufacturer consistency rule has been reproduced. Every returned report explicitly states that CCT/PCT acceptance and controller execution remain unverified. No block cloning, resource allocation, identity generation, enum conversion, or arbitrary port creation is attempted.

## Adding a native connection

`CafGraph.add_connections(changes)` adds an actual native relationship between two existing blocks. It requires a connection prototype from this same archive, and each change contains exactly these fields:

```json
{
  "diagram_ref": "8-1/575_1",
  "prototype_diagram_ref": "8-1/575_1",
  "prototype_wire_index": 0,
  "prototype_old": [0, 663, 2, 513],
  "source_ref": "8-1/575_1.2_11",
  "target_ref": "8-1/575_1.2_13",
  "old_connection_count": 1
}
```

This is an authored schema example. The prototype's source and destination property IDs are inherited; callers cannot supply guessed ports. Both replacement endpoints must match the corresponding prototype object's class, version, and opaque configuration using the same conservative signature rules described above. The destination property must have no existing writer, the source must execute before the destination, and the added dependency cannot create or join feedback. The destination and prototype diagrams must have the same observed class/version `1.0`.

The exact original prototype tuple and destination connection count serve as conflict guards. A batch checks all changes before returning any bytes, including duplicate-writer conflicts between proposed changes. It appends one four-short record to property `3118` and one aligned continuation record to property `3384`, initialized to false and empty text. Existing connection records, block lists, positions, sequence order, metadata, and identities remain intact. Empty native lists can be populated from a prototype in another matching diagram in the same archive. The resulting archive is reopened and its complete inspected diagrams must match the staged result.

The GUI exposes connection creation through a selected native connection prototype, existing source/destination selectors, an explicit tuple review, and a separate CAF download. Native resource capacity is not known from these records. Creating a schema-consistent relationship does not establish that a manufacturer's tool or controller will accept it, and the result must still be checked against the matching native environment.

## Validation and provenance

The committed tests author their own small XML containers; none contains private building data or copied application fragments. They verify identity resolution, the two boolean spellings, execution ordering, exact byte changes, archive metadata, conflict handling, opaque fields, and rejection of malformed or unsupported changes.

Opt-in tests read every CAF under `BMS_TEST_CAF_DIR`, inspect every diagram, and stage both a guarded source substitution and a new native connection entirely in memory. Both edits were established in all seven available archives. The tests check exported native records, preserved identities and order, and confirm that original files are unchanged. Browser tests download both kinds of native edit and reparse the actual returned CAF bytes. These checks establish interoperability with observed archives. They do not substitute for opening the edited file in the matching CCT/PCT, native simulation, a bench transfer, readback, restart persistence, and restoration.

No new independently usable JCI compiler or package route was established. Public code-index searches for the native diagram types, FDB compiler surface, and CCT database dependencies did not produce an implementation beyond the previously inspected OCT metadata and archive tools. The application still needs the matching authorized toolchain or independently verified native specifications and acceptance evidence before claiming complete FX/VMA authoring.
