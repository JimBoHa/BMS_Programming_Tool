# Authored native peer fixture isolation

The shared `native_link` test fixture now explicitly collects cyclic garbage
from completed tests before opening its own UDP endpoints. Automatic garbage
collection keeps its existing enabled state and thresholds. All requests, reply
validation, test assertions and operation/request bounds remain unchanged.
Production application and interface sources are unchanged.

## Observed reproduction

An opt-in diagnostic run retained the original selected case order through the
initialized-input case: 503 cases passed and that case failed. The client and
authored peer metadata identify the same input-property request and invoke ID.
The peer observed the request promptly, then a generation-2 collection paused
the shared process for 107.936 ms before it could hand off its acknowledgment.
The request's existing timeout was 100 ms; the overall operation limit was
1,800 seconds.

| Event | Milliseconds from client exchange start |
| --- | ---: |
| Peer observed request | 0.158 |
| Generation-2 collection started | 1.153 |
| Generation-2 collection stopped | 109.089 |
| Peer called acknowledgment handoff | 109.723 |
| Client observed timeout | 110.008 |

The collection reclaimed 152,913 objects. It overlapped the response window and
lasted longer than that entire window. That explains the timeout in this traced
reproduction. The failed attempt returned `not_sent` with no new transfer intent;
earlier successful operations in the same test retain their own evidence.

The [retained trace summary](validation/native-peer-gc-reproduction.json) contains
only authored-loopback metadata and relative times. It is an API receive/handoff
trace with GC callbacks, not a socket packet capture. Instrumentation may affect
scheduling. These observations do not establish the cause of an earlier untraced
failure merely because it has the same test name or later passes.

## Scope of the fixture change

Collection runs once during fixture setup before that fixture creates sockets,
starts a native operation or arms a request timeout. The explicit full collection
therefore runs outside this fixture's timed exchanges.
The change neither disables automatic collection nor adds a network retry,
response delay allowance or controller action. Actual missing or malformed
replies still require the existing rejection and uncertainty behavior.

The same 504-case prefix passes with the change. Its diagnostic trace records a
75.961 ms full collection during fixture setup; collections during the initialized
input test itself remain below 1 ms. This is one observed comparison, not a host
performance guarantee.

Qualification retains the original prefix and broader native tests, including
negative timeout, cancellation, single-attempt restore and readback assertions.
Historical Schedule, File/native, commit, startup, input
readback and browser observations retain their original unresolved scope where
their own tracing does not establish a cause. Physical/Bluetooth acceptance and
general native compilation remain separate.
