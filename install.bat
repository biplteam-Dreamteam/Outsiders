@echo off
chcp 65001 >nul
title Grand Mobile Support Copilot - Установка
echo ======================================================================
echo  🚀 Grand Mobile Support Copilot - Автоматическая установка
echo ======================================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python не найден! Установите Python 3.10 или выше с python.org
    pause
    exit /b 1
)

echo [1/3] Проверка и обновление pip...
python -m pip install --upgrade pip

echo.
echo [2/3] Установка зависимостей из requirements.txt...
python -m pip install -r requirements.txt

echo.
echo [3/3] Проверка работоспособности системы...
python -c "import fastapi, catboost, orjson, streamlit, rapidfuzz; print('Все зависимости успешно установлены!')"

echo.
echo ======================================================================
echo  Установка завершена! Теперь вы можете запускать:
echo   - start_app.bat   : Запуск графического интерфейса оператора
echo   - start_api.bat   : Запуск REST API сервера
echo   - run_predict.bat : Пакетная обработка тикетов
echo ======================================================================
pause
