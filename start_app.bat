@echo off
chcp 65001 >nul
title Grand Mobile Support Copilot - Web UI
echo ======================================================================
echo  🚀 Grand Mobile Support Copilot - Панель оператора (Streamlit UI)
echo ======================================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python не найден в системе! Установите Python 3.10+
    pause
    exit /b 1
)

echo [INFO] Запуск веб-панели оператора на порту 8501...
echo [INFO] Откройте в браузере: http://localhost:8501
echo.
start http://localhost:8501
python -m streamlit run admin_ui.py --server.port 8501 --server.headless false

pause
