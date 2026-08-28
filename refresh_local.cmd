@echo off
REM Refresco semanal del token en el .env local (mantiene vivo el camino-PC).
cd /d "C:\Users\aguss\Desktop\ig-stories-bot"
echo ---- %DATE% %TIME% refresh_local >> logs\task.log
".venv\Scripts\python.exe" manage.py refresh-token --write-env --force >> logs\task.log 2>&1
