# Security Policy

## Supported versions

Only the latest release on `main` receives security fixes.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Use GitHub's [private vulnerability reporting](../../security/advisories/new) for this
repository, or email `security@cloudandsre.com` with:

- a description of the issue
- a minimal reproducer
- the version(s) affected
- your assessment of severity

I aim to acknowledge within 72 hours and to ship a fix or mitigation within 14 days for
confirmed issues, with coordinated public disclosure once a fix is available.

## Supply chain

- GitHub Actions are pinned to full commit SHAs and kept current by Dependabot.
- Workflows run with least-privilege `GITHUB_TOKEN` permissions.
- CodeQL and OpenSSF Scorecard run on every push to `main` and weekly.
