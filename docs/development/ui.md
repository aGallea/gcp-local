# Browser UI — developer guide

This document is for contributors working on the browser UI bundled with `gcp-local`. If you only want to *use* the UI, see the relevant per-service usage doc (e.g. [`docs/services/gcs.md`](../services/gcs.md)). For the architectural picture of how the UI plugs into the rest of the emulator, see [`docs/architecture/overview.md`](../architecture/overview.md).

## Architecture at a glance

The UI is a single React SPA. There is no per-service frontend; one bundle covers every service.

| Piece | Path | Purpose |
|---|---|---|
| Source | `web/` | Vite + React + TypeScript app. |
| Build output | `src/gcp_local/ui/static/` | Production bundle (committed). Served as static files by FastAPI. |
| Mount point | `GET /ui/` on the admin port (4510) | StaticFiles mount with SPA fallback so deep links like `/ui/gcs/my-bucket` work. |
| Backend API | `src/gcp_local/core/ui_api/` | Versioned, internal `/_emulator/ui-api/v1/...` namespace consumed by the SPA. |
| Storage | The same `Storage` instances the wire-level emulators use | Reads and writes flow through `GcsStorage` (and equivalents for future services), so the UI and clients share one source of truth. |

The ui-api is intentionally **separate from the GCS / BigQuery / etc. wire surfaces**. Client libraries continue to talk to port 4443 (GCS), 9050 (BigQuery), etc.; the SPA never calls those. This keeps the wire surfaces faithful to the real GCP APIs and lets the UI evolve its own JSON shape independently. The two namespaces meet at the in-process storage layer.

The list of services with a UI surface in the current release is the constant `UI_SUPPORTED_SERVICES` in [`src/gcp_local/core/ui_api/router.py`](../../src/gcp_local/core/ui_api/router.py). Services not in that set still appear in the sidebar but render as greyed-out "coming soon" entries.

## Dev loop

One-time setup:

```bash
cd web
npm install
```

Run the live-reload dev server (Vite on 5173, with `/_emulator/*` proxied to the running emulator on 4510):

```bash
npm run dev
```

In a second terminal, start the emulator the way you normally would (`python -m gcp_local`). Edit files under `web/src/`; Vite picks up the changes.

To refresh the production bundle that ships in the Python package:

```bash
npm run build
```

The build emits to `../src/gcp_local/ui/static/`. **Commit the output** along with your source changes — CI fails if the committed bundle drifts from a fresh build (see [Quality gates](#quality-gates)).

## Quality gates

```bash
npm run lint    # ESLint flat config
npm test        # Vitest
npm run build   # type-checks (tsc -b) + emits the static bundle
```

CI runs these in the `web` job, then asserts that re-running `npm run build` produces no diff against the committed `src/gcp_local/ui/static/` tree. The `web` job gates the downstream Python jobs, so the bundle is always known-fresh when the unit/integration suites run. The Docker smoke test additionally verifies that the bundle is present in the published image and that the SPA fallback serves `index.html` for unknown sub-paths.

## Toolchain versions

The `web/` toolchain is current with the latest stable releases:

- React 19, React Router 7
- TypeScript 6
- Vite 8
- Vitest 4
- ESLint 10 (flat config)

CI uses Node 20 LTS. Local dev should match — older Node versions have not been tested.

When bumping any of these, run all three commands above and check the bundle hash in `src/gcp_local/ui/static/assets/` actually changes; it's easy to forget the rebuild and merge a stale bundle.

## Adding a service to the UI

Adding a new service mirrors the "Adding a service" checklist for the wire-level emulators (see [`adding-a-service.md`](adding-a-service.md)) but on the UI side. Follow-up specs (BigQuery UI, Pub/Sub UI, Secret Manager UI, Firestore UI) will each follow this recipe.

1. **Backend ui-api endpoints.** Add a module under `src/gcp_local/core/ui_api/<service>.py` exposing a `build_<service>_router()` function that returns an `APIRouter`. Routes return Pydantic models from `schemas.py`. Reuse existing `Storage` / engine instances rather than reaching into a new private state — the whole point of ui-api is to project the same in-process state the wire surface already exposes.
2. **Mount the router** in `src/gcp_local/core/ui_api/router.py` via `router.include_router(build_<service>_router())`, and add the service name to `UI_SUPPORTED_SERVICES` so the SPA stops greying it out.
3. **Typed client methods.** Extend `web/src/api/client.ts`'s `UiApi` with typed methods (`list<Resource>`, `create<Resource>`, etc.) and matching types in `web/src/api/types.ts`. Cover every new endpoint with a test in `client.test.ts`.
4. **Pages.** Place the React components under `web/src/services/<service>/` mirroring the GCS layout (a landing component, list pages, dialogs, preview / detail views). Components use CSS modules; tests use Vitest + React Testing Library.
5. **Sidebar label.** Add a human-readable label to `SERVICE_LABELS` in `web/src/components/AppLayout.tsx`.
6. **Routing.** Wire a route in `web/src/App.tsx` (`<Route path="/<service>/*" element={<ServiceLanding />} />`).
7. **Docs.** Add a "Browser UI" section to `docs/services/<service>.md`, an architectural note to `docs/architecture/<service>.md`, and a CHANGELOG entry.

Keep follow-up specs scoped to one service per PR — the UI codebase is small, but mixing service additions makes review and rollback harder.

## Quirk: folder placeholders

GCS has no first-class concept of a folder; the UI synthesizes folders from object name prefixes (`prefix=` + `delimiter=/`). To let users *create* an empty folder before any blob lives in it, the UI writes a 0-byte object whose name ends in `/` (e.g. `staging/`).

Most storage backends handle this cleanly. The disk backend (`DiskStorage`) does not — `staging/` on disk would collide with a real subdirectory used to store nested blobs. To avoid the collision, `DiskStorage` URL-encodes the trailing slash on the on-disk path: `staging/` is stored as `staging%2F`. The encoding is local to `DiskStorage`; in-memory and wire-format representations are unchanged. If you touch storage code, preserve this convention or you will silently break folder placeholders on `PERSIST=1`.
