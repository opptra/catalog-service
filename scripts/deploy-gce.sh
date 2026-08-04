#!/usr/bin/env bash
set -euo pipefail

# Deploy by replacing MIG VMs. New instances run the instance-template startup
# script (scripts/instance-startup.sh), which pulls :latest images from Artifact
# Registry and loads the "server" section of the catalog-service secret.
#
# Default path is a regional (zone-agnostic) MIG so replaces can land in any
# zone in the region when one zone is out of capacity.
#
# Required env:
#   MIG_NAME
#   MIG_REGION          (regional MIG — preferred; e.g. asia-south1)
# Optional:
#   MIG_ZONE            (zonal MIG only — legacy; do not set with MIG_REGION)
#   PROJECT_ID          (defaults to gcloud config)
#   MAX_SURGE           (default: 0)
#   MAX_UNAVAILABLE     (default: 3 — required for many regional MIGs)
#   WAIT_FOR_STABLE     (default: true) — wait until MIG is stable after replace

: "${MIG_NAME:?MIG_NAME is required}"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
: "${PROJECT_ID:?PROJECT_ID is required}"

MAX_SURGE="${MAX_SURGE:-0}"
MAX_UNAVAILABLE="${MAX_UNAVAILABLE:-3}"
WAIT_FOR_STABLE="${WAIT_FOR_STABLE:-true}"

MIG_REGION="${MIG_REGION:-}"
MIG_ZONE="${MIG_ZONE:-}"

if [[ -n "${MIG_REGION}" && -n "${MIG_ZONE}" ]]; then
  echo "Set only one of MIG_REGION or MIG_ZONE, not both." >&2
  exit 1
fi

if [[ -z "${MIG_REGION}" && -z "${MIG_ZONE}" ]]; then
  echo "MIG_REGION is required (regional / zone-agnostic MIG)." >&2
  echo "For a legacy zonal MIG only, set MIG_ZONE instead." >&2
  exit 1
fi

location_args=()
location_label=""
if [[ -n "${MIG_REGION}" ]]; then
  location_args=(--region="${MIG_REGION}")
  location_label="region ${MIG_REGION}"
else
  echo "Warning: MIG_ZONE is legacy; prefer a regional MIG with MIG_REGION." >&2
  location_args=(--zone="${MIG_ZONE}")
  location_label="zone ${MIG_ZONE}"
fi

echo "Replacing MIG ${MIG_NAME} (${location_label})"
echo "  max-surge=${MAX_SURGE} max-unavailable=${MAX_UNAVAILABLE}"
echo "  New VMs will pull catalog-client:latest + catalog-server:latest via startup script."

gcloud compute instance-groups managed rolling-action replace "${MIG_NAME}" \
  --project="${PROJECT_ID}" \
  "${location_args[@]}" \
  --max-surge="${MAX_SURGE}" \
  --max-unavailable="${MAX_UNAVAILABLE}"

if [[ "${WAIT_FOR_STABLE}" == "true" ]]; then
  echo "Waiting for MIG to become stable..."
  gcloud compute instance-groups managed wait-until "${MIG_NAME}" \
    --project="${PROJECT_ID}" \
    "${location_args[@]}" \
    --stable
  echo "MIG is stable."
fi

echo "MIG replace finished. Check startup logs on new VMs and LB backend health."
