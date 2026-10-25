# Audit content before publication

Keep field captures, local configuration, credentials and audit profiles outside
source control. Source examples should use loopback or documentation addresses
instead of an actual site's network.

The standard-library audit script reports categories, paths, line numbers and
Git object IDs without printing matched addresses or credentials:

    python scripts/privacy_audit.py --private-rules /private/path/rules.json
    python scripts/privacy_audit.py --history --private-rules /private/path/rules.json

The first command reads tracked working files, including staged additions. The
second reads unique blobs and commits reachable from local Git refs, including
deleted historical content. Fetch the intended remote refs before a history
audit. A finding or an oversized/unreadable object gives a nonzero exit status.
Use --output /private/path/report.json to retain a private report.

The private profile has networks and secrets fields. A **synthetic example** is:

    {
      "networks": ["198.51.100.0/24"],
      "secrets": {"operator-credential": "example-value-not-a-real-password"}
    }

Supply actual site rules only through an untracked private profile. Known-secret
checks cover literal, JSON-escaped, URL-encoded, base64 and UTF-16LE forms. Without
a private profile, the scanner checks common GitHub token and complete PEM
private-key patterns; it cannot identify an arbitrary site's addresses/passwords.
Literal key-header checks used by validators are not themselves private keys.

Review findings before remediation: an exact literal can also occur as an
ordinary role name, authored fixture or coincidental document data. Do not
publish raw captures or secret values to explain a finding.

This is a targeted publication check, not proof that every encoding or secret is
absent. Compressed archives, rendered images, hosted PR text, workflow logs,
release assets, stale server refs and external clones need separate inspection.
The script does not edit files, rewrite history, delete hosted content or revoke
credentials. Removing current text does not remove a historical copy.
