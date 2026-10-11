@echo off
cd /d "%~dp0"
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
