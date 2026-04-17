#!/usr/bin/env bash
# Create or update a Google Cloud Scheduler HTTP job that POSTs to qzWhatNext's
# internal daily schedule endpoint. Requires gcloud and an authenticated account.
#
# Usage:
#   export PROJECT_ID=my-gcp-project
#   export REGION=us-central1                    # Cloud Scheduler job location
#   export SERVICE_URL="https://qzwhatnext-xxxxx.run.app"
#   export QZ_INTERNAL_JOB_SECRET='(same value configured on Cloud Run)'
#   ./scripts/setup_cloud_scheduler_daily.sh
#
# Optional overrides:
#   JOB_NAME=my-job-id          # any valid Scheduler job name (console UI names like daily_rebuild are fine).
#                               # Default below is only an example for gcloud create/update.
#   SCHEDULE_CRON="0 5 * * *"   # 05:00 in TIME_ZONE
#   TIME_ZONE="America/New_York"
#
# Do NOT commit real secrets. Prefer: export QZ_INTERNAL_JOB_SECRET="$(gcloud secrets versions access latest --secret=qz-internal-job-secret)"

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
SERVICE_URL="${SERVICE_URL:-}"
SECRET="${QZ_INTERNAL_JOB_SECRET:-}"
JOB_NAME="${JOB_NAME:-qzwhatnext-daily-schedule}"
SCHEDULE_CRON="${SCHEDULE_CRON:-0 5 * * *}"
TIME_ZONE="${TIME_ZONE:-America/New_York}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: Set PROJECT_ID" >&2
  exit 1
fi
if [[ -z "$SERVICE_URL" ]]; then
  echo "ERROR: Set SERVICE_URL to your Cloud Run HTTPS base URL (no trailing slash)" >&2
  exit 1
fi
if [[ -z "$SECRET" ]]; then
  echo "ERROR: Set QZ_INTERNAL_JOB_SECRET (must match Cloud Run env on the service)" >&2
  exit 1
fi

URI="${SERVICE_URL%/}/internal/jobs/daily-schedule"

gcloud config set project "$PROJECT_ID" >/dev/null

gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT_ID" >/dev/null

if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" >/dev/null 2>&1; then
  echo "Updating existing job $JOB_NAME..."
  gcloud scheduler jobs update http "$JOB_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE_CRON" \
    --time-zone="$TIME_ZONE" \
    --uri="$URI" \
    --http-method=POST \
    --update-headers="X-qzwhatnext-job-secret=$SECRET" \
    --attempt-deadline=600s
else
  echo "Creating job $JOB_NAME..."
  gcloud scheduler jobs create http "$JOB_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE_CRON" \
    --time-zone="$TIME_ZONE" \
    --uri="$URI" \
    --http-method=POST \
    --headers="X-qzwhatnext-job-secret=$SECRET" \
    --attempt-deadline=600s
fi

echo "Done. Ensure Cloud Run has QZ_INTERNAL_JOB_SECRET set to the same value, e.g.:"
echo "  gcloud run services update qzwhatnext --region=$REGION --set-env-vars=QZ_INTERNAL_JOB_SECRET=***"
echo "(Use Secret Manager for production; do not pass secrets on the command line in shared history.)"
