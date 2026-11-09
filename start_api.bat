@echo off
chcp 65001 >nul
title Grand Mobile Support Copilot - REST API
echo ======================================================================
echo  🚀 Grand Mobile Support Copilot - FastAPI REST API (/triage)
echo ======================================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python не найден в системе! Установите Python 3.10+
    pause
    exit /b 1
)

echo [INFO] Запуск REST API сервера на порту 8000...
echo [INFO] Интерактивная документация Swagger: http://localhost:8000/docs
echo.
timeout /t 2 /nobreak >nul
start http://localhost:8000/docs
python main.py

pause
