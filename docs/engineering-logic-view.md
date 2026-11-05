# Engineering logic display

Controller application captures and local CAF diagrams now use the same
engineering canvas inside **Program**. The earlier connected view drew generic
rectangles and numbered wires, even after the CAF view gained named handles.
That split made the controller demonstration look different from a programming
tool. `EngineeringLogicCanvas` now supplies both presentations;
`CafLogicCanvas` remains a compatibility export for the existing CAF workflows.

## Presentation rules

- Draw input and output interfaces as distinct yellow/cyan signal terminals.
  Constants show their recorded default; label it **Stored**.
- Draw function bodies with named yellow input pins and cyan output pins.
  Recognize PID, PID pre-processing, Mux, timer, sequencer, FSM, comparison,
  calculation and memory classes from captured format metadata, not device model.
  Known comparison/math Setup reference labels may supply a symbol. Unknown
  classes and Setup values remain explicit; do not turn an unknown Boolean block
  into an assumed AND/OR gate.
- Anchor every wire to its actual recorded source/destination property. Names
  come from existing class/property dictionaries or a unique named child port
  whose recorded Attribute ID matches the parent pin. Ambiguous child names do
  not override the dictionary. A label grants no authoring capability.
- Use a readable signal-flow arrangement by default. Order sibling inputs by
  their destination pins to reduce crossed wires, while retaining original
  execution sequence. Recorded coordinates remain available. View moves never
  change archive coordinates, native order or controller configuration.
- Keep numeric identities and detailed evidence in the inspector. Selecting a
  block traces upstream/downstream paths; selecting a wire shows its endpoint
  names. Double-click modules to enter their actual diagrams and use the parent
  control to return. Search and keyboard selectors remain available.
- **Expand logic view** gives the diagram the available window space and keeps
  the source visible. Escape closes that view and returns focus. Expansion stays
  with the same source while moving between modules; a different source has its
  own view state.

The native adapter deliberately sets no observed CAF version or editable-port
profile. Its handles are read-only, and it issues no CAF property requests. CAF
handle gestures continue to stage the existing guarded local copy/export review;
no new transfer or program writer is introduced.

Display decoration is separate from the canonical native graph consumed by copy
compilers. Removing or changing a wire may change its displayed pin labels without
changing unrelated native records or weakening byte-preservation verification.

## Captured and live values

Stored defaults originate in the opened archive. A native block's **Live** badge
uses the selected controller's separate, identity-verified property read and its
read timestamp. Previous readings are labelled **Last read** when acquisition
fails. The captured graph, returned diagram and live response are retained with
their source, capture, diagram and selected-object identities, so a delayed reply
cannot supply another block or controller's displayed value. The existing field
read lifecycle and explicit change reviews remain in place.

## References and verification

The user's JCI and ALC examples establish the visual goals: named pins, recognizable
functions, compact interfaces and readable signal paths. The public references are
Johnson Controls' [PID logic example](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0/PID-PRAC-Commissioning-Overview/PID-Control-and-PRAC-Adaptive-Tuning-within-CCT)
and [logic-diagram description](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/16.0/User-Interface/User-Interface-Concepts/Classic-View-Workspace/Logic-Tab/Logic-Diagram).
Reference screenshots are not shipped with this implementation.

Authored CAF and native PID fixtures verify identical named-pin presentation,
source-derived aliases/defaults, unknown metadata, original bytes/order, and a real
HTTP/UDP application read. Browser checks cover source-owned live readings, a
delayed selected-point response, exact handle IDs, disabled native wiring, CAF
exports, expanded-view keyboard behavior and no unexpected field writes. Private
retained captures supplement the fixtures without entering the repository.
