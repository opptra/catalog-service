# Generation Input Columns

Source of truth for fields used by the Cortina curtains generate pipeline (`server/data/generate-pipeline/v1`).

Product key: **`SKU`**

---

## Required columns

These are required for every SKU we generate.

| Master column | Pipeline field | Used for |
|---|---|---|
| `SKU` | `product_key` | SKU identity, run tracking, output paths |
| `Brand Name` | `brand` | Brand token in title; Brand DNA routing |
| `Product Name` | `product_name` | Primary fact source (type, color, pattern, pack count, opacity, door/window) |
| `Description` | `description` | Text enrichment; if empty, falls back to `Product Name` |
| `Primary Image URL` | `primary_image_url` | Raw product photo for image brief + GPT image generation |

---

## Optional columns (use only if filled)

| Master column | Pipeline field | Used for |
|---|---|---|
| `Color` | `color` | Title / bullets / highlights when present |
| `Material` | `material` | Title / bullets / highlights when present |

If `Color` or `Material` is null/empty, they are **omitted** from `sku_context`. The model may infer them only from `Product Name` / `Description`.

---

## Metrics checklist (what we expect filled)

Use this as the completeness scoreboard for generate-ready SKUs.

| Metric / column | Required? | Current Cortina sample reality | Notes |
|---|---|---|---|
| `SKU` | Yes | Present | Must be unique product key |
| `Brand Name` | Yes | Present (`Cortina`) | |
| `Product Name` | Yes | Present | Main text signal today |
| `Description` | Yes (fallback allowed) | Often empty | Falls back to Product Name |
| `Primary Image URL` | Yes | Present | Required for image generation |
| `Color` | Nice to have | Often empty | Prefer explicit over inference |
| `Material` | Nice to have | Often empty | Prefer explicit over inference |

---

## Not used for generation (do not require)

These are **not** passed into text/image generation today:

- `Product Length (cm)` / package LBH / carton dims
- `Pack Size` / case pack / net quantity
- Master Title / Master Description / Master Bullets
- Marketplace titles / descriptions / bullets
- Keywords
- Pricing / cost fields
- ASIN / FSN / marketplace IDs

Reason: package dims and case-pack values were causing bad titles (e.g. fake lengths like "25 cm" / "26 feet").

---

## Also used (not spreadsheet columns)

| Input | Role |
|---|---|
| Brand DNA (`server/cortina_brand_dna.md`) | Voice, visual rules, official logo URL (logo stamped after image gen) |
| Channel rules (`channel/curtains_amazon_v1.json`) | Amazon Curtains & Drapes text/image rules |
| Generated listing text | Title + bullets + highlights fed into image briefs |

---

## What each generate step reads

| Step | Fields used |
|---|---|
| Text (title, 5 bullets, highlights) | `SKU`, `Brand Name`, `Product Name`, `Description`, `Color?`, `Material?` + Brand DNA + channel text rules |
| Image brief (JSON) | Same SKU fields + `Primary Image URL` (vision) + generated text + Brand DNA + channel image rules |
| Image render (GPT image) | JSON brief + raw `Primary Image URL`; official logo stamped after |

---

## Minimum generate-ready row

A SKU is generate-ready when these are present:

1. `SKU`
2. `Brand Name`
3. `Product Name`
4. `Primary Image URL`
5. `Description` preferred (else Product Name is used as fallback)
