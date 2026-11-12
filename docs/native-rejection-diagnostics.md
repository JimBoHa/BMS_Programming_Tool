# Native transport rejection diagnostics

A structured BACnet WritePropertyMultiple error stores its class and code in
`errorType`. The inherited library formatter can instead raise `AttributeError`
while trying to read a nonexistent top-level `errorCode`. Previously this could
mask the controller's rejection with an HTTP 500 and obscure its protocol cause.

The native application transport now reads the structured or simple error fields
directly, bounds fallback text and preserves the actual rejection as the exception
cause. Both raised and returned errors follow that path. It adds no write method,
retry, permission, configuration support or automatic reconciliation. A negative
reply remains a rejection; multiple-property partial completion still requires
the operation's independent readback and recovery rules.

Regression checks cover the actual library error class whose formatter fails,
raised and returned responses, the preserved cause, one dispatch, ordinary errors
and a broken fallback formatter. A field qualification encountered this formatting
failure; independent reads showed the selected setting unchanged. The controller
did not accept that configuration change.
