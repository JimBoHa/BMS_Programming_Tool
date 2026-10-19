# Niagara BOG interoperability

The Niagara adapter exports real Baja Object Graph XML inside a `.bog` ZIP containing `file.xml`. It imports a bounded native primitive profile into the Studio graph and provides a separate byte-exact archive inspector. It does not bundle a Niagara SDK, replace Workbench licensing, deploy a station, or program JCI FX/VMA firmware.

## Sources and evidence

- Public MIT-licensed [pybog source](https://github.com/bbartling/pybog/tree/0248d941bf230aad2f19f9805be67c0e64bd51ef), pinned at `0248d941bf230aad2f19f9805be67c0e64bd51ef`. The inspected [builder](https://github.com/bbartling/pybog/blob/0248d941bf230aad2f19f9805be67c0e64bd51ef/src/bog_builder/builder.py) provides an independently authored BOG generator. Attribution and its license are retained under `third_party/` and in `NOTICE`.
- Tridium's [Niagara AX kitControl Guide](https://raw.githubusercontent.com/bbartling/pybog/0248d941bf230aad2f19f9805be67c0e64bd51ef/pdf/docKitControl.pdf) describes primitive operations, status values, null handling, and event-driven links. A manufacturer-authored manual remains a specification reference even when its public copy is hosted in a source repository.
- Tridium's [2023 troubleshooting session](https://www.tridium.com/content/dam/tridium/en/documents/niagara-forum-2023/NF23-Technical-Troubleshooting-Niagara.pdf) and [2026 engineering session](https://www.tridium.com/content/dam/tridium/en/documents/niagara-summit-2026/application/tri-niagara-summit-2026-session-nth4.pdf) provide surrounding station and troubleshooting reference material. Catalog records outside Git retain exact source URLs, hashes, extraction status, and review limits.

The adapter's tests invoke the independently checked pybog builder to create numeric writables, a constant, subtraction, and native links. The resulting BOG is imported and the finite Studio result is checked as `100 - 40 = 60`. This establishes interoperability with that generator's source encoding. No installed Niagara station or Workbench runtime accepted or executed these exports during validation; the test is not native runtime certification.

## Native primitive profile

The profile contains 17 Studio kinds. Boolean/numeric variants can use different native component types.

| Studio kind | Native representation |
|---|---|
| Input / Output | `control:NumericWritable` or `control:BooleanWritable`; outputs link to priority input `in16`. |
| Constant | `kitControl:NumericConst` or `kitControl:BooleanConst`. |
| Switch | `kitControl:NumericSwitch` or `kitControl:BooleanSwitch`; `inSwitch`, `inTrue`, `inFalse`. |
| Add / Subtract / Multiply / Divide | Corresponding `kitControl` math components with `inA`, `inB`. Extra Add/Multiply inputs receive neutral values on export. |
| Min / Max | `kitControl:Minimum` / `Maximum`; extra native inputs repeat the second Studio operand on export. |
| Abs | `kitControl:AbsValue`, input `inA`. |
| Greater / Less / Equal | `GreaterThan` / `LessThan` / `Equal`, numeric inputs with Boolean result. |
| And / Or / Not | Corresponding Boolean components. Extra And/Or inputs receive neutral values on export. |

Source-preserving Studio exports contain a verified embedded source comment. Reimport compares a complete regenerated native XML representation before returning that original graph. A native edit cannot hide behind stale embedded source. To semantically convert an independently edited graph, remove the source comment explicitly; conversion then produces a review report rather than claiming source fidelity.

Foreign BOG import resolves local component handles, root/component module aliases, and supported relative or absolute `slot:` references without contacting a station. Four-input associative operations become explicit Studio reduction chains while preserving every downstream consumer's final result. Unconsumed native results receive visible Studio output taps. Imported metadata records source hash, semantic differences, output taps, and exact supported facet strings.

## Semantic boundaries

Niagara propagates link changes on events. Studio executes deterministic complete scans. Intermediate visibility, startup ordering, status/null behavior, priority handling, and failed-scan output holds are not equivalent. Every foreign conversion is marked `review_required`; exports include the same differences as native folder metadata.

Supported finite values have explicit types. Exported status wrappers explicitly set good initial status. Foreign bad/null status, mixed scalar encodings, duplicate writers, unresolved links, converters, unsupported output slots, unknown component settings, unknown executable components, and unmodeled typed records without handles are rejected. Missing component handles must not cause silent loss of native logic.

The unit profile maps dimensionless values, Fahrenheit, Celsius, kelvin, percent, and cubic feet per minute. Supported display-precision facets remain conversion evidence; only units affect Studio simulation. Finite native bounds or unknown facets are rejected rather than silently discarded. Stateful PI, schedules, delays, timers, alarms, slew limits, native drivers, physical terminals, histories, station credentials, and additional Sedona-native logic have no mapping in this profile.

Raw BOG XML and ZIP archives can be inspected and exported byte for byte. Additional unknown ZIP resources remain preserved in that archive workflow; semantic conversion refuses to discard them. Protected reversible encoding is not removed or bypassed. Limits are 8 MiB input, 32 MiB expanded ZIP content, 64 members, 50,000 XML elements, depth 48, and the Studio graph's 2,000-node / 10,000-edge limits.

The BOG files GUI exposes this archive workflow independently of Program import. It shows the original hash, encoding marker, archive members, components, native links, unresolved references, and unmodeled typed records. Search and pagination limit table rendering; exporting returns the original upload bytes. Reading an archive never opens a native station or executes its components. The local archive cache retains at most 16 files and 64 MiB of original plus expanded content; re-open a local file if it has been evicted.

Native station import, component resolution against installed modules, save/reopen, startup behavior, physical bindings, and real event/priority/quality tests remain required before using a converted application on equipment.
