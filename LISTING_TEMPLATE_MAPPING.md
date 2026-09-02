# Listing template mapping

How we fill Amazon’s listing `.xlsm` after generation.

Not the ingest spreadsheet. Ingest writes our PIM (`sku_master.attributes`: `SKU`, `Color`, …). Listing fill reads that bag plus generated title / bullets / images, and writes Amazon columns (`item_sku`, `color_name`, …).

---

## What we store

One blank Amazon workbook per **category × marketplace**.

| Where | What |
|-------|------|
| GCS | Blank `.xlsm` (layout, dropdowns, macros) |
| `listing_template.metadata` | Sheet offsets: labels row 4, machine keys row 5, data from row 7 |
| `listing_template_column` | One row per Excel column: `column_index` (where to write), `resolve_stage` (fill order), `config` JSONB (the **rule**) |

`config` stores the rule, not the SKU’s cell value. The value is computed at fill.

---

## Three names (do not mix)

Amazon’s Template sheet already has two names. A third is ours.

| Name | Whose | Example | Role |
|------|--------|---------|------|
| `label` (stored) | Amazon header row | `Seller SKU` | Human / prompts |
| workbook key row | Amazon machine-key row | `item_sku` | **Parse-time only** — match CSV / discover parents. Not stored on column config. |
| `source.key` (stored) | Our ingest header | `SKU` | Read PIM |

Parent dropdowns use `depends_on: <parent column_index>` (Excel column number), never a marketplace field name. Fill looks up the parent value by that index.

```
our SKU        →  Amazon item_sku (column_index N)
our Color      →  Amazon color_name
generated TITLE     →  Amazon item_name
generated IMAGE 1   →  Amazon main_image_url
```

---

## How fill works

`fill_type` = how. `source` = where (when copying).

- `SKU_MASTER` — PIM. `key` = ingest header exactly (`SKU`, `Color`).
- `GENERATION` — job output. Needs `attribute_name` + `slot`. `index` (1-based) picks one item from a JSON array (bullets). No `index` → join with spaces (keywords).

Columns fill in `resolve_stage` order (parents first). Same stage can run together.

| `fill_type` | Does |
|-------------|------|
| `SKIP` | Leave blank |
| `CONSTANT` | Write `constant_value` |
| `DIRECT_MAP` | Copy from `source` |
| `IMAGE` | Copy generated `IMAGE` slot → Dropbox HTTPS URL |
| `ENUM` | Pick from Amazon’s list. PIM `source` = exact-match hint only. Else model, constrained to the list |
| `AI_TEXT` | Fill-time free text from PIM + photos. No `source` |

Gaps (required empty, parent missing, enum not in list, upload failed) are reported, not fatal. Optional skip is not a gap.

---

## `config` examples

Every rule has `fill_type`, `requiredness` (`ALWAYS` \| `OPTIONAL`), `label`. Then only the fields for that type.

**Copy PIM**

```json
{ "fill_type": "DIRECT_MAP", "requiredness": "ALWAYS", "label": "Seller SKU",
  "source": { "from": "SKU_MASTER", "key": "SKU" } }
```

**Copy generated title**

```json
{ "fill_type": "DIRECT_MAP", "requiredness": "ALWAYS", "label": "Item Name",
  "source": { "from": "GENERATION", "attribute_name": "TITLE", "slot": 1 } }
```

**One bullet** (`index` 1-based; `bullet_point2` uses `"index": 2`)

```json
{ "fill_type": "DIRECT_MAP", "requiredness": "OPTIONAL", "label": "Bullet Point 1",
  "source": { "from": "GENERATION", "attribute_name": "BULLET_POINTS", "slot": 1, "index": 1 } }
```

**Keywords** (no `index` → join the array)

```json
{ "fill_type": "DIRECT_MAP", "requiredness": "OPTIONAL", "label": "Generic Keywords",
  "source": { "from": "GENERATION", "attribute_name": "BACKEND_KEYWORDS", "slot": 1 } }
```

**Image** (slot 2 → `other_image_url1`; we store the rule, not the URL)

```json
{ "fill_type": "IMAGE", "requiredness": "ALWAYS", "label": "Main Image URL",
  "source": { "from": "GENERATION", "attribute_name": "IMAGE", "slot": 1 } }
```

**Constant / skip / free text**

```json
{ "fill_type": "CONSTANT", "requiredness": "ALWAYS", "label": "Update / Delete", "constant_value": "Update" }
{ "fill_type": "SKIP", "requiredness": "OPTIONAL", "label": "Product ID" }
{ "fill_type": "AI_TEXT", "requiredness": "OPTIONAL", "label": "Material" }
```

**Dropdown** — list from Amazon. Optional PIM hint: if `Color` is `"Black"`, write `Black` and skip the model.

```json
{ "fill_type": "ENUM", "requiredness": "ALWAYS", "label": "Color",
  "valid_values": ["Black", "White", "Navy"],
  "source": { "from": "SKU_MASTER", "key": "Color" } }
```

**Parent-gated dropdown** — child stage runs after parent. `depends_on` is the parent’s Excel `column_index`. If that parent cell is `NFL`, only NFL teams are allowed.

```json
{ "fill_type": "ENUM", "requiredness": "OPTIONAL", "label": "League Name",
  "valid_values": ["NFL", "NBA"] }
{ "fill_type": "ENUM", "requiredness": "OPTIONAL", "label": "Team Name",
  "depends_on": 12,
  "valid_values_by_parent": { "NFL": ["New England Patriots"], "NBA": ["Los Angeles Lakers"] } }
```

---

## Setup vs fill

1. Upload blank `.xlsm` → GCS + `listing_template`.
2. Offline setup lives under `ops/listing_mapping/` (not under `server/`):
   - `PYTHONPATH=ops:server python -m listing_mapping` — mapping CSV + blank `.xlsm` → attribute_spec + template metadata + column SQL
   - `PYTHONPATH=ops:server python -m listing_mapping.generate_columns` — workbook-only columns (dropdowns → `ENUM` + lists; others → `DIRECT_MAP` **with no `source`**)
   - Marketplace Valid Values / Dropdown Lists sheet titles: `ops/listing_mapping/config/marketplace_listing_workbooks.json`
3. Human sets `source` / `IMAGE` / `CONSTANT` / `SKIP` / `AI_TEXT` if using generate_columns alone. Fill rejects `DIRECT_MAP` with no `source`.
4. `POST /api/listings/fill` walks stages, writes cells, returns a signed `*_filled.xlsm`.

Runtime fill code: `server/dto/listing_config.py`, `server/services/listing.py`, `server/utils/listing_template_columns.py`.
