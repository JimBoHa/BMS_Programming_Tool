# Optional authenticated LAN access

The desktop editor starts on loopback. LAN sharing is opt-in and requires an
explicit address, port, allowed client networks and private access-code file.
No site values are release defaults. These examples use documentation addresses;
replace them with the actual computer/network before use.

Create a random access code with at least 24 characters in a file readable only
by the current user. Keep configuration and credentials outside the repository
and release folder. A private configuration has this form:

```json
{
  "profile": "bms-studio-lan/1",
  "host": "192.0.2.25",
  "port": 8773,
  "allowed_networks": ["192.0.2.0/24"],
  "access_code_file": "/private/path/to/lan-access-code.txt"
}
```

On Windows, use the private Windows path with JSON backslash escaping. The code
file must not be group/world readable on POSIX. Empty network lists, `/0`,
unspecified/multicast bind addresses and short codes are refused.

Quit the desktop owner, then launch the installed executable with
`--share-config /private/path/to/lan-config.json`. On macOS it is
`/Applications/BMS Studio.app/Contents/MacOS/BMS Studio`; on Windows it is
`BMS Studio.exe` in the installation folder. The launcher shows the LAN URL and
owns both listeners. Its Open editor action uses loopback. A LAN port collision
fails explicitly rather than silently moving the published service.

An administrator can share an already running local editor without restarting
it using the alternative Python installation:

```sh
bms-share --config /private/path/to/lan-config.json --upstream http://127.0.0.1:8765
```

The upstream must be one HTTP loopback editor URL without credentials, path,
query or redirect following. The gateway binds the selected interface and does
not itself open BACnet, reconnect a device, resume a poller or grant write authority.

Operators open the LAN URL and sign in as `operator` using the private code.
Host, Origin and actual client subnet must match. Forwarded-IP headers cannot
bypass admission, and gateway credentials never reach the local editor. Original
session-token and field-operation checks remain in force. Operators share one
backend/interface/recovery store rather than independent per-user field sessions.

Ordinary LAN HTTP is supported even when the browser does not expose the
secure-context-only `crypto.subtle` and `crypto.randomUUID` APIs. The editor uses
local SHA-256 hashing and secure random bytes for UUIDs in that case. Source,
profile and downloaded-evidence hash checks still run; controller review and
write admission remain unchanged. A browser without secure random bytes refuses
operations that require new identifiers. HTTPS and loopback continue using the
native APIs when available.

HTTP Basic authentication does not encrypt traffic. Use HTTP sharing only on a
trusted LAN; use a TLS reverse proxy or secure VPN for untrusted transport.
Restrict the OS firewall to the intended network/port. Installation does not
silently create an inbound firewall rule.

Each request is forwarded once. If a response is lost during a field change,
inspect Changes and use the operation's explicit readback/recovery workflow
before deciding what to do next. Gateway restart never replays a prior request.

Rotate the private code and restart the gateway when access changes. Stop the
gateway/desktop listener to end LAN access. OS service/login startup remains an
administrator-managed choice; the installer does not enable it.
