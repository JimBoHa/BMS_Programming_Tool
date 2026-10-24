# Absolute temperatures and temperature differences

Use distinct units for a temperature and a change in temperature. The existing
**Convert** block remains an absolute conversion: 32 `degF` becomes 0 `degC`.
A change of 18 Fahrenheit degrees becomes a change of 10 Celsius degrees without
subtracting 32. A zero change remains zero in every difference unit.

| Quantity | Unit tokens |
| --- | --- |
| Absolute temperature | `degF`, `degC`, `K` |
| Temperature difference | `delta-degF`, `delta-degC`, `delta-K` |

## Blocks

| Block | Required inputs | Output and parameters |
| --- | --- | --- |
| TemperatureDifference | `a`, `b`: absolute temperatures in the same declared unit | `a - b`, in that unit's delta token; parameter `unit` is `degF`, `degC` or `K` |
| DeltaConvert | `in`: a difference matching `from` | Difference in `to`; both parameters use delta tokens; scale only, no origin offset |
| TemperatureOffset | `base`: absolute temperature in `unit`; `difference`: a signed difference in `difference_unit` | Base plus the scaled difference; output retains the base's absolute unit |

Examples:

- 86 `degF` minus 68 `degF` → 18 `delta-degF`.
- 18 `delta-degF` → 10 `delta-degC` → 10 `delta-K`.
- 32 `degF` plus 10 `delta-degC` → 50 `degF`.
- 20 `degC` plus −18 `delta-degF` → 10 `degC`.

The palette supplies each new block's correct default output unit. Changing its
`unit` or conversion `to` parameter updates that output unit in the inspector.
Input unit declarations must still match the wired sources. A difference cannot
feed an absolute-temperature Convert, and an absolute temperature cannot feed a
DeltaConvert. The new blocks reject wrong output quantities, mixed absolute
input units and mismatched input tokens with validation diagnostics.

## Project and runtime compatibility

Schema version 1 and the existing node `unit` string are retained. No new field,
implicit unit migration or rewrite is added to existing projects. Legacy Convert,
generic math and explicit Scale behavior remain unchanged. A legacy Subtract is
not silently reinterpreted as a temperature difference; use TemperatureDifference
to express that contract. This feature implements explicit temperature quantities,
not general dimensional algebra or automatic inference across arbitrary math.

All values must be finite. These blocks do not impose physical sensor ranges or
absolute-zero plausibility limits. A failed scan, including bad source quality or
nonfinite arithmetic, retains the existing state, published outputs and scan
clock. Different native numeric representations can still round, underflow or
overflow differently.

## Export and independent verification

BMS JSON, Structured Text, PLCopen XML and GraphML retain the exact quantity
blocks and units. ST lowers them to subtraction, slope-only multiplication/division
and addition. Sedona's generated kit uses that lowering. Its bundle retains the
checked editable graph and companion kit; standalone SAX/SAB references that
generated kit and cannot reconstruct the graph without the bundle. MatIEC compiles the ST to C, and the native
Sedona SVM executes the generated application independently of the graph engine.

Temco Control Basic emits real arithmetic statements and preserves the exact
quantity graph in checked authoring comments. Import regenerates and compares the
whole executable body before trusting those comments. The manufacturer compiler
and pinned interpreter host execute the resulting bytecode. Its 0.001 fixed-point
resolution and resource bounds remain visible; the native Temco source profile
does not carry sensor quality flags or physical controller acceptance.

Niagara exports use genuine `kitControl:Subtract`, `kitControl:Add` and
`kitControl:NumericUnitConverter` components. The pinned manufacturer's
`nre-config-edge10.dist!/defaults/units.xml` explicitly separates the `temperature`
and `temperature differential` quantities. Its differential records are
`fahrenheit degrees`, `celsius degrees` and `kelvin degrees`, all without an
absolute origin offset. Exported facets preserve those records rather than
labelling differences as absolute temperatures. Foreign converter facets cannot
mix the two quantity categories. Foreign subtraction/addition is recognized as a
quantity operation only when exact linked units establish the same raw arithmetic;
no cross-unit scaling is inferred for an ordinary Add. Genuine module, slot and
unit metadata validates the output, but a licensed Niagara station has not
executed it here.

The focused tests include negative/zero/cross-unit arithmetic, invalid quantities,
quality faults and retained outputs, legacy JSON/ST/revision hash compatibility,
source round trips, native IEC/Sedona/Temco execution and genuine Niagara metadata.
No field interface is opened. This does not compile a native JCI controller CAF,
configure a physical sensor or deploy a controller application.
