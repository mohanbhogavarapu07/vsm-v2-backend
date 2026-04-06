# launch_all.ps1
# VSM - Unified Process Orchestrator
# Starts all 4 VSM components in separate windows.

Write-Host "--- VSM 'START THE GAME' ORCHESTRATOR ---" -ForegroundColor Cyan

# 1. Start VSM Backend (Port 8000)
Write-Host "1/4 Starting Backend..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd c:\vsmv2\vsm-backend; uvicorn app.main:app --port 8000 --reload"

# 2. Start Celery Workers
Write-Host "2/4 Starting Celery Workers..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd c:\vsmv2\vsm-backend; .\run_workers.ps1"

# 3. Start VSM AI Agent (Port 8001)
Write-Host "3/4 Starting AI Agent..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd c:\vsmv2\vsm-ai-agent; uvicorn app.main:app --port 8001 --reload"

# 4. Start VSM Frontend (Port 8080)
Write-Host "4/4 Starting Frontend..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd c:\vsmv2\vsm-v2-frontend; npx vite --port 8080 --strictPort"

Write-Host "----------------------------------------" -ForegroundColor Green
Write-Host "All services are launching. Check the new windows for logs." -ForegroundColor Green
Write-Host "Dashboard: http://localhost:8080" -ForegroundColor Green
