# Services UI — Foundation + GCS pilot (design)

**Status:** Draft, pending implementation
**Date:** 2026-05-03
**Scope:** Sub-project 1 of a multi-spec effort. Establishes the UI foundation (shell, tech stack, embedding model, conventions) and ships a fully featured GCS browser as the pilot service. BigQuery, Secret Manager, Pub/Sub, and Firestore UIs are deferred to follow-up specs that build on this foundation.

## Goal

Give users of `gcp-local` a browser-based way to browse and manipulate emulator state instead of relying on `gcloud`/`gsutil`/Python clients. Long-term destination is a "GCP console clone" covering all five services. This spec covers the foundation and the GCS pilot — enough to validate the architecture under real use before layering on the remaining services.

The UI is **not** a wire-protocol surface — it does not replace the GCS REST API, BigQuery REST API, etc. It is a separate inspector/operator layer that reads from and writes to the same underlying storage as those APIs.

## Non-goals

- Replacing or competing with the existing wire APIs.
- Authentication / authorization. The emulator is local-only; the UI inherits that posture and documents it.
- Internationalization, dark mode, telemetry, accessibility audits beyond reasonable defaults.
- Real-time updates (websockets/SSE). List views are pull-on-mount with a manual refresh button.
- BigQuery, Secret Manager, Pub/Sub, Firestore UIs (each gets a dedicated follow-up spec).

## Scope of GCS pilot

In:

- **Buckets:** list, create (name + location), delete (with empty/force confirmation).
- **Blobs:** list within a bucket (prefix/folder navigation), upload (drag-drop or file picker), download, inline preview (text/JSON/image, with size caps), delete.
- **Display:** show name, size, content-type, updated time, generation in list and detail views.

Deferred:

- Edit blob metadata (content-type, custom metadata).
- Copy / rename blob.
- Search/filter within a bucket beyond prefix navigation.
- Bulk select / bulk delete.

## Architecture

### Delivery model

A React SPA (TypeScript, Vite) lives under a new `web/` source tree. Production bundle is built by CI and shipped inside the Python wheel under `src/gcp_local/ui/static/`, and inside the Docker image via a multi-stage build. The existing FastAPI admin app on port **4510** mounts:

- `/ui/` — `StaticFiles` serving the bundled SPA (with HTML5 history-API fallback to `index.html`).
- `/_emulator/ui-api/v1/...` — JSON API consumed by the SPA.

This keeps the single-binary, single-port story the project values: one `pip install`, one Docker image, one URL to remember.

### Why a dedicated `ui-api` namespace

The existing GCS REST API on port 4443 emulates Google's wire format — that is the contract under test. The UI needs richer responses (paginated listings with computed sizes, inline preview metadata, friendlier error shapes) that would muddy that contract. The `ui-api` is therefore a thin presenter layer that:

- Lives in `src/gcp_local/core/ui_api/`.
- Reads from and writes to the **same** underlying storage backend the GCS service uses, via a shared `Storage` interface — no extra wire hop, single source of truth for state.
- Versioned `v1` for our own honesty about breaking changes; explicitly documented as **internal**, not for external clients.

**Alternative considered:** have the UI call the GCS REST API in-process over loopback. Rejected: it adds a wire hop and CORS handling for no real benefit, conflates two ports in the user's mental model, and forces UI shape onto the wire contract.

**Alternative considered:** server-rendered HTML (Jinja2 + HTMX). Rejected per user preference for a richer SPA experience and a higher ceiling for future services that will want syntax-highlighted SQL editors (BigQuery), nested document trees (Firestore), and live message tails (Pub/Sub).

### Component layout

```
src/gcp_local/
  core/
    admin_api.py               # extended to mount /ui/ + ui-api router
    ui_api/
      __init__.py
      router.py                # FastAPI APIRouter, prefix=/_emulator/ui-api/v1
      gcs.py                   # GCS endpoints (delegates to Storage)
      schemas.py               # Pydantic request/response models
      errors.py                # error-envelope helpers
  ui/
    __init__.py
    static/                    # built React bundle (committed via CI)
      index.html
      assets/...
  services/gcs/
    storage.py                 # existing — exposes the Storage interface ui-api uses

web/                           # React source tree
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  src/
    main.tsx
    App.tsx
    api/                       # typed client for ui-api
    components/                # shared shell: AppLayout, ServiceNav, EmptyState, Toast, etc.
    services/
      gcs/
        BucketList.tsx
        BucketView.tsx
        BlobList.tsx
        BlobUploadDialog.tsx
        BlobPreview.tsx
    theme/                     # CSS modules / design tokens
```

The `web/src/services/gcs/` subtree is the template each future service follows in its own follow-up spec.

### UI shell

Layout: persistent left sidebar listing services (GCS active for v1; others rendered as disabled "coming soon" entries) and an Admin section (Health, Reset). Main pane shows the selected service. A thin top bar shows breadcrumbs and the emulator host (e.g., `localhost:4510`).

The shell ships ready for additional services — adding BigQuery means a new `web/src/services/bigquery/` subtree and one entry in the sidebar config, nothing else.

### JSON API surface (ui-api/v1)

```
GET    /_emulator/ui-api/v1/services
GET    /_emulator/ui-api/v1/gcs/buckets
POST   /_emulator/ui-api/v1/gcs/buckets
DELETE /_emulator/ui-api/v1/gcs/buckets/{bucket}                       (?force=bool)
GET    /_emulator/ui-api/v1/gcs/buckets/{bucket}/blobs                 (?prefix=, ?delimiter=, ?page_token=)
POST   /_emulator/ui-api/v1/gcs/buckets/{bucket}/blobs                 (multipart upload)
GET    /_emulator/ui-api/v1/gcs/buckets/{bucket}/blobs/{name}          (metadata + small inline preview if previewable)
GET    /_emulator/ui-api/v1/gcs/buckets/{bucket}/blobs/{name}/download (raw bytes)
DELETE /_emulator/ui-api/v1/gcs/buckets/{bucket}/blobs/{name}
```

Pydantic models in `ui_api/schemas.py`. Errors use the envelope `{"error": {"code": str, "message": str}}` and never leak stack traces, filesystem paths, or secrets.

## Dev workflow

- `cd web && npm install && npm run dev` — Vite dev server on `:5173`, proxies `/_emulator/*` to `:4510` so a developer can iterate on UI without rebuilding the bundle.
- `npm run build` — emits the production bundle to `src/gcp_local/ui/static/`.
- `python -m gcp_local` — serves the built bundle from `:4510/ui/`.
- `npm run lint` (eslint) and `npm test` (vitest) for frontend quality gates.

If `src/gcp_local/ui/static/index.html` is missing at runtime (e.g., editable install without a build), `/ui/` returns a friendly 404 page with build instructions instead of crashing the server. The rest of the emulator continues to work normally.

## Build / CI / Docker

- **GitHub Actions:** new `web` job — install node 20, `npm ci`, `npm run lint`, `npm test`, `npm run build`. The Python jobs depend on this so the bundle is in place for the wheel build and the Docker test.
- **Docker:** multi-stage build. Stage 1 = `node:20-alpine` runs `npm ci && npm run build`. Stage 2 = existing Python image, copies the bundle into `src/gcp_local/ui/static/`.
- **Wheel:** `pyproject.toml` includes `src/gcp_local/ui/static/**` as package data so `pip install gcp-local` ships a working UI. The wheel-publish workflow runs the web build before `python -m build`.
- **Local editable install:** developers run `npm run build` once after cloning. `CONTRIBUTING.md` documents this; the runtime fallback (above) handles the gap.

## Testing strategy

- **Python unit tests** (`tests/unit/core/test_ui_api_gcs.py`): each ui-api endpoint, happy + error paths, against the in-memory storage backend. Use existing GCS test fixtures.
- **Python integration test** (`tests/integration/test_ui_api_integration.py`): full FastAPI client + filesystem storage, exercises upload → list → preview → download → delete end to end.
- **Frontend unit tests** (`web/src/**/*.test.tsx`, vitest + React Testing Library): per-component, mocked fetch.
- **Docker smoke test:** existing `tests/integration/test_docker_image.py` extended to curl `/ui/` and assert `index.html` is served, plus one `ui-api` endpoint round-trip.
- **No e2e browser tests in v1.** Playwright is added when there is a stable shell worth pinning. Out of scope for foundation.

## Error handling and empty states

- Network errors → toast with retry button. Never a blank pane.
- Empty bucket / no buckets → illustrated empty state with primary CTA ("Create your first bucket").
- Backend errors follow `{error: {code, message}}` and surface `message` to the user verbatim.
- **Upload size cap:** 100 MB default for v1, configurable via `GCP_LOCAL_UI_MAX_UPLOAD_MB`. Larger uploads return a clear error explaining the cap before reading the body.
- **Inline preview caps:** 1 MB for text/JSON; images > 5 MB force a download instead of inline rendering. Binary types with no preview show metadata only and a Download button.

## Documentation updates (per repo Definition of Done)

- `docs/services/gcs.md` — new "Browser UI" section.
- `docs/architecture/gcs.md` — note the shared `Storage` interface and the ui-api consumer.
- `docs/architecture/overview.md` — add the UI layer to the architecture diagram and call out the ui-api namespace.
- New `docs/development/ui.md` — UI architecture, dev loop, build pipeline, conventions for adding a new service.
- `README.md` — short Browser UI section under Quickstart, screenshot, port reminder.
- `CHANGELOG.md` — `### Added` entry under `[Unreleased]`.
- `ROADMAP.md` — strike "UI" if currently listed as Future; add follow-up bullets for per-service UIs.
- `CONTRIBUTING.md` — document the `npm` toolchain expectation, build step, and lint/test commands.
- `pyproject.toml` — declare `src/gcp_local/ui/static/**` as package data.

## Out of scope (deferred to follow-up specs)

- BigQuery, Secret Manager, Pub/Sub, Firestore UIs — each gets its own spec layered on this foundation.
- O6 metadata edit, O7 copy/rename, N1 search, N3 bulk operations.
- Authentication, dark mode, i18n, telemetry, websockets/SSE.
- Multi-project navigation. The UI shows whatever the emulator currently holds; multi-project filtering is a future enhancement.

## PR boundary

Single PR. The work is large by repo conventions (likely 1500–2000 LOC of new production code spanning Python + TypeScript + CI/Docker), which exceeds the 400-LOC target and the 500-LOC flag. The user has explicitly chosen a single PR for this foundation work because the pieces are tightly coupled: shipping the React app without ui-api endpoints (or vice versa) yields a non-functional intermediate state. The PR description must call out the size, name foundation work as the justification, and link this spec.

## Open questions / risks

- **Bundle size in the wheel.** A React + Vite bundle is typically 150–300 KB gzipped, negligible for a developer tool. We will measure during implementation; if it ever crosses ~1 MB raw, revisit.
- **Node toolchain in CI/Docker.** Adds build time and a maintenance surface. Mitigated by pinning node 20 LTS and using `npm ci` (lockfile-driven, deterministic).
- **`Storage` interface coupling.** The ui-api depends on the GCS service module's storage abstraction. If the GCS internals refactor, the ui-api goes with them. This is intentional — single source of truth — but worth flagging.
