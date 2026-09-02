---
name: pack-inbound-inputs
description: Pack unstructured product + image-link CSVs (public Google Drive URLs) into wizard inbound-QC files. Use when the user has Bombay-style Details + Split CSVs and wants attributes.csv + images.zip for upload or inbound QC.
---

# Pack inbound inputs

Do **not** write a one-off script. Run the repo CLI from `server/` (venv on).

## When

User has unstructured catalog files (product facts CSV + a CSV of Drive image links) and wants wizard / inbound-QC inputs.

## Run

```bash
cd server
source .venv/bin/activate
python -m pipelines.pack_inbound_inputs.cli
```

Defaults (Bombay Dyeing unstructured drop):

| Flag | Default |
|---|---|
| `--details` | `<repo>/sample_data/bombay-unst/BD-Details-FK.csv` |
| `--images-csv` | `<repo>/sample_data/bombay-unst/Image Enhancement - Split.csv` |
| `--out-dir` | `<repo>/local-data/job-inputs/bombay-unst` |

Optional: `--limit N`, `--workers N` (default 8), `--skip-images` (CSV + empty ZIP, no Drive).

Output:

- `attributes.csv` — `SKU` first (Opptra SKU)
- `images.zip` — `images/{SKU}/image_01.jpg`, … (wizard layout)
- `pack_failures.csv` — remaining Drive failures and SKUs with no images (`no_images=yes`)

Drive files must be shared **anyone with the link**. Cache: `out-dir/.drive-cache/`
(re-runs skip files already cached; safe to stop and resume).

## After it finishes

Report the printed paths (`attributes:`, `images:`, `no-images:` / `failed:` if any).

To QC those files:

```bash
cd server
python -m pipelines.inbound_qc.cli \
  --product <attributes.csv> \
  --images <images.zip>
```
