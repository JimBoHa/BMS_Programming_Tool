# Simulation browser evidence and test cleanup

Use `test` from `simulationFixture` for page-driven local simulation. The fixture forwards matching step/scenario POSTs exactly once with `route.fetch({maxRedirects:0,maxRetries:0})`, retains a private copy of the actual HTTP body, and fulfills the page with the unchanged bytes. It does not alter application code, retry requests, enumerate calculation sessions or clear a server cache.

Chromium can expose an empty `PageResponse.body()` for the app's `fetch().blob()` path despite a complete HTTP body and successful UI update. `simulationServerResponseText/JSON` reads the actual HTTP capture keyed by the exact PageRequest. These helpers represent the server reply, not a deliberately forged response delivered by a fault test. Keep separate UI acceptance/rejection assertions.

A custom held/fault step or scenario handler must call `fetchSimulationResponse(route)` instead of `route.fetch()`. It records actual evidence before the test delays or changes delivery. Forward unchanged responses using `{response, body:await response.body()}`; intentional JSON faults retain their explicit overrides. Default context routes survive `page.unroute()` and teardown removes only the fixture's own handler.

Ownership requires the exact source page/origin, matching request/response URL, HTTP200, a new-session POST, original creation nonce and returned ownership token/creation nonce. It derives from the original server reply rather than a forged page delivery. Closing a page with a held reply still permits retirement of the proved engine. Failed acquisitions never nominate a guessed ID; their outcome retains the product's expiry policy and is annotated. Cleanup continues for all previously proved handles even if another acquisition fails.

Tests exercise exact request/backend integers with independent Python checks, private-buffer protection, one actual POST/one created engine, malformed source/nonce/status refusals, held delivery, acquisition failure and an independent retained engine. This is test resource management, not a claim that document-exit cleanup is guaranteed in the product.
