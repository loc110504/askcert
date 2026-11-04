# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | Yes                |
| < 0.1   | No                 |

## Reporting a vulnerability

Please do not open a public issue for security problems.

Report vulnerabilities privately using GitHub's "Report a vulnerability" feature
(private vulnerability reporting) on the repository's Security tab:
https://github.com/loc110504/askcert/security/advisories/new

We aim to respond within 14 days on a best-effort basis.

## Scope notes

- Rules and evidence are parsed as data. They are never executed (no `eval` or `exec`).
- Resource exhaustion is bounded by the `max_nodes` and `timeout` limits. When a
  limit is exceeded, AskCert raises `ResourceLimitExceeded`.
- AskCert certifies conclusions relative to the supplied rules and evidence only.
  It does not verify that the evidence is true. Reports that a conclusion is wrong
  because the input evidence is wrong are not security vulnerabilities.
