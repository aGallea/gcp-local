# Adding a new service

This is the canonical checklist for contributors adding a new service to `gcp-local` (Pub/Sub, Firestore, etc.). Follow each step in order; each one references the existing BigQuery / GCS / Secret Manager implementations as templates.

The reason this doc exists: the existing service implementations are the source of truth for "what a service looks like in this repo". This checklist makes sure no piece (especially documentation) gets forgotten.

## 1. Spec

Brainstorm the v1 surface for the service. Decide which APIs are in scope, which are accepted-and-ignored, and which are out of scope.

- Save the spec to `docs/superpowers/specs/YYYY-MM-DD-<service>-design.md`.
- Reference the parent `docs/superpowers/specs/2026-04-24-gcp-local-core-design.md` for cross-cutting conventions.
- Use [`docs/superpowers/specs/2026-04-25-gcp-local-bigquery-design.md`](../superpowers/specs/2026-04-25-gcp-local-bigquery-design.md) as the structural template.

## 2. Plan

Write a TDD plan with bite-sized tasks under `docs/superpowers/plans/YYYY-MM-DD-<service>.md`. Use the BigQuery plan as a template.

The plan should declare a commit policy at the top so subagent-driven execution can commit per task on the feature branch.

## 3. Service package

Create `src/gcp_local/services/<service>/` with the established layout:

| File | Responsibility |
|---|---|
| `service.py` | Implements the `Service` protocol from `gcp_local.core.service`. Owns lifecycle (`start`, `stop`, `reset_state`, `health`). Constructs and tears down the FastAPI app or gRPC server. |
| `app.py` | FastAPI app factory + router wiring (REST services). For gRPC services this is `servicer.py` instead, returning the gRPC servicer. |
| `routes/` (REST) or `handlers.py` (gRPC) | Request handlers. One file per resource group. |
| `engine/` | Anything stateful that's worth its own subpackage (DuckDB connections, schema autodetect, load runners, session stores). |
| `models.py` | Domain dataclasses (records, schemas). |
| `storage.py` | Storage protocol + in-memory and disk-backed implementations. |
| `errors.py` | Service-specific exception types + REST/gRPC error envelope helpers. |
| `names.py` | Resource-name parsers and validators. |

The BigQuery, GCS, and Secret Manager packages are the working templates.

## 4. Register the service via entry point

Add the service to `pyproject.toml`:

```toml
[project.entry-points."gcp_local.services"]
<service> = "gcp_local.services.<service>.service:<Service>Service"
```

The CLI's service-discovery loop (in `gcp_local.core.registry`) instantiates whichever services are listed in the `SERVICES` env var (or all of them by default).

## 5. Tests

- **Unit tests** under `tests/unit/services/<service>/`. One test file per concern (routes, storage, engine, error mapping). Aim for behavior-focused tests, not implementation-detail tests.
- **Integration tests** under `tests/integration/test_<service>_integration.py` driving the real `google-cloud-<service>` Python client against an in-process emulator. The existing `emulator` fixture (in `tests/integration/conftest.py`) is the entry point.

`pytest`, `ruff check .`, `ruff format --check .`, and `mypy src/` must all pass before opening a PR.

## 6. Documentation

This is the bit that gets forgotten. The PR template's documentation checklist enumerates these — repeating them here for clarity:

- [ ] **`docs/services/<service>.md`** — user-facing usage doc. Template: `docs/services/bigquery.md`. Sections: elevator pitch, what's emulated, what's not emulated, connecting (Python client snippet), examples, limits & quirks.
- [ ] **`docs/architecture/<service>.md`** — internals deep-dive. Template: `docs/architecture/bigquery.md`. Sections: at-a-glance, wire & port, storage model, request lifecycle, error mapping, tests, internals-level limitations.
- [ ] **`README.md`** — add a row to the "Services at a glance" table; include both usage and architecture links.
- [ ] **`ROADMAP.md`** — if the service was on the Planned list, move it from Planned → In progress while the work is open, then delete the row when it ships (it now lives in the README table).
- [ ] **`docs/deployment.md`** — add a row to the default-ports table.
- [ ] **`CHANGELOG.md`** — add an entry under `[Unreleased]` describing what landed.

## 7. Pull request

- Open a PR to `master`.
- Fill out the PR template (`.github/pull_request_template.md`), including the documentation checklist above.
- Wait for CI to be green.
- Squash-merge when approved.
- Delete the feature branch (the GitHub PR UI does this with one click).

## 8. Verify the smoke flow

If maestro-evals or another consumer depends on the service, rebuild the gcp-local Docker image and bounce the local rancher-desktop deployment to verify end-to-end:

```bash
docker build -f docker/Dockerfile -t gcp-local:dev .
kubectl rollout restart deploy/gcp-local
kubectl rollout status deploy/gcp-local
```

Then run the consumer's smoke test.
