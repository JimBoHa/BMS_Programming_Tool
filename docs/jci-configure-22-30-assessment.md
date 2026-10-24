# JCI Configure ranks22–30: reviewed scope

This assessment compares the implementation through PR60 with the prioritized manual feature register. It selects the first uncovered, independently verifiable software slice; it does not mark an entire manufacturer feature complete.

| Rank / manual ID | Existing coverage and remaining gap |
| --- | --- |
|22 · MF-bcb12d171b · writable setpoint synchronization | Native hardware-definition metadata can be inspected/migrated, and logical setpoint inputs exist. The NS8000 note PDF20 describes Revision3+ writable ZN-SP, explicit output selection and most-recent sensor/controller change. The required native application allocation/binding and sensor protocol/arbitration execution are not verified. No firmware downgrade or invented synchronization behavior is introduced. |
|23 · MF-4402524a37 · converter token participation | The direct serial MS/TP master exposes its own protocol state, and addressed Device reads verify reachability. CWCVT pages7–8 describe its separate Auto/Sole/Live, baud/address, manager-count and SA/FC observation scope. No verified CWCVT host status service is available; its display state cannot be inferred from generic serial/IP reachability. |
|24 · MF-eb24cdc8de · cooling-only VAV | The equipment wizard already creates an editable, validated, simulated portable cooling-only graph. Native JCI sequence/packages/CAF compilation, balancing and code compliance remain unverified. Repeating that portable template would not close the native gap. |
|25 · MF-82130dc1f7 · pulse prescaling | Selected next: [explicit native Accumulator settings evidence and exact offline carried-remainder review](accumulator-prescale.md). This closes a useful bounded inspection/review slice. Hardware debounce, persistence, COV timing, physical overflow and native configuration writes remain incomplete. |
|26 · MF-5e116fc4a1 · device authorization | Local Studio tokens are separate from device authorization. Metasys16 Guide PDF35,74–77 defines target policy, identity, authentication/origin/scope and release/topology constraints. No tested implementation of JCI Authorization Mode/Policy/Status or certified identity establishes native rights. Discovery/read success cannot grant write/programming authority. |
|27 · MF-734a2e0ed5 · display authorization/timeouts | CCT18 PDF262 ties display settings to native application transfer, distinguishes Disabled/Local/Default and qualifies firmware10.6+ default behavior. No qualified display schema/transfer/physical execution path exists; a generic app login or UI timeout would not implement this. |
|28 · MF-3aba872151 · distributed plant signal schedule | Grouped portable simulation can link explicit program signals and hardware surveys identify supported inputs. The plant note PDF49 describes subsystem-sized CAFs and SRC/DEST supervisory mapping. A source-bound subsystem sensor/network-signal schedule and native supervisor mapping remain missing; portable links do not allocate native JCI points. This is a useful future offline engineering feature. |
|29 · MF-173d9ae6c9 · dual-duct VAV | Current wizard covers three single-duct families. CCT18 PDF594–596 describes hot/cold-deck equipment, actuator choices and multiple airflow-pickup layouts. An explicit portable dual-deck template is a future independent feature; proprietary adaptive tuning, calibration, integrated actuator allocation and native acceptance remain outside it. |
|30 · MF-744693d3ae · exact PCX capacity | Existing hardware surveys already distinguish exact documented FX-PCX3711-0 universal inputs from FX-PCX3721-0 dedicated binary inputs, and withhold unknown variants/spares. The full product family/output/bus capacity matrix and physical confirmation remain partial. No capacity may be extrapolated from point count or a model prefix. |

Earlier plant-template ranks18–20 also remain partially uncovered. This selection does not reorder them or claim native plant compilation. The pulse feature has a concrete documented integer contract and an existing source-pinned native property path, so it can be tested without a proprietary compiler or field writes.

Sources reviewed from the local primary-manual library; PDFs are not redistributed:

| Document / edition / pages | Original PDF SHA256 |
| --- | --- |
|Controller Tool Help, LIT-12011147,18.0,262/585/594–596/1582–1585 | `68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903` |
|NS8000 Series Network Sensors Application Note, LIT-12014021,2023-07-20,17–20 | `a027c1084e1afa266908413e5790828307945b683202b030f40e43354ac69e9a` |
|CWCVT Wireless MS/TP Converter User Guide,LIT-12014120,1.1,7–8/19 | `f7f823e951538972fe6970f22318b3eb411be9560087f8aca964208ff96ff1db` |
|Metasys System Configuration Guide,LIT-12011832,16.0,35/74–77 | `0c12f1988f5be8c46cc9d779d782139fe2b41994d98afc54d7dfc91e234d20d4` |
|Chilled Water Plant for Guideline36 Application Note,LIT-12014531,1.0,49 | `87298adc723f40cc5c0ff08d08822dbd7c931698e576b7c51b099f5a59c839d7` |
|FX-PC Series Programmable Controllers and Related Products Product Bulletin,LIT-12011657,2024-03-07,10–11/15/24 | `733063dc209b19212100a4957e3e7c05e00484b31b4886f8aeb5d4b65e2fa8af` |

These edition-specific references are evidence for the assessment, not universal firmware support or vendor certification.
