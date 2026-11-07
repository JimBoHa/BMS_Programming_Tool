# Matching-connection review lifetime

Matching-connection controller actions now check their current editor and review
generations synchronously when the action is invoked. A handler retained before
visibility/page exit, a pair or destination change, task close/reopen or a native
workspace switch cannot dispatch an old Apply request. A late valid preview does
not restore authority after those changes, including coalesced away-and-back
events. Cancellation remains scoped to the owned operation ID.

The parent editor supplies a separate disclosure generation and its existing
source/prototype/pair generation. Native workspace generation and current-state
checks retain the ordinary/batch task boundary. Local drafts and local-copy
reviews retain their existing behavior; disclosure changes retire field authority
without clearing the bounded wire cache or fabricating a new source.

The task can close while a review is being prepared. Capture, Apply and readback
lock the summary alongside the existing controls and workspace navigation, so a
summary click cannot cancel a controller-command phase. Explicit cancellation
keeps its original behavior. Completing or cancelling an older operation cannot
release a newer busy owner.

Review retirement does not discard an active transfer's late receipt. Original
target, exact response exports, uncertainty, retained receipt loading and explicit
readback keep their existing contracts. Readback never replays a restore.

Qualification uses authored localhost BACnet peers. The baseline counterexample
intercepted the stale HTTP request before the server, so no restore was performed.
The repair changes no native compiler, server admission, transfer journal,
preservation rule, timeout, retry policy, layout or stylesheet. It establishes no
new physical, BTCVT, runtime or CCT acceptance scope.
