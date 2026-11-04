# Native timeout stage and deadline evidence

Native application timeout errors now retain their last reported phase and state
whether the operation's actual timeout context expired. Existing error displays
and recorded failure text receive this information without a separate screen.

For example, a timed-out step can report:

```text
Native operation timed out. Last reported phase: reading authored File 3.
The overall operation time limit did not expire.
Consult retained transfer receipts before any further write.
```

Expiry of the operation's own timer instead reports that its overall time limit
expired. The distinction comes from the existing timeout context's `expired()`
state; it is not guessed from an exception's class, cancellation cause, elapsed
duration or the number of earlier successful reads. Original error detail and
nonempty cancellation-cause text remain appended, and exception chaining remains.

The phase is the last phase reported by the owned operation. Cleanup may have
advanced that phase; it does not identify the first lost packet or prove a
network, controller, host-load or compiler cause. An expired operation timer can
coexist with another earlier failure. Existing backup-cleanup details remain
separate evidence.

Cancellation keeps its original cancellation notice. Busy/cancelled operation
admission, active ownership, final cleanup and retained receipts are unchanged.
The default overall limit remains 1,800 seconds; configured operation bounds and
individual request limits remain as configured. No retry, extra field read,
restore, automatic reconciliation or new write authority is added.

Authored checks distinguish child timeouts, actual owned timer expiry, preserved
error/cancellation detail, ordinary success, explicit cancellation and busy or
previously cancelled operation IDs. Existing local protocol/transfer checks
retain their original assertions and limits. These diagnostics improve future
evidence; the original failures described in
[the November 4 software qualification](software-validation-2026-11-04.md) and
earlier investigations remain unresolved without their own cause and repair.

## Retained verification observations

The first selected 1,126-case run passed 1,069 cases and failed 57. Its 55 Sedona
host/import failures explicitly report an unavailable Java runtime: that run
omitted the installed Java executable from its environment. A follow-up selects
the existing Java/SDK/compiler paths and verifies the pinned toolchain before
collecting the same cases. Sources, assertions, request bounds and retries remain
unchanged. All 1,126 source cases then pass; the original run remains retained.

Two other original outcomes are separate from that configuration error. An
initialized-input allocation retained a matching native application hash and
commit acknowledgment, but its published-input readback timed out and stayed
uncertain. A rename retained dispatch of EndRestore without a recorded
acknowledgment and also stayed uncertain. The latter's new diagnostic records
the last phase as committing the reviewed application and states that its
overall operation timer did not expire. Both original receipt/state sets remain
retained. Their later passing cases do not establish why the earlier responses
were unavailable or prove that the Java configuration repaired either outcome.

An earlier installed-package run passed 1,125 of the 1,126 selected cases. Its
remaining initialized-input case failed while applying voltage mode, after its
earlier allocation and resistance-mode changes had verified. The result retained
a matching application image, commit acknowledgment and preserved settings, but
published-input readback timed out and remained uncertain. That run is retained
as a failure, not qualification.

A later opt-in, original-order reproduction identified a full garbage-collection
pause during a test-peer exchange. The separate
[fixture isolation repair](native-peer-fixture-isolation.md) moves collection
before that fixture's endpoints and timed requests. This diagnostic delivery is
qualified on that merged baseline. It does not attribute the earlier untraced
outcomes to the collection observed in the later trace.
