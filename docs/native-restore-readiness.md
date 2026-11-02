# Controller readiness after native restore

An end-restore acknowledgement confirms receipt of the commit request. A controller
may still be starting its application and temporarily time out on property reads.
Starting verification after a fixed one-second delay can therefore leave an
otherwise successful transfer uncertain.

After an acknowledged restore, the service now allows up to 60 seconds for
source-pinned identity and operational-status reads. Each probe is bounded by
the remaining readiness budget. Probes are separated by two seconds. A different
controller identity stops the wait immediately. Readiness does not itself verify
application bytes or saved settings: the existing full readback follows only
when the expected identity responds with operational status.

The original and reviewed payload remain durable before dispatch. Readiness
never repeats a restore, file block or commit, and never enters backup mode.
Every completed probe is retained in the transfer receipt. Deadline expiry,
nonoperational status, cancellation or identity mismatch leaves the transfer
uncertain and blocks another write until explicit receipt readback resolves it.
The normal per-request, overall operation, route and interface guards still apply.

Authored UDP peer tests cover delayed readiness for name and instance changes,
a readiness read that exceeds the deadline, a nonoperational controller and an
identity mismatch. They assert that only one restore is sent and that no backup
or file verification starts when readiness is unresolved.
