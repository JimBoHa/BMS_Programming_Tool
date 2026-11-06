# Reproducible CI browser environment

The Linux wheel/release-verification job runs in the official Playwright Ubuntu
24.04 image matching the locked `@playwright/test` version, **1.56.1**. The image
is pinned by its multi-platform manifest digest:

`mcr.microsoft.com/playwright:v1.56.1-noble@sha256:f1e7e01021efd65dd1a2c56064be399f3e4de00fd021ac561325f2bfbb2b837a`

The image includes the corresponding browser binaries and operating-system
libraries. The job still installs the project's locked JavaScript dependencies
and verifies that Chromium and WebKit executables exist before running the same
browser acceptance suite. `--init` and `--ipc=host` follow Playwright's container
recommendations for trusted test code. Shell steps retain Bash semantics.

This replaces per-run Ubuntu package downloads during `playwright install
--with-deps`. Two consecutive unchanged-source runs exhausted the existing
25-minute job limit downloading packages from the runner's Azure Ubuntu mirror;
browser tests had not started. Original logs are retained outside Git. The
deadline, browser tests, test assertions, dependency locks, packaging/provenance
and privacy checks, documentation/SBOM audit, desktop matrix and release gates
remain unchanged. The image is a CI environment, not part of the distributed app.

Packaging regressions retain subprocess output in exception locals. The CI
invocation uses `--showlocals` so a failed isolated wheel build exposes its
captured output instead of only the subprocess exit status. This changes failure
diagnostics, not the test selection or acceptance conditions.

When changing the Playwright package version, select its matching official image,
verify the immutable manifest digest against Microsoft Artifact Registry, and
update the lock and image pin together. A passing package install is not a browser
test; require the actual browser acceptance and all desktop packaging jobs.

References: [official Docker image and version guidance](https://playwright.dev/docs/docker),
[official CI guidance](https://playwright.dev/docs/ci).
