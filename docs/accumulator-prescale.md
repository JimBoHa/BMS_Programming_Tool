# Accumulator prescale evidence and offline pulse review

Connect → Native point status has an explicit **Read native Accumulator prescale and metering metadata** option. It is off by default. For selected, identity-verified standard Accumulator objects it reads `Prescale`, `Scale`, `Max_Pres_Value`, `Pulse_Rate`, `Limit_Monitoring_Interval`, `Value_Change_Time`, and `Value_Before_Change`. Other point types cause no metering queries. Existing plain direct IPv4 and pinned IPv4-router/DNET:MAC identity, ingress, request, deadline, cancellation and teardown guards apply. There is no discovery, polling, write or new interface.

Each property retains typed native values, original tag evidence, local receipt times and source/next-hop evidence. Unknown `Scale` choices, native errors, malformed data and timeouts remain visible with their available raw evidence. Native `Scale` is distinct from `Prescale`; the offline calculation does not apply it. A successful read does not establish a coherent snapshot, current configuration, firmware acceptance, electrical counting, applied engineering scaling or physical health. Coefficients outside Unsigned32 or a zero divisor cannot seed an offline review.

The nested **Offline Accumulator pulse review** also works disconnected. Declare the multiplier, nonzero modulo divisor, initial PV, numerator remainder, maximum PV and up to256 pulse batches. Counts use canonical unsigned decimal strings, each at most `4294967295`; Boolean, floating, exponent, signed and padded spellings are refused. The initial remainder must be smaller than the divisor. For each accepted batch:

```
numerator = pulses × multiplier + previous remainder
increment, new remainder = divmod(numerator, divisor)
new PV = previous PV + increment
```

Arithmetic uses exact integers, including products above binary64's exact integer range. For multiplier3/divisor2, four one-pulse batches produce increments1,2,1,2 and remainders1,0,1,0. The remainder is in numerator units; it is not a fractional displayed engineering value.

A batch whose candidate PV exceeds the declared maximum is rejected in full, without committing its candidate remainder. Later batches remain unevaluated. This is an explicit review policy. No physical saturation, wrap, pulse loss, partial-batch acceptance or controller overflow behavior is inferred.

**Use observed prescale** copies valid observed coefficients and maximum. It explicitly initializes synthetic PV and remainder to zero. Native Present_Value cannot reveal the raw pulse count or the carried remainder. The retained point report can be attached as a separate baseline; changing proposed coefficients does not change that snapshot. A missing/evicted report or unverified source identity is refused. No further controller reads occur during review or export.

Review results include every accepted/rejected/unevaluated batch, exact intermediate decimal strings, declared configuration, optional original native baseline, source/rule/configuration/content hashes and scope. JSON downloads use the exact retained server bytes; CSV includes review/configuration/profile hashes. A sealed report import verifies its profile, content and independently regenerated arithmetic, then restores **configuration only**. Original native observations stay in the original downloaded file and acquire no live identity through import. The self seal is an integrity check, not authenticated provenance.

Unexported panel state and the newest8 reviews remain in session memory, bounded to256KiB each. Export before leaving/restarting; import restores declared configuration without opening any field interface. Input/source changes retire pending review/download responses. There is no physical pulse generator, portable graph lowering, hardware debounce simulation, scan scheduling, COV publication, restart/persistence emulator, native Prescale writer, Value_Set command or JCI application compiler.

## Source and applicability

JCI **Controller Tool Help18.0**, LIT-12011147, PDF1582–1585, describes Counter Input/Accumulator objects, release prerequisites, Prescale carried integer division, persistence, service indications and commands. Reviewed original PDF SHA256:
`68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903`.
[Official Help](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0).

The release documentation requires Field Controller main code5.0+ for this object. That is documentation applicability, not an acceptance matrix for every FX/Metasys model or release. Native datatype interpretation uses pinned BACpypes3 `0.0.110` `AccumulatorObject`, `Prescale` and `Scale`; the optional property may be absent or refused on a real controller. Source-defined integer arithmetic is reviewed here; hardware persistence/debounce and proprietary setup remain separate gaps.

## API and validation

Existing `/api/bacnet/point-status/read` adds strict Boolean `include_accumulator_metadata=false`. `/api/accumulator-prescale/profile` is local metadata. Token-protected `POST /review`, `/import`, `/export/json` and `/export/csv` perform local operations only. JSON accepts at most256KiB, refuses duplicate keys/nonfinite data, and compares profile/arithmetic proofs with exact JSON types. Retained exports require both review ID and content seal.

Tests use independent literal BACnet UDP responses for direct/routed native reads, unknown choices, zero/oversized coefficients, wrong identities, source spoofing, corrupt replies, cancellation and teardown. Independent integer matrices cover carry, partitioning, exact large products and noncommitting overflow. HTTP tests cover tokens, strict input, seals, exact exports, expiry and offline source binding. Chromium/WebKit exercise actual loopback reads, declared state, authoritative downloads independently verified by Python, import, invalid input and late-response retirement. No physical controller, serial converter or Bluetooth acceptance is claimed.
