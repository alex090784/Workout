# Build-time gate (Rune review, 2026-09-17): deploying either Cloud Function
# without first verifying shared/session_parser.py is byte-identical across
# both deploy directories was previously a MANUAL step (scripts/sync_shared_parser.sh)
# that someone had to remember to run. Rune called that a trap, not an acceptable
# trade-off -- two copies of a free-text parser silently drifting is the single
# most common failure mode across this project's history. These targets make
# that verification a hard prerequisite: `make deploy-daily-feedback` and
# `make deploy-sync` cannot reach the `gcloud functions deploy` step if
# sync_shared_parser.sh exits non-zero (it does, on any sha256 mismatch).
#
# Usage:
#   make deploy-daily-feedback
#   make deploy-sync
#   make verify-parser     # just the check, no deploy

PROJECT  := abm2020
REGION   := europe-west1

.PHONY: verify-parser deploy-daily-feedback deploy-sync

verify-parser:
	@./scripts/sync_shared_parser.sh

deploy-daily-feedback: verify-parser
	cd cloud_function && gcloud functions deploy garmin-daily-feedback \
		--project=$(PROJECT) --region=$(REGION) --gen2 --runtime=python312 \
		--entry-point=garmin_daily_feedback --source=. --trigger-http \
		--no-allow-unauthenticated --timeout=120 \
		--service-account=garmin-feedback-sa@$(PROJECT).iam.gserviceaccount.com \
		--max-instances=1 --concurrency=1

deploy-sync: verify-parser
	cd cloud_function_sync && gcloud functions deploy training-plan-sync \
		--project=$(PROJECT) --region=$(REGION) --gen2 --runtime=python312 \
		--entry-point=training_plan_sync --source=. --trigger-http \
		--no-allow-unauthenticated --timeout=180 \
		--service-account=training-plan-sync-sa@$(PROJECT).iam.gserviceaccount.com \
		--max-instances=1 --concurrency=1
