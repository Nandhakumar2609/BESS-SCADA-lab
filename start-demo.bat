@echo off
REM BESS SCADA lab - one-click demo for Windows (needs Docker Desktop running)
cd /d "%~dp0"
docker info >nul 2>&1 || (echo Docker Desktop is not running. Start it, wait for "Engine running", then try again. & pause & exit /b 1)
if not exist .env copy .env.example .env >nul
set GRAFANA_ANONYMOUS_VIEWER=true
echo Starting simulator, gateway, InfluxDB and Grafana (first run downloads images, a few minutes)...
docker compose -f docker-compose.simple.yml up -d --build || (echo Start failed - copy the messages above and send them for help. & pause & exit /b 1)
echo Waiting for Grafana...
:wait
timeout /t 3 >nul
curl -s -o nul http://localhost:3000/api/health || goto wait
start http://localhost:3000/d/bess-overview
echo.
echo Grafana is open at http://localhost:3000  (dashboards: BESS Site Overview, BESS Alarms ^& Communications)
echo Data appears after about 1 minute. To stop: stop-demo.bat
pause
