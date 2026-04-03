# run_workers.ps1
# VSM Backend – Celery Execution Script for Windows
#
# USAGE:
#   .\run_workers.ps1
#
# This script starts the Celery worker and beat service with the '-P solo' pool
# which is required for stable execution on Windows.

Write-Host "Starting VSM Celery Workers with Pool: SOLO..." -ForegroundColor Cyan

# Start the worker with all queues
# -A app.workers.celery_app: The Celery app instance
# -P solo: Required for Windows compatibility
# --loglevel=info: Standard logging level
# -Q ...: Listen to all defined queues
# -B: Also run the Celery Beat scheduler in this process (convenient for dev)

celery -A app.workers.celery_app worker -P solo --loglevel=info -Q event_processing,nlp_processing,aggregation,ai_trigger -B
