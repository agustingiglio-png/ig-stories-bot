@echo off
REM Publicacion local (Programador de tareas de Windows) - 13:00 ART
REM Trae el estado mas reciente (por si la nube ya publico) y publica.
REM Es idempotente: si ya se publico hoy, no repite.
cd /d "C:\Users\aguss\Desktop\ig-stories-bot"
echo ---- %DATE% %TIME% inicio publish_local >> logs\task.log
call git pull --rebase --autostash >> logs\task.log 2>&1
".venv\Scripts\python.exe" manage.py publish >> logs\task.log 2>&1
echo ---- %DATE% %TIME% fin publish_local >> logs\task.log
