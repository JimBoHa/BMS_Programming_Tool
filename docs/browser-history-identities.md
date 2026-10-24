# Exact supported browser history identities

Alarm delivery and Trends & alarms now refuse identities the browser cannot represent safely. Supported numeric row IDs are integers from 1 through 9007199254740991. Pagination cursors may also be 0. This is an explicit browser profile; the SQLite stores and APIs retain their existing 64-bit identity support.

The completed-delivery prune field accepts canonical unsigned decimal whole-ID text. Surrounding whitespace is trimmed. Signs, leading zeros, decimal fractions, exponent notation, empty text and IDs outside the supported range are refused. Validation uses `BigInt` before any `Number` conversion, so typed 9007199254740993 cannot become 9007199254740992 in a request. A refusal sends no prune request.

Received delivery IDs, event references, alarm IDs, trend sequences and continuation cursors must be positive safe integer Numbers before the page publishes actionable rows. Invalid pages clear their row actions and cursors and show a refusal. They do not claim that no records exist. Safe route/source filters remain available so an operator can select a supported page. Display-only unsupported route/event cursors are labeled rather than printing rounded digits. String route and observation-source identities remain separate.

Download, retry, discard, acknowledgment, event selection and paging recheck the selected identity before constructing an operation or query. The delivery download also requires the returned ID to match the selected safe ID. It saves the original server response Blob, preserving nested payload numbers even though those values are not interpreted as browser action identities. Normal small-ID operations retain their existing behavior. This does not add a full 64-bit browser identity protocol, change native evidence or canonical Program numbers, or alter backend history, alarm, retry or retention semantics.

Tests seed real ephemeral SQLite stores with delivery, alarm, event and trend IDs at and above 9007199254740993. Exact API source is checked independently in Python. Actual browser tests prove that unsupported identities cannot dispatch a wrongly targeted action/query, malformed prune tokens never send a mutation, safe filters recover, and supported download/retry/discard/prune/acknowledgment/event workflows still work. A safe delivery's downloaded bytes match the actual response and retain a nested 9007199254740993 payload ID under independent Python parsing. Test routes stay paused, all endpoints are local, and field interfaces remain closed.

Each browser worker owns a separate seeded server and temporary store; ordinary Playwright runs require no global history clear or private seeding configuration. For installed-package acceptance, `BMS_TEST_INSTALLED_TARGET` selects the child server's sole package search target and a working directory outside the checkout. The harness refuses a package import outside that target, a source-checkout resolution or missing bundled UI/metadata, and prints its resolved package/resource paths. Test and seeding helpers remain separate from the installed product. Installed-package execution is a separate acceptance run; source checks alone do not establish it.

The seeded Chromium/WebKit lane comes from Playwright's actual `browserName` fixture. A project display name can be empty or arbitrary; it is not a seeded route/source identity. The fixture explicitly refuses an unsupported browser type instead of choosing a different lane. This fixes both the repository's unnamed default Chromium project and installed acceptance configurations that name a WebKit project differently.

From `web`, install the desired browser and run the supported lane explicitly:

```sh
npx playwright install chromium webkit
npx playwright test tests/browser-history-ids.spec.ts --browser=chromium
npx playwright test tests/browser-history-ids.spec.ts --browser=webkit
```

For a custom configuration with a `projects` list, select its declared display name with `--project=<name>` and set that project's `use.browserName` to `chromium` or `webkit`. Do not assume that `--project=webkit` exists in the repository's default configuration: it declares no named projects. An installed-package runner must additionally set `BMS_TEST_INSTALLED_TARGET` in the parent Playwright environment so the isolated history child imports the same installed payload; its main app server must also resolve that payload outside the checkout. Changing only the main server's environment does not bind test-created child servers. Validation runs against an immutable wheel preserve the original installed files and keep test-only adaptations separate.
