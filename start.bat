@echo off
cd /d "C:\Users\abhij\Downloads\PromptForge"

echo Starting Prompt Processing System...

:: Start the FastAPI server in a new window
start "API Server" cmd /k "uvicorn app.main:app --reload"

:: Wait 3 seconds for the server to be ready
timeout /t 3 /nobreak > nul

:: Start the worker in a new window
start "Worker" cmd /k "python -m app.workers.worker"

:: Open the browser
start http://localhost:8000/

echo Done! Two windows opened: API Server and Worker.
