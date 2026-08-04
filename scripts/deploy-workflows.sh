#!/usr/bin/env bash
set -euo pipefail

# Deploy the workflows listed in cloud-workflows/manifest.yaml as Cloud Workflows.
# A workflow YAML sitting in cloud-workflows/ is NOT deployed unless it has an
# entry in the manifest — this keeps a WIP file in that folder from shipping
# by accident. Each id must match the corresponding _*_WORKFLOW constant in
# server/services/*.py (e.g. job-pipeline <-> server/services/job.py
# _JOB_PIPELINE_WORKFLOW).
#
# Executions use the project's default Compute Engine service account
# (grant that SA Secret Manager access on catalog-service-cloud-secret).
#
# Required env:
#   PROJECT_ID
#   REGION          (from Secret Manager / server.env — no script default)
# Optional:
#   WORKFLOWS_DIR   (default: cloud-workflows)
#   MANIFEST        (default: <WORKFLOWS_DIR>/manifest.yaml)

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
: "${PROJECT_ID:?PROJECT_ID is required}"
: "${REGION:?REGION is required (from Secret Manager server.REGION)}"

WORKFLOWS_DIR="${WORKFLOWS_DIR:-cloud-workflows}"
MANIFEST="${MANIFEST:-${WORKFLOWS_DIR}/manifest.yaml}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f "${MANIFEST}" ]]; then
  echo "Manifest not found: ${MANIFEST}" >&2
  exit 1
fi

ids=()
sources=()
current_id=""
while IFS= read -r line; do
  trimmed="$(sed -E 's/#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//' <<<"${line}")"
  [[ -z "${trimmed}" ]] && continue
  if [[ "${trimmed}" =~ ^-[[:space:]]*id:[[:space:]]*(.+)$ ]]; then
    current_id="${BASH_REMATCH[1]}"
  elif [[ "${trimmed}" =~ ^source:[[:space:]]*(.+)$ ]]; then
    if [[ -z "${current_id}" ]]; then
      echo "Manifest error: 'source' with no preceding '- id' in ${MANIFEST}" >&2
      exit 1
    fi
    ids+=("${current_id}")
    sources+=("${BASH_REMATCH[1]}")
    current_id=""
  fi
done < "${MANIFEST}"

if [[ ${#ids[@]} -eq 0 ]]; then
  echo "No workflows listed in ${MANIFEST}" >&2
  exit 1
fi

for i in "${!ids[@]}"; do
  name="${ids[i]}"
  source_file="${WORKFLOWS_DIR}/${sources[i]}"
  if [[ ! -f "${source_file}" ]]; then
    echo "Manifest entry '${name}' points at missing file: ${source_file}" >&2
    exit 1
  fi
  echo "Deploying workflow ${name} (${source_file}) → ${REGION}"
  gcloud workflows deploy "${name}" \
    --source="${source_file}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
done

echo "Deployed ${#ids[@]} workflow(s)."
