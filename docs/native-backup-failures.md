# Interrupted native backup diagnostics

An interrupted File read can also lose the reply to End Backup. Previously,
the first exception left the cleanup block immediately and hid that second
failure from the operator. The capture error now retains both failures. A File
read reports its exact File identifier and stream byte offset; the active phase
also identifies the attempt to end the backup session.

Cancellation and the overall operation deadline retain the same cleanup detail
alongside their existing cancellation/timeout notice. The workflow still sends
each File request and state command at most once. It does not retry a read,
resend End Backup, start a restore or publish an incomplete backup as editable.
After unconfirmed cleanup, check the controller status and any retained transfer
receipt before another operation. A failed verification backup after a restore
does not prove that the preceding application change failed to apply.

Owned UDP tests drop the File reply, the End Backup reply and both replies. They
verify a single cleanup attempt, no file writes, no eligible capture after
unconfirmed completion, released transactions/ownership, and visible cleanup
detail after both explicit cancellation and the overall deadline. They do not
claim that an unavailable controller has returned to operational status.
