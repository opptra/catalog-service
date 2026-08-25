#!/bin/bash
# Creates the second database the API expects. Runs only on first volume init.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c 'CREATE DATABASE "user-service";'
