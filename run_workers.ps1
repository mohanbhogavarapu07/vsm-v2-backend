# run_workers.ps1
# VSM Backend – Celery Execution Script for Windows
#
# This script starts the Celery worker and beat service as separate processes
# as required for stable execution on Windows.

Write-Host "Starting VSM Celery Worker (Pool: SOLO) in a new window..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "celery -A app.workers.celery_app worker -P solo --loglevel=info -Q event_processing,nlp_processing,aggregation,ai_trigger"

Write-Host "Starting VSM Celery Beat Scheduler in a new window..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "celery -A app.workers.celery_app beat --loglevel=info"

Write-Host "Both services are starting. Please keep the new windows open." -ForegroundColor Yellow
