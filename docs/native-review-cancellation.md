# Native write review cancellation

Calendar, numeric weekly-day and String weekly-day cancellation now removes
completed review tokens owned by the named operation. Previously, these older
writers cancelled an active task but kept a completed review until consumption,
supersession or expiry. The newer Schedule exception writer already removed
completed owned reviews; its backend remains unchanged.

Cancellation returns `reviews_retired` alongside the existing operation ID and
active-task `cancel_requested` flag. It is idempotent, works without an open field
interface, sends no field request and preserves unrelated reviews. Applying a
cancelled token is rejected before fresh reads, durable intent or dispatch.
It never deletes a source capture, local draft or journal record.

The weekly deployment panel now retains the completed preview's operation ID.
Editing its source/declarations, changing target/interface, closing the task,
navigation, visibility changes and page exit retire that ready server review.
Starting another review retires the previous owned review. A valid Apply consumes
its token without first cancelling it. Calendar, weekly and exception panels
also cancel the owned preview when its returned response fails UI validation.
Late responses cannot restore field authority or replace unfinished work.

Cancellation of a transmitted write remains uncertain. Existing one-attempt,
identity, lifetime, wire, intent, protocol-response and readback rules stay in
force. Original receipts remain immutable and available offline; explicit
read-only reconciliation remains separate and sends no retry or rollback.
The registered profile/rule hashes and journal formats do not change.

Qualification covers direct/routed actual UDP peers for all three older domains,
multiple unrelated completed reviews, offline/idempotent cancellation, rejection
of copied cancelled tokens, valid Apply and original receipt readback. Receipts
created by the prior installed package are separately read and reconciled by the
candidate without rewriting their bytes or adding a write.

Browser checks cover source edits, closing, task navigation, visibility, malformed
responses and valid Apply across numeric/String weekly and Calendar workflows;
the malformed-response check also covers exceptions. Exact real HTTP response
bytes are captured and fulfilled once, with retries and redirects disabled,
while the authored UDP peer and actual backend perform their normal operations.
A separate earlier browser body-accessor observation remains unexplained: its
trace stored an empty preview body while the page displayed a valid fresh review.
That trace is retained; controlled qualification does not establish its cause.
No timeout, retry or storage quota is relaxed. This is simulated software
qualification, without site or Bluetooth actions.
