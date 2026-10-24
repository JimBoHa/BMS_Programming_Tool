# Niagara BOG interoperability

The Niagara adapter exports real Baja Object Graph XML inside a `.bog` ZIP containing `file.xml`. It imports a bounded native primitive profile into the Studio graph and provides a separate byte-exact archive inspector. It does not bundle a Niagara SDK, replace Workbench licensing, deploy a station, or program JCI FX/VMA firmware.

## Sources and evidence

- Public MIT-licensed [pybog source](https://github.com/bbartling/pybog/tree/0248d941bf230aad2f19f9805be67c0e64bd51ef), pinned at `0248d941bf230aad2f19f9805be67c0e64bd51ef`. The inspected [builder](https://github.com/bbartling/pybog/blob/0248d941bf230aad2f19f9805be67c0e64bd51ef/src/bog_builder/builder.py) provides an independently authored BOG generator. Attribution and its license are retained under `third_party/` and in `NOTICE`.
- Tridium's [Niagara AX kitControl Guide](https://raw.githubusercontent.com/bbartling/pybog/0248d941bf230aad2f19f9805be67c0e64bd51ef/pdf/docKitControl.pdf) describes primitive operations, status values, null handling, and event-driven links. A manufacturer-authored manual remains a specification reference even when its public copy is hosted in a source repository.
- Tridium's [2023 troubleshooting session](https://www.tridium.com/content/dam/tridium/en/documents/niagara-forum-2023/NF23-Technical-Troubleshooting-Niagara.pdf) and [2026 engineering session](https://www.tridium.com/content/dam/tridium/en/documents/niagara-summit-2026/application/tri-niagara-summit-2026-session-nth4.pdf) provide surrounding station and troubleshooting reference material. Catalog records outside Git retain exact source URLs, hashes, extraction status, and review limits.

The adapter's tests invoke the independently checked pybog builder to create numeric writables, a constant, subtraction, and native links. The resulting BOG is imported and the finite Studio result is checked as `100 - 40 = 60`. This establishes interoperability with that generator's source encoding. No installed Niagara station or Workbench runtime accepted or executed these exports during validation; the test is not native runtime certification.

### Additional manufacturer SDK evidence

On 2026-10-19, selected original members were downloaded from the public distributor's [iC Workbench 4.10.9.14 archive](https://downloads.onesight.solutions/iSMA/Niagara%20Software/IC%20Workbench/Software/iC_Workbench-4.10.9.14.zip). Exact HTTP ranges and ZIP CRC checks transferred 65,218,471 bytes from the 1,686,770,702-byte archive. The untouched JARs, documentation, license agreement, inspection notes and per-member SHA-256 manifest remain outside Git in `Reference_Library/research/niagara-sdk-4.10.9.14/`; the project does not bundle them. ZIP checks and recorded hashes establish the inspected bytes; a trusted publisher signature chain was not established.

| Member | SHA-256 |
|---|---|
| `modules/baja.jar` | `8f8351b226a2e1c7d92f4639e6d3282ab6ccc0e04dc0d27b256b050f7fe746b1` |
| `modules/control-rt.jar` | `87c2fa2baaed1f1e9be298e9dd66ffe99500210822d57d9a1abbb595309cc3ce` |
| `modules/kitControl-rt.jar` | `680983fcab508a88da7b09b6fea32afdbb65552b7067be3ccb8b27887b11ee49` |
| `modules/docDeveloper-doc.jar` | `f74c03e55492495a9e7ba0f077bd5ca24e42fe1b2bea1a1fcf8bcacc55c7b156` |
| `modules/docKitControl-doc.jar` | `68b399f8d63228e950dc89607c1ac9bfd89c8c9442aebbeb6fe299dd6b9eef0b` |
| `modules/docSource-doc.jar` | `5d0423c27e3a531e7d4c06d0476fe9de4c6b8e84e8750960fb7e75c78f435470` |
| `dist/4.10.9.14/nre-config-edge10.dist` | `ef7c125446e318cdc993b80a5f6caadd24b9da50218b674171622f6d63dcc162` |

`docDeveloper-doc.jar!/doc/bog.html` gives the native format and `ValueDocEncoder` / `ValueDocDecoder` APIs. The modules' `META-INF/module.xml` files declare native component names and implementation classes. The developer archive's `.bajadoc` XML gives inherited frozen property names and types. `nre-config-edge10.dist!/defaults/units.xml` gives physical dimensions and transforms. These are stronger static checks than comparing our exporter with our own importer.

The optional `tests/test_niagara_sdk.py` and `tests/test_niagara_extended.py` read this external metadata, using `BMS_TEST_NIAGARA_SDK_DIR` if a different local folder is needed. Together they check all 23 Studio kinds, three additional Boolean variants, composite mappings, every emitted frozen property and link endpoint type, all nine supported unit records, and module alias reuse in the genuine `module.palette`. They execute our adapter and parse metadata; they do not execute Niagara components or test a station.

That comparison exposed and fixed three substantive interoperability errors: module declarations must remain available to following siblings throughout the document; unit facets require complete serialized `BUnit` values; and compact scalar attributes on complex status slots must not become invented initial values during conversion. Current tests use proper nested status values and explicitly reject the misleading compact form.

The package's 2020-10-20 agreement, `nre-config-edge10.dist!/lib/licenseAgreement.txt`, grants execution on an identified licensed system in section 1.1, describes included API source as reference material in section 1.2, and limits modification/incorporation/redistribution in section 2.1. No licensed local Niagara runtime was established. Reference source remained unchanged outside Git and no vendor implementation code was incorporated. Runtime acceptance remains unverified.

## Native primitive profile

The profile contains 20 Studio kinds. Boolean/numeric variants can use different native component types.

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
| Clamp | A `Minimum` followed by `Maximum`, with explicit constant limits. |
| Scale | Same-unit clamped scaling uses `kitControl:Reset` with four explicit static status-numeric limits. Extrapolating scaling uses `Subtract`, `Divide`, `Multiply`, and `Add`; unit-changing clamped scaling also inserts `Minimum` / `Maximum` around the dimensionless fraction. |
| TemperatureDifference | Native `kitControl:Subtract` with an explicitly differential output unit. |
| DeltaConvert | Native `kitControl:NumericUnitConverter` with differential in/out facets. |
| TemperatureOffset | Native `kitControl:Add`, plus a differential unit converter when needed. |
| Convert | `kitControl:NumericUnitConverter`, with explicit `inFacets` / `outFacets`; absolute temperatures in Fahrenheit, Celsius, and kelvin only. |

### Scaling, clamping and conversion evidence

The manufacturer `BReset.bajadoc` descriptor documents capped linear scaling and its slope/intercept equation. `docKitControl-doc.jar!/doc/kitControl-Reset.html` requires the input low limit to be below the input high limit, permits descending output limits, and identifies the component's single facets property as describing its input. Export normalizes reversed Studio input ranges by swapping both endpoint pairs. A unit-changing scale uses separately faceted arithmetic components so its output does not acquire the input's display unit. An unclamped Studio scale never becomes a native Reset, which always caps its result.

`docKitControl-doc.jar!/doc/kitControl-NumericUnitConverter.html` distinguishes changes to the numeric value from changes to its display facets, and requires compatible unit categories. The genuine converter descriptor declares exactly `inFacets`, `in`, `outFacets`, and `out`. Export configures those actual properties. A fabricated ordinary `facets` property would be ignored by this component. Foreign conversion requires complete supported temperature-unit records on both facets, and assigns an unlinked configured input constant its input unit. The existing Convert mapping represents absolute temperatures. DeltaConvert uses the separate, zero-offset temperature-differential unit records.

Foreign native Reset components become clamped Studio Scale blocks only when all four finite static limits are explicit and the input range is ascending. Linked limits, missing limits, bad status, and unknown settings are rejected rather than converted into static parameters. Clamp and arithmetic scale composites import as their visible ordinary primitives when no checked Studio source is present; the adapter does not guess that an independently edited native network still represents a particular high-level block. Source-preserving reimport returns the original Clamp/Scale/Convert or explicit temperature-quantity graph only after the complete generated body matches.

The extended tests cover independently authored foreign Reset and NumericUnitConverter XML, all nine temperature-unit pairs, both clamp modes, reversed inputs, descending outputs, different engineering units, multiple output consumers, exact limits and bounded helper expansion. Descriptor checks independently confirm that the generated native component names, inherited slots, status wrappers, facets and linked types actually exist. The focused Niagara suites passed 151 tests locally. Finite numerical comparisons execute Studio graphs produced by native import; a Niagara runtime did not execute these files. Reset's equation and native unit transforms can round or overflow differently from Studio, and component events can expose intermediate results.

Source-preserving Studio exports contain a verified embedded source comment. Reimport compares a complete regenerated native XML representation before returning that original graph. A native edit cannot hide behind stale embedded source. To semantically convert an independently edited graph, remove the source comment explicitly; conversion then produces a review report rather than claiming source fidelity.

Foreign BOG import resolves local component handles, document-wide module aliases, and supported relative or absolute `slot:` references without contacting a station. Four-input associative operations become explicit Studio reduction chains while preserving every downstream consumer's final result. Unconsumed native results receive visible Studio output taps. Imported metadata records source hash, semantic differences, output taps, and exact supported facet strings.

## Semantic boundaries

Niagara propagates link changes on events. Studio executes deterministic complete scans. Intermediate visibility, startup ordering, status/null behavior, priority handling, and failed-scan output holds are not equivalent. Every foreign conversion is marked `review_required`; exports include the same differences as native folder metadata.

Supported finite values have explicit types. Exported status wrappers explicitly set good initial status. Foreign bad/null status, mixed scalar encodings, duplicate writers, unresolved links, converters, unsupported output slots, unknown component settings, unknown executable components, and unmodeled typed records without handles are rejected. Missing component handles must not cause silent loss of native logic.

The unit profile maps dimensionless values, absolute Fahrenheit/Celsius/kelvin, their three explicit temperature-differential units, percent, and cubic feet per minute. Native unit records carry name, symbol, physical dimension and scale/offset; bare display names and changed transforms are rejected. Supported facet keys may appear in any order and remain exact conversion evidence; only units affect Studio simulation. Finite native bounds, duplicate keys, unknown facets, incompatible status wrapper/field types, or unmodeled status metadata are rejected rather than silently discarded. Stateful PI, schedules, delays, hysteresis/deadband, timers, alarms, slew limits, native drivers, physical terminals, histories, station credentials, and additional Sedona-native logic have no mapping in this profile.

Raw BOG XML and ZIP archives can be inspected and exported byte for byte. Additional unknown ZIP resources remain preserved in that archive workflow; semantic conversion refuses to discard them. Protected reversible encoding is not removed or bypassed. Limits are 8 MiB input, 32 MiB expanded ZIP content, 64 members, 50,000 XML elements, depth 48, and the Studio graph's 2,000-node / 10,000-edge limits. Composite export counts every additional helper against the lower of the project target's node limit and 2,000, and rejects nonfinite derived interval constants before encoding. These are interchange bounds, not a Niagara station's hardware capacity. Source-free import can add further explicit reduction nodes and refuses a result that exceeds Studio limits.

The BOG files GUI exposes this archive workflow independently of Program import. It shows the original hash, encoding marker, archive members, components, native links, unresolved references, and unmodeled typed records. Search and pagination limit table rendering; exporting returns the original upload bytes. Reading an archive never opens a native station or executes its components. The local archive cache retains at most 16 files and 64 MiB of original plus expanded content; re-open a local file if it has been evicted.

Native station import, component resolution against installed modules, save/reopen, startup behavior, physical bindings, and real event/priority/quality tests remain required before using a converted application on equipment.

Explicit temperature-difference facets and the three quantity blocks are described in [temperature quantities](temperature-quantities.md). The supported unit profile now includes the three zero-offset differential records from the genuine units database.
