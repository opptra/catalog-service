---
name: catalog-service-conventions
description: Architecture, layering, API contract, and workflow rules for the catalog-service repo. Use whenever writing, reviewing, or refactoring ANY code in this repository — the React client (client/) or the FastAPI server (server/). Covers where new code goes, the client/server API contract, how server code reaches external services (object storage, LLMs, HTTP APIs, the database) through reusable clients, dependency and secret policy, branch/PR workflow, and the lint/build verification to run after every change. These project rules override any conflicting default from a framework skill (fastapi, pydantic, supabase-postgres-best-practices, vercel-react-best-practices).
---

# catalog-service conventions

This is the project contract for the `catalog-service` repo. Follow it on every change so the
codebase stays consistent and anyone — regardless of engineering experience — produces correct
code the first time.

## Project shape

| Part | Stack | Location |
|------|-------|----------|
| Client | React 19 + TypeScript (strict) + Vite SPA, react-router-dom v7, axios | `client/` |
| Server | Python 3.12 + FastAPI + uvicorn | `server/` |

- **Plain SPA — no Next.js, no SSR, no React Server Components.** Ignore any Next.js/RSC/server-action
  guidance from framework skills; it does not apply here.
- Deploy: Google Cloud Build (`cloudbuild.yaml`) → GCE VM. In production nginx prefixes server routes as `/api/`.

## Golden rule

When this project skill conflicts with a framework skill's default (fastapi, pydantic, supabase-postgres-best-practices,
vercel-react-best-practices), **this project skill wins.** Framework skills tell you *how* to use the
library idiomatically; this file decides *how we structure and ship it here*.

## Workflow — do this every time

1. **Never push directly to `main`.** All work goes through a `feat/…`, `fix/…`, or `chore/…` branch and a PR.
2. **Verify before you finish.** After any change, run the verification commands for the part(s) you
   touched and fix every error and warning you introduced. Do not report a task complete with failing checks.
3. **Small, focused changes.** One concern per PR. Do not refactor unrelated code, rename files, or
   reorganize folders unless that is the task.
4. **Add dependencies deliberately.** Check whether something already installed covers the need, prefer
   well-maintained mainstream options, and justify the addition in the PR. Never add a library as a side effect.
5. **No secrets in code.** Configuration comes from environment variables only. Update the relevant
   `.env.example` when adding a variable — never commit real values.

### Verification commands

Client (`client/`):

```bash
npm run lint     # oxlint — zero errors AND zero warnings
npm run build    # tsc -b + vite build — type-check and build must succeed
```

Server (`server/`):

```bash
ruff check .            # zero violations
ruff format --check .   # already formatted
uvicorn main:app        # must boot without errors
```

If a check fails on code you did not touch, do not silence it with ignore comments — flag it instead.

## Client architecture (`client/src/`)

```
client/src/
├── main.tsx        # entry: StrictMode + BrowserRouter — no logic here
├── App.tsx         # route definitions only
├── pages/          # one component per route (e.g. Home.tsx)
├── components/     # shared, reusable presentational components
├── api/            # ALL server communication lives here
│   └── axios.ts    # the single shared axios instance
└── assets/         # static files
```

- **All HTTP goes through the shared axios instance** in `client/src/api/axios.ts`. Never call `fetch`
  or create a new axios instance in a component. Add typed request functions in `client/src/api/`
  (e.g. `api/products.ts`) and call those from components.
- **Function components + hooks only.** No class components.
- **TypeScript strictness:** no `any`, no `@ts-ignore` / `@ts-expect-error`, no non-null assertions (`!`)
  to silence errors. Define explicit `interface`/`type` for props and API payloads.
- **Routing:** a new page is a component in `pages/` plus a `<Route>` in `App.tsx`. Use react-router
  navigation (`Link`, `useNavigate`) — never `window.location`.
- **Naming:** components `PascalCase.tsx`; hooks `useThing.ts`; other modules `camelCase.ts`.
- **State:** default to local `useState`/`useReducer` and lifting state up. Introduce a shared-state
  library only when genuinely needed, and then use it consistently across the app.

## Server architecture (`server/`)

The server starts as a single `main.py`. As endpoints are added, grow into this layout — and once a
folder exists, all new code must follow it:

```
server/
├── main.py              # app creation, middleware, router registration ONLY
├── routers/             # APIRouter modules per resource (e.g. products.py)
├── services/            # business logic — plain functions/classes, no FastAPI imports
├── schemas/             # Pydantic models for every request/response body
├── core/                # settings, shared dependencies, reusable service clients (config.py, clients/)
├── pyproject.toml       # Ruff configuration
├── requirements.txt     # runtime dependencies
└── requirements-dev.txt # dev tooling
```

- **Thin route handlers.** Routers parse/validate input and call a service function. Business logic
  never lives inside a route handler.
- **Pydantic schema for every request and response body.** Never accept or return raw `dict`s on
  endpoint signatures; set `response_model` on routes.
- **Type hints on every function** — parameters and return types.
- **Config via one settings module** (`core/config.py` once it exists), not scattered `os.getenv` calls.
- **Errors:** routers raise `HTTPException` with a proper status code; services raise domain exceptions,
  not HTTP ones.
- **Naming:** modules and functions `snake_case`; Pydantic models `PascalCase`.

### External-service clients (object storage, LLMs, HTTP APIs, the database)

The server-side equivalent of the frontend's single axios instance: reach every external service through
one reusable, centrally-configured client — never an SDK or connection created ad-hoc inside a router or service.

- **One client per service, built once.** Configure it from settings (`core/config.py`, env vars) and keep
  the instances together under `core/clients/` (e.g. `gcs.py`, `openrouter.py`, `db.py`). Reuse a single
  instance for the app's lifetime and reuse its connections/sessions/pool — never create one per request.
- **Inject, don't instantiate.** Hand clients to routers and services via FastAPI dependencies
  (`Annotated[Client, Depends(get_client)]`) so code stays reusable and testable. Services receive the
  client; they never import the vendor SDK or wire up credentials themselves.
- **Wrap intent, not the SDK.** Expose small, purpose-named helpers (e.g. `upload_asset(...)`) so call sites
  read as intent, and swapping a provider (GCS ↔ S3) touches one file.

This is a structural rule — *where* clients live and *how* they're shared. For each library's idiomatic
usage (FastAPI, Pydantic, Postgres), defer to that framework skill, but keep the structure above.

## Client/server API contract

- Server routes are versionless and prefixed by nginx as `/api/` in production. The client must only
  use relative paths through the shared axios instance (its base URL comes from `VITE_API_BASE_URL`).
- When you add or change a server endpoint, update the corresponding typed client function in
  `client/src/api/` in the **same** change. The Pydantic schema and the TypeScript type must stay in sync.

## Git conventions

- Branch names: `feat/<short-name>`, `fix/<short-name>`, `chore/<short-name>`.
- Commit messages: imperative and concise, e.g. `feat: add product list endpoint`.
- A PR must pass all verification commands before requesting review.
