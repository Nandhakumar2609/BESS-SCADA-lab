@echo off
cd /d "%~dp0"
docker compose -f docker-compose.simple.yml down
pause
