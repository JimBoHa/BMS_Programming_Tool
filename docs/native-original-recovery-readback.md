# Verify recovery of the original native application

An uncertain transfer can remain blocked even after the controller's original
application has been restored. Seeing its old name or instance alone does not
prove that its program or saved settings were recovered.

Explicit native receipt readback now recognizes a separate `recovered_original`
outcome. It requires the original complete identity, operational status, a fresh
source-pinned File 3/11/12 capture, exact expanded bytes of the original application
with its saved application settings merged, complete saved-setting preservation,
and another operational-status read. Point-name recovery also verifies the original
published Object_Name. A partial image, a changed saved value or a nonoperational
controller remains uncertain and blocked.

The receipt retains its failed/uncertain original intent and result. Its append-only
readback says that the proposed change was not verified, records the original
backup and original-image proof, and clears the unresolved-station lock only after
that proof succeeds. The outcome survives restart and appears distinctly in the
existing identity/default/wire/point-name views. It is never relabelled as a
successful application of the proposed change.

This action verifies an original recovery that already happened. It does not send
an application, restart, retry, rollback, or restore command. Capture/readback can
still enter/end backup mode as declared by the native backup profile. Runtime
calibration and retained read-only timestamp qualifications remain separate.

Owned UDP tests cover name, instance and point-name recovery, persistence across
restart, unchanged restore dispatch counts, and rejection of identity-only,
changed-image, changed-setting and nonoperational recovery claims.
