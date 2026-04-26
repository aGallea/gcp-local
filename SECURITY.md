# Security policy

`gcp-local` is a local-development emulator for Google Cloud services. It accepts unauthenticated requests by design and is not intended to handle real secrets or production data. The threat model is "developer's local machine" — not a public-facing service.

## Reporting a vulnerability

The preferred channel is **GitHub Security Advisories** on the [`aGallea/gcp-local`](https://github.com/aGallea/gcp-local/security/advisories) repository.

Backup channel: email **asafgallea@gmail.com**.

We acknowledge security reports within **7 days** and aim to release a fix within **30 days** for issues that fall in scope.

## In scope

- Vulnerabilities in code that runs as part of the emulator process: arbitrary code execution, container escape from the published Docker image, sandbox escape from the DuckDB execution engine.
- Path traversal or sandbox escape from the on-disk persistence layer when `PERSIST=1`.
- Vulnerabilities in our build / release pipeline that could be used to compromise users.

## Out of scope

`gcp-local` runs locally and accepts any request. The following are intentional design choices, not vulnerabilities:

- Lack of authentication on emulator endpoints.
- Lack of TLS on emulator ports.
- Predictable / fake resource IDs and tokens (`AnonymousCredentials` works against every endpoint).
- Denial-of-service against an emulator running on a developer's laptop.
- "Information disclosure" of fake data the emulator itself fabricated.

If you are unsure whether something is in scope, file the report — we'd rather triage and explain than miss a real issue.
