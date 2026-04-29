# Claude / agent instructions for `gcp-local`

This repo is an open-source local emulator for GCP services. Contributions land via PRs against `master`. AI agents working in this repo (Claude Code, Copilot, etc.) must follow the Definition of Done below in addition to the conventions in `CONTRIBUTING.md`.

## Definition of Done

**Every PR — including bug fixes — must update both docs and tests for the touched area. The agent self-audits before reporting work complete; the user should never have to ask "did you update the docs / tests?"**

### Docs audit checklist

For every change, walk this list and update what applies. If nothing applies, state that explicitly when summarizing the PR.

- [ ] **`docs/services/<service>.md`** — user-facing usage doc. New flags, new endpoints, changed semantics, changed defaults, new env vars all belong here. Remove any "What's not emulated" bullet the change closes.
- [ ] **`docs/architecture/<service>.md`** — internals. Update step-by-step flow descriptions, request lifecycles, data-model notes. Remove any "Internals-level limitations" bullet the change closes.
- [ ] **`README.md` services-at-a-glance table** — only when status (Alpha → Stable, Planned → Alpha) or wire/port changes.
- [ ] **`ROADMAP.md`** — remove any in-progress, planned, or per-service follow-up bullet the change closes. Move bullets between tiers as appropriate.
- [ ] **`CHANGELOG.md`** — add an entry under `[Unreleased]` (`### Added`, `### Changed`, `### Fixed`, or `### Removed`). If the change closes a "Known limitations" line under the latest released version, remove or amend that line.
- [ ] **Design specs in `docs/superpowers/specs/`** — when a spec said "deferred" or "all-or-nothing" or any other property the new change reverses, annotate the original spec line so future readers see the supersession instead of being misled.
- [ ] **Inline code comments** — remove any "// TODO: support X" left dangling after X ships; remove any comment in `engine/loads.py` etc. that contradicts the new behavior.
- [ ] **`pyproject.toml`** — when a new module imports a third-party package at module-level, that package belongs in the runtime `dependencies` list, **not** in `optional-dependencies.dev`. Otherwise the production Docker image (which runs `pip install .`) crashes at import.

### Tests audit checklist

- [ ] **Unit tests** — every helper or function with non-trivial logic gets a unit test exercising the happy path + at least one error/edge path. Use existing fixtures (`tests/unit/services/<service>/`).
- [ ] **Integration tests** — when a change is reachable from a real Google client library (`google-cloud-bigquery`, `google-cloud-storage`, etc.), add an integration test that drives the wire path end-to-end (`tests/integration/test_<service>_integration.py`). Unit tests verify implementation; integration tests verify the contract.
- [ ] **Error paths** — explicitly cover the failure modes the change introduces (missing fields, invalid input, network errors). Don't only test success.
- [ ] **Defaults** — verify that default behavior is unchanged when new flags / fields are not supplied.
- [ ] **Regressions** — run the full suite (`pytest tests/ --ignore=tests/integration/test_docker_image.py`) before committing.
- [ ] **Docker test (when changing imports / deps)** — if the change adds an import or moves a dependency, build the Docker image locally and verify the affected service container becomes healthy (`docker run -e SERVICES=<svc> gcp-local:dev`). The CI `docker` job runs this; catch it before pushing.

### Quality gates

Before committing:
- `ruff check src/ tests/` — clean
- `ruff format src/ tests/` — clean
- `pytest tests/ --ignore=tests/integration/test_docker_image.py` — green

Before claiming "ready for PR" / "all checks pass":
- Walk both audit checklists above and report what was audited and updated, even if some bullets weren't applicable.
- Note any cross-cutting impact: stale comments, contradictory specs, "Known limitations" lines that the change supersedes.
- Verify CI (`gh pr checks <N>`) actually passed; don't conflate "tests pass locally" with "CI is green."

## Repo conventions

- **Conventional Commits**: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. Subject in imperative mood, ≤72 chars; body explains the *why*.
- **Branch naming**: `feat/<short-name>`, `fix/<short-name>`. Branch off `master`.
- **PR size**: target <400 LOC of production-code changes per PR; flag anything over 500. Tests and docs don't count toward the production-code budget but should still be reviewable.
- **Don't combine unrelated changes** — process/tooling updates ship in their own PR, not bundled with feature work.
- **Never bypass hooks** (`--no-verify`) or skip CI without explicit user approval.
- **Don't commit unless the user explicitly asks** — staging and proposing a commit is fine; running `git commit` is not, until told to.

## Architecture quick-reference

- Each service lives under `src/gcp_local/services/<name>/` and exposes a `Service` class registered via the `gcp_local.services` entry-point group in `pyproject.toml`.
- Services share a common framework: `Context` (port overrides, persistence flag), `StateHub` (cross-service event bus), admin API on port 4510 (`/_emulator/{health,services,reset}`).
- BigQuery is REST + DuckDB; GCS is REST + filesystem/in-memory storage; Secret Manager is gRPC.
- Adding a service: see `docs/development/adding-a-service.md`.
