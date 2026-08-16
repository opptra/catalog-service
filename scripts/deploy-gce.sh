#!/usr/bin/env bash
set -euo pipefail

# Deploy by restarting MIG VMs. On boot, instance-startup.sh pulls :latest
# images from Artifact Registry and reloads the "server" section of the
# catalog-service secret. Faster than rolling replace (no new VM provisioning).
#
# Use rolling replace manually when the instance template / startup-script
# itself changes — restart does not apply a new template.
#
# Required env:
#   MIG_NAME
#   REGION              (from Secret Manager server.REGION — no script default)
# Optional:
#   MIG_ZONE            (zonal MIG only — legacy; do not set with REGION)
#   PROJECT_ID          (defaults to gcloud config)
#   MAX_UNAVAILABLE     (default: 3 — required for many regional MIGs)
#   WAIT_FOR_STABLE     (default: true) — wait until MIG is stable after restart

: "${MIG_NAME:?MIG_NAME is required}"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
: "${PROJECT_ID:?PROJECT_ID is required}"

MAX_UNAVAILABLE="${MAX_UNAVAILABLE:-3}"
WAIT_FOR_STABLE="${WAIT_FOR_STABLE:-true}"

# Prefer REGION (from secret/env); accept legacy MIG_REGION as an alias.
MIG_REGION="${REGION:-${MIG_REGION:-}}"
MIG_ZONE="${MIG_ZONE:-}"

if [[ -n "${MIG_REGION}" && -n "${MIG_ZONE}" ]]; then
  echo "Set only one of REGION or MIG_ZONE, not both." >&2
  exit 1
fi

if [[ -z "${MIG_REGION}" && -z "${MIG_ZONE}" ]]; then
  echo "REGION is required (from Secret Manager server.REGION)." >&2
  echo "For a legacy zonal MIG only, set MIG_ZONE instead." >&2
  exit 1
fi

location_args=()
location_label=""
if [[ -n "${MIG_REGION}" ]]; then
  location_args=(--region="${MIG_REGION}")
  location_label="region ${MIG_REGION}"
else
  echo "Warning: MIG_ZONE is legacy; prefer a regional MIG with REGION." >&2
  location_args=(--zone="${MIG_ZONE}")
  location_label="zone ${MIG_ZONE}"
fi

echo "Restarting MIG ${MIG_NAME} (${location_label})"
echo "  max-unavailable=${MAX_UNAVAILABLE}"
echo "  VMs will re-run startup and pull catalog-client:latest + catalog-server:latest."

gcloud compute instance-groups managed rolling-action restart "${MIG_NAME}" \
  --project="${PROJECT_ID}" \
  "${location_args[@]}" \
  --max-unavailable="${MAX_UNAVAILABLE}"

if [[ "${WAIT_FOR_STABLE}" == "true" ]]; then
  echo "Waiting for MIG to become stable..."
  gcloud compute instance-groups managed wait-until "${MIG_NAME}" \
    --project="${PROJECT_ID}" \
    "${location_args[@]}" \
    --stable
  echo "MIG is stable."
fi

echo "MIG restart finished. Check startup logs on VMs and LB backend health."
