# JCT configuration connection

Settings → Communications & network → JCT configuration connection establishes
BMS Studio's own authenticated session with a JCT configuration service. It does
not borrow a browser session or reuse an online Metasys login token.

Enter the HTTPS service origin, an existing configuration account and the
service's previously trusted SHA-256 certificate fingerprint. Sign in, read the
archive list, select an archive, then read its devices and inspect an object's
configuration. This profile uses the configuration authentication realm,
`/offline/api/private-api`, and the native tool's archive inventory. An online
`/API/private-api` login is a separate authority.

The service origin and certificate fingerprint may be supplied by a private
`jct-service-profile.json` in the application's state directory:

```json
{
  "server_origin": "https://configuration.example",
  "certificate_sha256": "<64 lowercase hexadecimal characters>"
}
```

This optional profile contains no credentials. Keep deployment-specific profiles
out of the repository. A certificate mismatch stops sign-in before credentials
are sent. The connection does not disable TLS chain or time validation, follow
redirects, discover proxies or automatically retry authentication.

## Session and inspection scope

Passwords clear from the form on submission and are never saved. The backend
holds the remote session token in memory; the browser receives only an opaque
local connection key. Navigating between tasks retains an established connection
in the current workspace. An unfinished sign-in is retired when its view closes,
and any late successful login is closed locally. Closing the connection, native
HTTP 401 or application shutdown retires access. Twenty minutes of inactivity
expires access on the next connection operation.
There is no automatic reauthentication. Local API session/origin guards remain
in force, and no BACnet interface opens as a consequence of this connection.

Archive identities belong to the explicitly selected archive. They are never
silently substituted for online object identities. An archive can be stale;
reading it does not establish agreement with a running engine, live values or
permission to deploy it. Inventory responses are bounded; no exhaustive-site
claim is made from one page.

Object inspection masks credential-named fields and schema-declared password
fields, including defaults. Ordinary unknown configuration fields remain in the
display projection. That projection is explicitly neither an editable document
nor a recoverable native backup. Native capture/export must preserve its own
original, protected evidence rather than use a redacted display response.

This profile admits authentication and archive metadata reads only. It rejects
archive editing, archive creation, transfer jobs and online object paths before
HTTP dispatch. It adds no controller download, source remapping or field write.
The next source-edit slice still needs a fresh supervisory capture, a qualified
native archive edit and transfer contract, isolated field acceptance, and
independent identity/link/value preservation checks. See the
[source-method investigation](metasys-source-qualification.md) and
[SCT/JCT roadmap](sct-jct-parity-roadmap.md).

## Verification

Authored HTTP peers cover the separate authentication realm, exact archive and
object selection, foreign resources, forbidden mutations, credential masking,
browser-owned connection keys, expiry, native refusal and disconnect during a
read. Browser tests cover desktop and compact layouts, archive inspection,
rejected login, expired sessions, delayed profile hydration and late sign-in
cleanup in Chromium and WebKit. These tests establish software behavior; they
do not qualify archive edits, supervisory transfers or live source changes.
