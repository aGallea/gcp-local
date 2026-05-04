# Contributing to gcp-local

Thanks for your interest in contributing! This document covers local development setup, the PR workflow, and conventions specific to this project.

If you're adding a brand-new service (Pub/Sub, Firestore, etc.), read [`docs/development/adding-a-service.md`](docs/development/adding-a-service.md) first — that walks through every file you'll need to touch.

## Local development setup

Requirements:

- Python 3.13
- A POSIX-y shell (macOS or Linux). Windows users can use WSL2.
- Docker (optional, only needed if you want to test the container image)

Clone and install:

```bash
git clone https://github.com/aGallea/gcp-local.git
cd gcp-local
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the emulator from your checkout:

```bash
python -m gcp_local
```

Health check:

```bash
curl http://localhost:4510/_emulator/health
```

## Running the test suite

Unit tests (fast, no network):

```bash
python -m pytest tests/unit -v
```

Integration tests (drive the real `google-cloud-*` clients against an in-process emulator):

```bash
python -m pytest tests/integration -v
```

Lint and type-check:

```bash
python -m ruff check .
python -m ruff format --check .
python -m mypy src/
```

CI runs the same commands; if they pass locally they should pass in CI.

## Frontend toolchain

The browser UI (served at `http://localhost:4510/ui/`) lives under `web/`. It is a Vite + React + TypeScript SPA. Working on it requires Node 20 LTS — older Node versions are not supported.

One-time setup:

```bash
cd web
npm install
```

Day-to-day commands:

```bash
npm run dev    # Vite dev server on :5173, proxies /_emulator/* to :4510
npm run lint   # ESLint flat config
npm test       # Vitest
npm run build  # type-checks + emits the production bundle to ../src/gcp_local/ui/static/
```

The build output (`src/gcp_local/ui/static/`) is **committed to the repository** so the Python package ships with a pre-built bundle. After any change under `web/`, run `npm run build` and commit the regenerated bundle alongside your source changes. CI fails if the committed bundle drifts from a fresh build.

For the architecture walkthrough and the recipe for adding a new service surface to the UI, see [`docs/development/ui.md`](docs/development/ui.md).

## Branch + PR workflow

1. Create a feature branch off `master`. Branch names use the form `<service>` or `<service>-<topic>`, e.g. `bigquery-load-jobs` or `pubsub`.
2. Push the branch and open a pull request to `master`.
3. Fill out the PR template (`.github/pull_request_template.md`) — including the doc-update checklist if your PR adds or changes user-visible behavior.
4. CI must be green before merge.
5. We squash-merge to `master`. Delete the branch after merge (the PR UI offers this with one click).

## Commit message conventions

Existing commits follow the `<type>(<scope>): <subject>` form. Reuse it. Recognized types:

| Type | Use for |
|---|---|
| `feat` | A new user-visible feature |
| `fix` | A bug fix |
| `refactor` | Code change without user-visible behavior change |
| `perf` | Performance improvement without behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `chore` | Build / tooling / repo housekeeping |

Scope is the service name when the change is scoped to one service (`feat(bigquery): ...`). Use `core` for cross-cutting framework changes, or omit the scope when it would feel forced.

The PR title becomes the squash-merge commit subject, so the same convention applies to PR titles.

## Adding a new service

See [`docs/development/adding-a-service.md`](docs/development/adding-a-service.md) for the full checklist. Highlights:

- Brainstorm a spec → save to `docs/superpowers/specs/`.
- Write a TDD plan → save to `docs/superpowers/plans/`.
- Implement the service under `src/gcp_local/services/<service>/`.
- Register the service via the `gcp_local.services` entry point in `pyproject.toml`.
- Cover with both unit and integration tests.
- Update the docs listed in the PR template's checklist.

## Reporting bugs and requesting features

Use the GitHub issue templates at [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/). They prompt you for the context we need to triage quickly.

## Reporting security issues

See [`SECURITY.md`](SECURITY.md). The TL;DR is: GitHub Security Advisories preferred, `asafgallea@gmail.com` as the backup channel.

## Code of conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.
