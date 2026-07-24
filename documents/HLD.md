# Catalog OS V1 — High-Level Design

Internal system for Opptra: authenticate into a brand, upload product data into PIM, generate marketplace-ready content with AI (grounded in brand DNA + category intelligence), then fill listing templates (NPI). AI usage is trackable.

---

## Tech stack

| Tech | Role | Why |
|------|------|-----|
| **React (Vite SPA)** | UI | Fast client UI for upload, jobs, progress, downloads. Repo uses Vite (not Next.js). |
| **FastAPI (Python)** | Public + internal API | Thin HTTP layer for UI and for Cloud Workflows workers; fits async jobs and typed contracts. |
| **Postgres (GCP)** | System of record | Relational data: users/brands, category hierarchy + validations, PIM, intel/DNA, jobs, versioned SKU×marketplace outputs. |
| **GCS** | Object storage | Large binaries only — images/media, Excel templates, filled listing files. |
| **GCP Cloud Workflows** | Job orchestration | Fan-out per SKU with retries; keeps long generation off the request path. |
| **OpenRouter** | AI gateway | One gateway for all models (text/image); pick model per task; usage attributable per user/brand. |
| **Google sign-in** | Auth | Brand membership + role enforced in the app layer (reusable across Opptra apps later). |
| **Sentry + Langsmith** | Observability | App errors/perf (Sentry); LLM traces (Langsmith). |

Internal worker calls use shared **`client-id` + `client-token`**.

---

## Where data lives

| Store | Holds |
|-------|--------|
| **Postgres** | Users, brands, roles · category hierarchy + validations · category intelligence · brand DNA · PIM · jobs / phase maps · **versioned SKU × marketplace** generation data · usage/cost |
| **GCS** | Images/media · listing templates (`.xlsx` / `.xlsm` / `.xls`) · filled listing files |

---

## End-to-end flow

```mermaid
sequenceDiagram
    actor UI
    participant Public_API
    participant Postgres as Postgres<br/>(users, brands, roles,<br/>category hierarchy + validations,<br/>intel, brand DNA, PIM,<br/>jobs, versioned SKU×marketplace data)
    participant Cloud_Workflows
    participant Internal_Execute
    participant GCS as GCS<br/>(media, templates,<br/>listing files)
    participant AI as OpenRouter

    rect rgb(245, 245, 245)
        Note over UI,Postgres: 1. Auth
        UI->>Public_API: Google sign-in
        Public_API->>Postgres: resolve user, brand access, role
        Public_API-->>UI: authenticated (brand + role)
    end

    rect rgb(245, 245, 245)
        Note over UI,Postgres: 2. Upload / PIM<br/>(UX still open — new vs existing,<br/>when to offer generate / listing)
        UI->>Public_API: upload product flat file (brand)
        Public_API->>Postgres: validate against category rules<br/>(product carries a category)
        alt validation fails
            Public_API-->>UI: upload not accepted
        else validation ok
            Public_API->>Postgres: upsert PIM
            Public_API-->>UI: success — offer generate<br/>(and/or next steps — TBD)
        end
    end

    rect rgb(245, 245, 245)
        Note over UI,AI: 3. Generation (open attribute set)<br/>User enables what to generate — default all on<br/>(title, bullets, description, images,<br/>A+ images, image types, …)
        UI->>Public_API: POST /jobs (brand, skus, marketplace,<br/>enabled attributes)
        Public_API->>Postgres: Job + SKUs PENDING
        Public_API->>Cloud_Workflows: start(jobId)
        Public_API-->>UI: jobId

        Cloud_Workflows->>Internal_Execute: execute(jobId, skuId)<br/>client-id + client-token
        Internal_Execute->>Postgres: load phase map, PIM,<br/>category intel, brand DNA
        Internal_Execute->>Internal_Execute: combine intel + DNA + PIM
        Internal_Execute->>AI: generate enabled attributes only
        AI-->>Internal_Execute: outputs for enabled fields
        Internal_Execute->>GCS: store images / media (if enabled)
        Internal_Execute->>Postgres: store versioned SKU × marketplace<br/>attrs + phase / status
        Internal_Execute-->>Cloud_Workflows: 200 or fail

        UI->>Public_API: GET /jobs/{jobId}
        Public_API->>Postgres: read Job + SKUs
        Public_API-->>UI: status + counts + phase maps

        loop regenerate selected attribute(s) anytime
            UI-->>Public_API: same job path, scoped attrs<br/>(e.g. one image)
            Note over Postgres,GCS: new version for that<br/>SKU × marketplace attribute<br/>(prior versions kept)
        end
    end

    rect rgb(245, 245, 245)
        Note over UI,GCS: 4. NPI listing
        UI->>Public_API: POST listing export<br/>(brand, skus, marketplace)
        Public_API->>Postgres: load current versioned generation + PIM
        Public_API->>GCS: load marketplace template
        Public_API->>Public_API: fill known fields; classify gaps
        opt gaps need AI
            Public_API->>AI: fill missing template fields
            AI-->>Public_API: values
        end
        Public_API->>GCS: write filled listing file
        Public_API->>Postgres: record export + path
        Public_API-->>UI: download
    end
```

| Stage | Summary |
|-------|---------|
| **1. Auth** | Google → user + brand + role |
| **2. Upload / PIM** | Category-wise validate → upsert PIM → success. **UX open** (new vs old, generate vs listing timing). |
| **3. Generation** | Open pipeline: user picks attributes (**all on by default** — title, bullets, description, images, A+ images, image types, …). Workflows → execute → versioned SKU×marketplace attrs. **Regenerate** loops the same path for selected attr(s) → new version; older kept |
| **4. NPI listing** | Template from GCS + current generation data → fill (AI for gaps) → listing file in GCS |

---

## Locked

| Topic | Decision |
|-------|----------|
| PIM, category, intel, brand DNA | **Postgres** |
| Images, templates, listing files | **GCS** |
| Generation | Open attribute set (title, bullets, description, images, A+ images, image types, …); **all enabled by default** |
| Generation grain | **SKU × marketplace**, per-attribute **versioned** |
| Regenerate | Loop on generation: same path, selected attribute(s) → new version |
| Internal auth | **`client-id` + `client-token`** |
| Templates | Excel family (`.xlsx` / `.xlsm` / `.xls`) |

---

## Open

**Upload / PIM user flow** — how new vs existing products are shown, when generate vs listing is offered, whether one upload can mix both. Left flexible until decided.
