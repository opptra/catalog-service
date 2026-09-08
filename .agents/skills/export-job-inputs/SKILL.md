---
name: export-job-inputs
description: Rebuild a generation job's original wizard inputs (attributes.csv + images.zip) from sku_master.attributes and GCS source photos. Use when the user gives a job external_id and asks to export, reconstruct, recover, or regenerate original input files, product CSV, images ZIP, or files uploadable to the generation / inbound-QC pipeline.
---

# Export job inputs

Do **not** write a one-off script. Run the repo CLI from `server/` (venv on).

## When

User has a **GENERATION** `job.external_id` and wants the original product spreadsheet + photos ZIP (wizard / inbound-QC shape).

## Run

```bash
cd server
source .venv/bin/activate
python -m pipelines.export_job_inputs.cli --job-id <job-external-id>
```

Optional:

| Flag | Effect |
|---|---|
| `--limit N` | First N live SKUs in `sku_generation_job` order |
| `--out-dir PATH` | Override output dir |

Default output: `<repo>/local-data/job-inputs/<job-external-id>/`

- `attributes.csv` — `SKU` first, then `sku_master.attributes` keys
- `images.zip` — `images/{SKU}/{filename}` (wizard layout)

## Prerequisites

Read-only. Needs:

- `server/.env`: `GCS_BUCKET`, `GOOGLE_CLOUD_PROJECT`, catalog DB
- ADC (`gcloud auth application-default login`)
- Cloud SQL Auth Proxy (or whatever `DB_HOST`/`DB_PORT` point at)

If GCS token refresh fails, tell the user to re-run `gcloud auth application-default login`. Do not invent credentials.

## Data path (do not reimplement)

```
job.external_id
  → sku_generation_job (job_id)
    → sku_master.attributes["SKU"] + other attribute columns
      → gs://{GCS_BUCKET}/products/{SKU}/assets/images/
```

Generated images under `jobs/{job}/sku_generation_jobs/.../images/` are **not** originals. Skip them.

FLATFILE_UPLOAD jobs are rejected — pass a GENERATION job id.

## After it finishes

Report the printed paths (`attributes:`, `images:`, `no-images:` if any).

To QC those files:

```bash
cd server
python -m pipelines.inbound_qc.cli \
  --product <attributes.csv> \
  --images <images.zip>
```
