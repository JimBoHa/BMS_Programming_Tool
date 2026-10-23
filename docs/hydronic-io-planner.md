# Chilled-water hydraulic I/O planner

The hydraulic planner derives an engineering point schedule and measurement dependencies from an explicit plant layout. It then binds those roles to an existing sealed **Plant I/O and network engineering schedule** and checks the electrical counts of explicitly declared physical devices. It does not generate a control Program or native plant application.

The authored `chilled-hydraulic-io-planner/1` profile covers parallel chillers, variable-speed primary pumps, and four layouts: primary-only or primary-secondary, each with headered or dedicated primary pumps. Choose 1–8 chillers. Headered primary pumps have an independent count of 1–8, an explicit equally-sized declaration and a binary or modulating chiller-isolation command selection. Dedicated primary uses one pump per chiller as a bounded profile assumption; headered-only choices are refused. Primary-secondary adds 1–8 equally sized headered variable-speed secondary pumps and an explicit primary-speed measurement strategy. Secondary/decoupler choices are refused for primary-only layouts. Boolean and integer declarations retain their exact types; integer1 does not establish an equally-sized Boolean declaration.

## Derived roles and dependencies

Every chiller gets an enable role. Every primary and secondary pump gets separate enable and speed roles. Headered primary adds a CHW isolation command per chiller. Primary-only adds a common modulating minimum-flow bypass, primary flow and building differential pressure. A single `primary.flow` role can serve both minimum-flow bypass and headered primary flow staging; its reasons retain both uses rather than inventing a second input.

Primary-secondary always retains secondary flow for secondary pump staging and building differential pressure for secondary speed. Choose one primary-speed strategy:

- Direct decoupler flow adds the decoupler-flow measurement.
- Primary-minus-secondary flow adds primary flow and reuses the existing secondary-flow role.
- Primary/secondary supply-temperature difference adds those two temperature measurements.

Headered primary also requires primary flow for flow staging, regardless of its speed strategy. Therefore the temperature strategy does not imply a plant without flow meters. One building differential-pressure value is represented; multiple independent pressure loops, highest-output selection and local pressure-control arrangements remain outside the implemented subset. Dependency records describe engineering requirements and source reasons, not executable graph edges or an implemented pump/chiller sequence.

Status, alarm, maintenance, lockout, fault, selected temperature and extra flow measurements are explicit optional monitoring selections. Prove-on selections add the relevant status measurements. Selecting both monitoring and prove-on for one status creates one role with both reasons. Omitted prove-on choices remain visible unresolved sequence assumptions. A selected status input does not establish actual proving delays, failure handling, safety permissives or commissioned behavior.

Each role carries its stable ID, application direction, value type, exact unit token, reference subsystem and source-page/table reasons. Reference subsystem labels describe the source tables; they do not discover or authenticate a controller application. Common CHW supply-temperature/setpoint, supervisory requests/reset mappings, OEM flow data, balancing, timing and safety dependencies of a complete application remain visible outside this hydraulic subset. Condenser/tower systems, heat exchangers, waterside economizers, series chillers, hot-water plants and constant-speed primary operation are excluded.

## Exact application bindings

A measurement binds an application-side **Input**; a command binds an **Output**. A network-fed measurement remains an Input and a network command remains an Output. This basis follows the portable Program interface, not a point-name suffix or an inferred physical terminal.

Review requires an exact existing PLANT review ID and content seal. The backend reloads and verifies the original sealed review, its original Program source bytes and regenerated analysis. Bind each selected hydraulic role to an exact instance/node ID. Type, direction and original unit text must match. Flow, pressure and temperature unit tokens come from an explicit authored vocabulary; the point tables do not prescribe that vocabulary. No trimming, unit alias normalization, automatic scaling or conversion repairs a mismatch. Percent commands use `%`; Boolean roles use an empty unit token.

Every selected role accepts one binding. Reusing an exact endpoint for different roles is refused. Shared hydraulic purposes already derive one shared role, which needs one binding. Missing roles and metadata conflicts produce an unresolved review. Existing errors in the source PLANT review also prevent a declared-subset consistency result.

A network binding requires all exact PLANT link IDs connected to that endpoint in its source/destination direction. Partial fanout selection, made-up names and unresolved link evidence do not establish a match. Original link diagnostics remain available. A network binding consumes no physical channel here; its remote sensor or actuator capacity is outside this subset unless separately represented by a derived physical binding.

## Physical devices and count witnesses

A physical binding names a separate explicit physical-host record and an electrical mode. An analog value does not select voltage, current or resistance automatically; Boolean commands do not select triac, FET or relay automatically. This profile accepts maintained-contact Boolean inputs, voltage/current/resistance numeric measurements, Boolean triac/FET/relay commands and voltage/current numeric commands. It does not infer pulse conditioning, actuator wiring or electrical compatibility.

Physical records distinguish a controller from a module. A module needs an explicit parent controller on the same PLANT application host. The controller model must agree with an existing nonblank PLANT host model declaration. Known catalog controller/expansion kinds must agree with the declaration. A PLANT host is not an unlimited aggregate of its base and SA modules. No module is added because its model name appears in a source. Duplicate base declarations or the same exact survey host cannot supply capacity twice; unused physical declarations are refused. Offline names remain operator declarations and do not prove physical identity or distinguish wiring aliases.

For each declared physical host, the planner calls the existing HW-CAP evaluator with only its valid bound hydraulic roles. It groups electrical modes into bounded demand rows and retains the ordinary dated, sealed capacity result, source conflicts and pool-count witness. Invalid bindings remain diagnostic errors and do not quietly become valid demands. Shortfall and unknown-model remain distinct from count fit. A parent controller with only module-bound roles has no base demand declared; its base channels are never transferred to the module.

An optional survey reference names the exact stored report ID, content seal and base or SA/MAC host. Existing HW-CAP validation reloads that evidence and preserves its uncertainty. Stale, removed or mismatched survey references refuse review/export. Survey occupancy is not subtracted and no installed spare terminal is identified.

**Every capacity result covers the declared hydraulic subset only. Other application occupancy is unknown.** Neither a count fit nor a network-only plan establishes whole-application fit, spare channels, terminal assignment, source/sink behavior, ratings, power, host/module compatibility, native CAF allocation, installed identity or physical acceptance. All related verification flags remain false.

## Original exports and lifecycle

Pure role-plan JSON and CSV row order are deterministic for the same explicit choices. Bound reviews preserve ordinary capacity-review timestamps and exact original PLANT review text, including its original Program sources. They are evidence of a particular review, not a promise that two separately evaluated dated reviews have identical bytes. JSON uses compact sorted UTF-8 encoding and a content seal. CSV includes readable role/source/Program/node/physical-device identities, reasons, exact binding modes, capacity/source/profile hashes and the subset qualification. Formula-leading spreadsheet text is escaped in CSV; original JSON text is unchanged.

The browser retains authoritative response Blobs. Downloaded JSON uses the original server bytes; CSV is generated from the retained server review. Source choices, topology, bindings, profile/catalog or survey changes require fresh review authority. Export rechecks the original PLANT authority, current profile/catalog and selected stored surveys before returning the retained original review; it does not replace it with a newly dated result.

Hydraulic reviews are session-local: at most8 reports share48MiB. Reports are limited to24MiB and requests to512KiB. Requests allow256 role bindings and32 explicit physical hosts. Existing PLANT source/instance/interface limits and HW-CAP limits of32 demand rows,64 channels per row and1024 channels total still apply. Exceeding a bound fails rather than truncating evidence. Expired PLANT or hydraulic reviews require an explicit fresh review/reopen. Download the evidence before restart; hydraulic reports are not a new durable capture library. PLANT's existing durable original-source captures remain separate.

API routes are `GET /api/hydronic-io/profile`, token-protected `POST /derive`, `/derive/csv`, `/review` and `/reviews/export/{json|csv}`. Derive takes the current profile seal and topology. Review additionally takes the exact PLANT key, capacity catalog seal, physical declarations and role bindings. Export takes the retained hydraulic `content_sha256`. Downloads carry `X-File-SHA256`. Strict bounded JSON rejects duplicate keys and malformed typed declarations. No route queries or writes a field device.

## Source scope and conflicts

Primary source: [JCI Chilled Water Plant for Guideline36 Application Note](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Chilled-Water-Plant-for-Guideline-36-Application-Note/1.0), LIT-12014531, release1.0,2025-05-15. Original PDF SHA256: `87298adc723f40cc5c0ff08d08822dbd7c931698e576b7c51b099f5a59c839d7`. Reviewed sections: PDF5–8 layouts;34–36 pump control/staging/measurement alternatives;37 primary-only minimum flow;49–54 distribution and Tables28,29,32. Counts and dedicated one-pump/chiller assumptions are authored bounds, not fixed equipment limits inferred from diagrams.

The 2017 CPO10 note LIT-12011575, PDF13, SHA256 `4d55be500d3e4b07399a3bf4019ef93a55eabbc10d156bdafb1c0e7c363828a2`, excludes secondary loops with variable primary pumps. This distinct2025 profile explicitly permits that layout; it does not silently reinterpret2017 applications. The2025 temperature-speed and flow-staging descriptions are both preserved. PDF51's HX/BI and bypass classification inconsistencies are not resolved by suffix matching: HX and series-chiller bypass points are excluded; the common primary-only modulating bypass follows PDF37 and the Table28 control-point entry.

This is an engineering planner foundation. It does not implement plant control sequences, native manufacturer applications, runtime hydraulics, CAF generation/compilation/download, controller modifications, complete Guideline36/Title24 compliance or commissioned acceptance. HYD-IO-001 records the bounded feature; broad hydronic requirement MF-8e7eecb866 remains partial.
